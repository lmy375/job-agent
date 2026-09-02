"""``job stats``：终端里的数据概览。

**只报库存，不做分析**：库里有多少条、抓了多少 JD、投了多少、薪资什么水位。
「这个市场在招什么方向、要什么技能」不在这里——那是分析，因人而异，
归 skill 或用户自己的脚本（见 CLAUDE.md「不承担市场分析」一节）。
"""

from __future__ import annotations

import typer

from job_agent.cli.state import CliState

_TOP_KEYWORDS = 12


def stats(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings

    total = context.jobs.count()
    details = context.details.status_counts()
    applications = context.applications.status_counts()
    floor = settings.match.salary_floor_wan
    salary = context.jobs.salary_summary(floor_wan=floor)

    typer.secho(f"数据库：{settings.storage.database}", bold=True)
    typer.echo(f"  职位总数        {total}")
    typer.echo(f"  已抓详情        {sum(details.values())}  {_fmt(details)}")
    typer.echo(f"  投递记录        {sum(applications.values())}  {_fmt(applications)}")
    if floor is not None:
        typer.echo(
            f"  薪资可解析      {salary.parsed}  其中上限 ≥{floor:.0f} 万："
            f"{salary.meetsFloor}（{salary.meetsFloorPct}%）  平均上限 {salary.avgHighWan} 万"
        )
    else:
        typer.echo(
            f"  薪资可解析      {salary.parsed}  平均上限 {salary.avgHighWan} 万"
            "（[match].salary_floor_wan 没配，不报达标比例）"
        )

    typer.secho("\n按搜索关键词", bold=True)
    for row in context.jobs.keyword_counts()[:_TOP_KEYWORDS]:
        typer.echo(f"  {row.keyword:<16}{row.count:>6}")


def _fmt(counts: dict[str, int]) -> str:
    return "（" + "，".join(f"{k}:{v}" for k, v in counts.items()) + "）" if counts else ""
