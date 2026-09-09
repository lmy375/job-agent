"""``job stats``：终端里的数据概览。

**只报库存，不做分析**：库里有多少条、抓了多少 JD、投了多少、薪资什么水位。
「这个市场在招什么方向、要什么技能」不在这里——那是分析，因人而异，
归 skill 或用户自己的脚本（见 CLAUDE.md「不承担市场分析」一节）。
"""

from __future__ import annotations

import typer

from job_agent.cli.state import CliState
from job_agent.core.llm import load_score_prompts
from job_agent.core.storage import LlmScoreStatus, ScoreStatus

_TOP_KEYWORDS = 12


def stats(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings

    total = context.jobs.count()
    details = context.details.status_counts()
    applications = context.applications.status_counts()
    floor = settings.score.salary_floor_wan
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
            "（[score].salary_floor_wan 没配，不报达标比例）"
        )

    score = context.scores.status(settings.score.fingerprint)
    typer.echo(f"  已打分          {score.scored}{_score_note(score)}")

    llm = context.llm_scores.status(
        settings.llm_score_provider_name,
        settings.llm_score_active.model,
        load_score_prompts(settings).fingerprint,
    )
    typer.echo(f"  LLM 打分        {llm.scored}/{llm.scorable}{_llm_note(llm)}")

    typer.secho("\n按搜索关键词", bold=True)
    for row in context.jobs.keyword_counts()[:_TOP_KEYWORDS]:
        typer.echo(f"  {row.keyword:<16}{row.count:>6}")


def _score_note(score: ScoreStatus) -> str:
    """落库分数新鲜不新鲜。过期就直说该重跑——旧分数看不出旧，最容易被当成现在的。"""
    if score.scored == 0:
        return "  ← 还没打过分，跑 job score"
    if score.stale:
        return "  ← [score] 改过但没重新打分，跑 job score"
    if score.missing:
        return f"  ← 还有 {score.missing} 条有 JD 没打分，跑 job score"
    return f"（{score.scoredAt:%Y-%m-%d %H:%M}）" if score.scoredAt else ""


def _llm_note(llm: LlmScoreStatus) -> str:
    """LLM 打分的覆盖率提示。

    「还有多少没打」刻意**不**说成待办：按条计费，大部分没打过是常态，
    天天喊「还差 3000 条」只会让人学会忽略它。真该提醒的是口径不一致——
    库里混着别的模型或别的提示词判出来的分数，那些和现在这批没法比。
    """
    if llm.scored == 0:
        return "  ← 还没打过，跑 job llm-score --top 30"
    note = f"（{llm.scoredAt:%Y-%m-%d %H:%M}）" if llm.scoredAt else ""
    if llm.stale:
        extra = llm.scored - llm.current
        return f"{note}  ← 其中 {extra} 条是别的模型或旧提示词判的，与现在的口径不可比"
    return note


def _fmt(counts: dict[str, int]) -> str:
    return "（" + "，".join(f"{k}:{v}" for k, v in counts.items()) + "）" if counts else ""
