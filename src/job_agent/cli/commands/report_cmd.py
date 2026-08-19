"""``job report``：生成 HTML 市场分析报告。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.core.analysis import analyze
from job_agent.core.report import build, load_insights


def report(
    ctx: typer.Context,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="输出路径，默认取配置里的 report.output。")
    ] = None,
    no_dedupe: Annotated[
        bool,
        typer.Option(
            "--no-dedupe",
            help="不按 JD 正文去重（同一岗位被多家猎头挂出时会重复计数）。",
        ),
    ] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()

    typer.echo("正在统计……")
    data = analyze(context.db, context.settings, dedupe=not no_dedupe)
    if not data["total"]:
        echo_warn("没有可用的 JD，请先执行 job search 与 job detail。")
        raise typer.Exit(code=1)

    insights = load_insights(context.settings.report.insights_dir)
    for warning in insights.warnings:
        echo_warn(warning)

    path = build(data, context.settings, output=output, insights=insights)
    echo_ok(f"报告已生成（{data['total']} 份有效 JD）：{path}")
