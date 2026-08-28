"""``job shortlist``：把打完分的前 N 条渲染成候选清单骨架。

产出的 Markdown 里，判断部分是**留白**的，等 ``/job-match`` skill 填。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.core.matching import load_rules, rank, render_shortlist
from job_agent.core.matching.shortlist import TODO, write_shortlist

DEFAULT_LIMIT = 12


def shortlist(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="输出路径，默认取配置里的 match.shortlist_output。"),
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", "-n", help="写进清单的岗位数。")
    ] = DEFAULT_LIMIT,
    floor: Annotated[
        float | None,
        typer.Option("--floor", help="只看薪资上限 ≥ 这个数的岗位（万元/年，税前口径）。"),
    ] = None,
    no_dedupe: Annotated[
        bool, typer.Option("--no-dedupe", help="不按 JD 正文去重。")
    ] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings

    rules = load_rules(settings.match.rules)
    jobs = rank(context.db, settings, rules, floor_wan=floor, dedupe=not no_dedupe)
    if not jobs:
        echo_warn("没有可用的职位。先跑 job search + job detail。")
        raise typer.Exit(code=1)

    content = render_shortlist(jobs, settings, limit=limit, floor_wan=floor)
    target = output or settings.match.shortlist_output
    path = write_shortlist(content, target)

    blanks = content.count(TODO)
    echo_ok(f"候选清单已生成（{min(limit, len(jobs))}/{len(jobs)} 条）：{path}")
    typer.echo(
        f"\n里面有 {blanks} 处 `{TODO}` 等着填——那是需要读 JD 才能回答的部分。"
        "\n下一步：在 Claude Code 里跑 `/job-match`，它会逐条读 JD、比硬门槛、排投递优先级。"
    )
