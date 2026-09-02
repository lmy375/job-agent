"""LangGraph 路线的运行器：组图、跑图、在投递前停下来等人拍板。

入口是 ``job agent``（见 ``cli/commands/agent_cmd.py``）——那一层只负责解析选项，
真正的流程全在这里。**这个模块不 import 任何 ``cli`` / ``web`` 的东西**，
共享的只有内核（``core/``、``config/``、``context``），边界见 CLAUDE.md。

langgraph 那几个刻意留在 :func:`run` 里面 import：它们加载得不快，
而 ``job search`` / ``job score`` 根本用不到——不该让每次敲 ``job`` 都等它们。
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from job_agent.errors import JobAgentError


class AgentRunOptions(BaseModel):
    """一次运行的选项。CLI 那层把命令行参数翻成它，运行器只认这个 model。"""

    model_config = ConfigDict(extra="forbid")

    #: 用哪个 profile（profiles/ 下的目录名）。None = 取 [profiles].default
    profile: str | None = None
    #: 全局配置文件路径。None = 自动查找
    config_file: Path | None = None
    #: 先采集（等价于 job search：搜索 + 抓 JD），否则直接用库内数据
    collect: bool = False
    #: 出完计划后进入投递确认。投递不可撤销，默认不开
    apply_enabled: bool = False
    #: 送审岗位数上限，覆盖 [agent].top_n
    top: int | None = None
    #: 用哪个模型接入点（[agent.providers.*] 的表名），覆盖 [agent].provider
    provider: str | None = None
    #: 覆盖选中接入点的 model（模型 ID）
    model: str | None = None
    #: 运行 ID。中断后传同一个可从 checkpoint 续跑
    thread: str | None = None


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


def run(options: AgentRunOptions) -> int:
    """跑完一次 采集 → 分诊 → 审读 → 投递计划（→ 投递确认），返回退出码。"""
    # 延迟到这里 import：langgraph 加载不快，不该拖慢每一次 `job` 调用
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command

    from job_agent.agent.build import build_graph, state_serde
    from job_agent.agent.llm import build_llm
    from job_agent.agent.state import AgentState
    from job_agent.context import AppContext

    try:
        ctx = AppContext.create(
            profile=options.profile, config_file=options.config_file
        )
    except JobAgentError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 2

    settings = ctx.settings
    if options.top is not None:
        settings.agent.top_n = options.top
    if options.provider is not None:
        # 赋值不会重跑 model_validator，这里自己挡一下
        if options.provider not in settings.agent.providers:
            known = "、".join(sorted(settings.agent.providers))
            print(
                f"!! --provider {options.provider} 没有对应的 "
                f"[agent.providers.{options.provider}] 表；已定义的有：{known}",
                file=sys.stderr,
            )
            ctx.close()
            return 2
        settings.agent.provider = options.provider
    if options.model is not None:
        settings.agent.active.model = options.model

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
    thread_id = options.thread or f"run-{time.strftime('%Y%m%d-%H%M%S')}"
    app = build_graph(ctx, llm, SqliteSaver(conn, serde=state_serde()))
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "max_concurrency": settings.agent.max_concurrency,
        # 一次运行的全部 trace 归进同一个 thread，在 LangSmith 里按它检索
        "metadata": {"thread_id": thread_id},
    }

    print(f"== job agent 开始运行（thread={thread_id}，模型={settings.agent.model_label}）==")
    exit_code = 0
    try:
        # 续跑已有 thread 时传 None，从 checkpoint 接着走；新 thread 给初始状态
        state: AgentState | None = None
        if not (options.thread and app.get_state(config).next):
            state = AgentState(collect=options.collect, apply_enabled=options.apply_enabled)
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
