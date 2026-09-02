"""``job stats``：终端里的数据概览。"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.state import CliState
from job_agent.core.analysis import analyze

_TOP_KEYWORDS = 12


def stats(
    ctx: typer.Context,
    tracks: Annotated[
        bool, typer.Option("--tracks", help="额外跑一遍分类统计（较慢，需要已抓取的 JD）。")
    ] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()

    total = context.jobs.count()
    details = context.details.status_counts()
    applications = context.applications.status_counts()
    salary = context.jobs.salary_summary()

    typer.secho(f"数据库：{context.settings.storage.database}", bold=True)
    typer.echo(f"  职位总数        {total}")
    typer.echo(f"  已抓详情        {sum(details.values())}  {_fmt(details)}")
    typer.echo(f"  投递记录        {sum(applications.values())}  {_fmt(applications)}")
    typer.echo(
        f"  薪资可解析      {salary.parsed}  其中上限 ≥100 万："
        f"{salary.meets100}（{salary.meets100Pct}%）  平均上限 {salary.avgHighWan} 万"
    )

    typer.secho("\n按方向（searchKeyword）", bold=True)
    for row in context.jobs.keyword_counts()[:_TOP_KEYWORDS]:
        track = context.settings.search.track_for_keyword(row.keyword) or "未归类"
        typer.echo(f"  {row.keyword:<16}{row.count:>6}   {track}")

    if not tracks:
        typer.echo("\n（加 --tracks 可看赛道 / 角色分布）")
        return

    typer.secho("\n赛道分布（按 JD 正文去重后）", bold=True)
    data = analyze(context.db, context.settings)
    typer.echo(f"  有效 JD 共 {data.total} 份")
    for track, count in data.trackCounts.most_common():
        info = data.tracks.get(track)
        median = info.salaryMedianHigh if info else None
        top_role = info.roles[0][0] if info and info.roles else "—"
        typer.echo(
            f"  {track:<6}{count:>6}   中位上限 {median or '—'} 万   主要角色：{top_role}"
        )


def _fmt(counts: dict[str, int]) -> str:
    return "（" + "，".join(f"{k}:{v}" for k, v in counts.items()) + "）" if counts else ""
