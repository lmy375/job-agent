"""``job agent``：LangGraph 路线的入口（无人值守跑完整条流程）。

**这是 `cli/` 唯一允许 import `agent/` 的地方**，而且只 import 运行器一个模块。
两条执行路线的逻辑仍然互不依赖（CLAUDE.md 的铁律，`tests/test_boundaries.py`
按文件名把这条豁免钉死）——这里做的只有「把命令行选项翻成
:class:`AgentRunOptions`」，一行流程逻辑都不写。

import 放在函数体里是为了启动速度：``runner`` 会连带拉起 langgraph，
而 ``job search`` / ``job score`` 用不到它，不该让每次敲 ``job`` 都等它加载。
"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.help import h
from job_agent.cli.state import CliState


def agent(
    ctx: typer.Context,
    collect: Annotated[
        bool, typer.Option("--collect", help="先采集（等价于 job search：搜索 + 抓 JD）。")
    ] = False,
    apply_enabled: Annotated[
        bool,
        typer.Option("--apply", help="出完计划后进入投递确认。投递不可撤销，默认不开。"),
    ] = False,
    top: Annotated[
        int | None, typer.Option("-n", help=h("送审岗位数上限，覆盖 [agent].top_n。"))
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help=h("用哪个模型接入点（[agent.providers.*] 的表名）。")),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="覆盖选中接入点的 model（模型 ID）。")
    ] = None,
    thread: Annotated[
        str | None,
        typer.Option("--thread", help="运行 ID。中断后传同一个可从 checkpoint 续跑。"),
    ] = None,
) -> None:
    from job_agent.agent.runner import AgentRunOptions, run

    state: CliState = ctx.obj
    code = run(
        AgentRunOptions(
            profile=state.profile,
            config_file=state.config_file,
            collect=collect,
            apply_enabled=apply_enabled,
            top=top,
            provider=provider,
            model=model,
            thread=thread,
        )
    )
    raise typer.Exit(code=code)
