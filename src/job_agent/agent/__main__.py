"""LangGraph 路线的独立入口：``job-agent``（或 ``python -m job_agent.agent``）。

刻意不挂在 ``job``（typer CLI）下面：两条执行路线互不 import，
这一条只在装了 agent extra 时可用（``uv sync --extra agent``）。

用法：
    job-agent                 # 用库内已有数据：分诊 → 审读 → 出投递计划
    job-agent --collect       # 先采集（search + detail），再走上面的流程
    job-agent --apply         # 出完计划后进入投递确认（interrupt 等人拍板）
    job-agent --thread run-x  # 指定运行 ID；断点/中断后用同一 ID 续跑
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from typing import Any

from job_agent.errors import JobAgentError


def _require_agent_extra() -> None:
    """只检查组图与 checkpoint 的依赖。

    模型客户端（langchain-anthropic / langchain-openai）按选中的 provider
    才需要，缺哪个由 llm.build_llm 报——它知道当前选的是谁。
    """
    try:
        import langgraph
        import langgraph.checkpoint.sqlite  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            f"agent 路线的依赖未安装（{exc.name}）。\n"
            "  uv sync --extra agent    # 或 pip install 'job-agent[agent]'"
        ) from exc


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="job-agent",
        description="无人值守跑完 采集 → 分诊 → 审读 JD → 投递计划；投递前必经人工确认。",
    )
    parser.add_argument(
        "--profile",
        "-p",
        type=str,
        default=None,
        help="用哪个 profile（profiles/ 下的目录名），默认取 [profiles].default",
    )
    parser.add_argument(
        "--config", type=str, default=None, help="全局配置文件路径（默认自动查找）"
    )
    parser.add_argument(
        "--collect", action="store_true", help="先采集（job search + job detail），默认用库内数据"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="出完计划后进入投递确认。投递不可撤销，默认不开",
    )
    parser.add_argument("--top", type=int, default=None, help="送审岗位数上限，覆盖 [agent].top_n")
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="用哪个模型接入点（[agent.providers.*] 的表名），覆盖 [agent].provider",
    )
    parser.add_argument(
        "--model", type=str, default=None, help="覆盖选中接入点的 model（模型 ID）"
    )
    parser.add_argument(
        "--thread", type=str, default=None, help="运行 ID。中断后传同一 ID 从 checkpoint 续跑"
    )
    return parser.parse_args(argv)


def _read_approval(payload: Any) -> list[int]:
    """终端里等人拍板（``payload`` 是 ConfirmRequest，从 checkpoint 反序列化而来）。

    这是整条路线唯一的交互点——投递不可撤销。
    """
    print("\n== 投递确认 ==")
    print(f"完整计划见：{payload.plan_output}")
    for cand in payload.candidates:
        print(f"  [{cand.priority}/5] job_id={cand.job_id}  {cand.pitch}")
    raw = input("输入要投递的 job_id（逗号分隔，直接回车 = 放弃投递）：").strip()
    if not raw:
        return []
    try:
        return [int(part) for part in raw.replace("，", ",").split(",") if part.strip()]
    except ValueError:
        print("! 无法解析，视为放弃投递")
        return []


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _require_agent_extra()

    # 依赖就位后才 import：让上面的报错信息先于 ImportError 出现
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command

    from job_agent.agent.build import build_graph, state_serde
    from job_agent.agent.llm import build_llm
    from job_agent.agent.state import AgentState
    from job_agent.context import AppContext

    try:
        ctx = AppContext.create(profile=args.profile, config_file=args.config)
    except JobAgentError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 2

    settings = ctx.settings
    if args.top is not None:
        settings.agent.top_n = args.top
    if args.provider is not None:
        # 赋值不会重跑 model_validator，这里自己挡一下
        if args.provider not in settings.agent.providers:
            known = "、".join(sorted(settings.agent.providers))
            print(
                f"!! --provider {args.provider} 没有对应的 "
                f"[agent.providers.{args.provider}] 表；已定义的有：{known}",
                file=sys.stderr,
            )
            ctx.close()
            return 2
        settings.agent.provider = args.provider
    if args.model is not None:
        settings.agent.active.model = args.model

    try:
        llm = build_llm(settings)
    except JobAgentError as exc:
        print(f"!! {exc}", file=sys.stderr)
        ctx.close()
        return 2

    # LangSmith 追踪：config.toml 的 [agent.langsmith] 填了 api_key 才启用。
    # 它是 langchain-core 内建的，靠这几个环境变量开关——不用挂 callback handler，
    # 所以也不需要在 invoke 的 config 里塞 callbacks
    tracing = settings.agent.langsmith
    if tracing.api_key is not None:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = tracing.api_key.get_secret_value()
        os.environ["LANGSMITH_PROJECT"] = tracing.project
        if tracing.endpoint:
            os.environ["LANGSMITH_ENDPOINT"] = tracing.endpoint
        print(f"  LangSmith 追踪已启用（project={tracing.project}）")

    settings.agent.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.agent.checkpoint, check_same_thread=False)
    thread_id = args.thread or f"run-{time.strftime('%Y%m%d-%H%M%S')}"
    app = build_graph(ctx, llm, SqliteSaver(conn, serde=state_serde()))
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "max_concurrency": settings.agent.max_concurrency,
        # 一次运行的全部 trace 归进同一个 thread，在 LangSmith 里按它检索
        "metadata": {"thread_id": thread_id},
    }

    print(f"== job-agent 开始运行（thread={thread_id}，模型={settings.agent.model_label}）==")
    exit_code = 0
    try:
        # 续跑已有 thread 时传 None，从 checkpoint 接着走；新 thread 给初始状态
        state: AgentState | None = None
        if not (args.thread and app.get_state(config).next):
            state = AgentState(collect=args.collect, apply_enabled=args.apply)
        app.invoke(state, config)

        # 停在 interrupt（投递确认）时循环等人拍板
        snapshot = app.get_state(config)
        while snapshot.next:
            interrupts = [i for task in snapshot.tasks for i in task.interrupts]
            if not interrupts:
                print("!! 图停住了但没有待回答的 interrupt，检查 checkpoint", file=sys.stderr)
                exit_code = 1
                break
            approved = _read_approval(interrupts[0].value)
            app.invoke(Command(resume=approved), config)
            snapshot = app.get_state(config)

        final = app.get_state(config).values
        applied = final.get("applied") or []
        if applied:
            ok = sum(1 for o in applied if o.status == "ok")
            print(f"== 投递完成：成功 {ok}/{len(applied)} ==")
        print(f"== 结束。计划：{settings.agent.plan_output}（thread={thread_id}）==")
    except JobAgentError as exc:
        print(f"!! {exc}", file=sys.stderr)
        exit_code = 2
    except KeyboardInterrupt:
        print(f"\n! 已中断。用 --thread {thread_id} 可从 checkpoint 续跑", file=sys.stderr)
        exit_code = 130
    finally:
        if tracing.api_key is not None:
            # 上报是后台线程做的，进程退出前等它们排空，否则最后几条 trace 会丢
            try:
                from langchain_core.tracers.langchain import wait_for_all_tracers

                wait_for_all_tracers()
            except Exception as exc:  # 追踪上报失败不影响运行结果
                print(f"! LangSmith 上报未能完成：{exc}", file=sys.stderr)
        ctx.close()
        conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
