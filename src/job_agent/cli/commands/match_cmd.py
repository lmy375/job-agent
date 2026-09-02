"""``job match``：按当前 profile 的 ``match.toml`` 信号表给库里的职位分诊排序。"""

from __future__ import annotations

from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict, TypeAdapter

from job_agent.cli.state import CliState, echo_warn
from job_agent.core.matching import ScoredJob, load_rules, rank

#: 终端默认只列这么多；再多就该看 job shortlist 或 job web 了
DEFAULT_TOP = 20


class MatchJson(BaseModel):
    """``--json`` 的输出条目。字段是脚本要读的契约，所以定成 model 而不是现拼 dict。"""

    model_config = ConfigDict(extra="forbid")

    jobId: int
    score: float
    title: str
    company: str
    salary: str
    salaryLowWan: float | None
    salaryHighWan: float | None
    location: str
    industry: str
    workYears: str
    education: str
    track: str
    role: str
    keyword: str
    dupes: int
    url: str
    hits: list[str]
    penalties: list[str]
    offTrack: bool


#: 一次构造、反复使用；顺带保证 --json 的输出始终符合 MatchJson 的 schema
_MATCH_JSON = TypeAdapter(list[MatchJson])


def match(
    ctx: typer.Context,
    floor: Annotated[
        float | None,
        typer.Option("--floor", help="只看薪资上限 ≥ 这个数的岗位（万元/年，税前口径）。"),
    ] = None,
    top: Annotated[int, typer.Option("--top", "-n", help="列前几条。")] = DEFAULT_TOP,
    why: Annotated[
        bool, typer.Option("--why", help="每条都展开命中与扣分的信号。")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON（给脚本用）。")] = False,
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
        echo_warn(
            "没有可排序的职位。先跑 job search + job detail；"
            "如果库里有数据，可能是 --floor / match.salary_floor_wan 门槛太高。"
        )
        raise typer.Exit(code=1)

    if as_json:
        payload = [_as_json(job) for job in jobs[:top]]
        typer.echo(_MATCH_JSON.dump_json(payload, indent=2).decode())
        return

    threshold = floor if floor is not None else settings.match.salary_floor_wan
    scope = f"薪资上限 ≥ {threshold:.0f} 万" if threshold is not None else "全部"
    typer.secho(f"{scope}：{len(jobs)} 条，按匹配分排序（前 {min(top, len(jobs))} 条）", bold=True)
    typer.secho(
        "  分数只做分诊，不代表结论——该不该投要读 JD，跑 /job-match。",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.echo("")
    typer.echo(f"{'分':>5}  {'年薪(万)':<12}岗位 / 公司")

    for job in jobs[:top]:
        typer.echo(f"{job.score:>5.0f}  {_band(job.salary_low, job.salary_high):<14}"
                   f"{_clip(job.title, 40)} | {_clip(job.company, 20)}")
        if why:
            if job.hits:
                typer.secho(f"        + {job.reasons()}", fg=typer.colors.GREEN)
            if job.penalties:
                typer.secho(f"        − {job.concerns()}", fg=typer.colors.YELLOW)

    typer.echo("\n下一步：job shortlist 生成候选清单骨架，再跑 /job-match 让 Claude 逐条读 JD。")


def _band(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "—"
    return f"{low:.0f}-{high:.0f}"


def _clip(text: str, width: int) -> str:
    """按显示宽度截断（中文算两格），让终端里的列对得上。"""
    out, used = [], 0
    for char in text:
        step = 2 if ord(char) > 0x2E80 else 1
        if used + step > width:
            out.append("…")
            break
        out.append(char)
        used += step
    return "".join(out)


def _as_json(job: ScoredJob) -> MatchJson:
    row = job.row
    return MatchJson(
        jobId=job.job_id,
        score=round(job.score, 1),
        title=job.title,
        company=job.company,
        salary=row.salary,
        salaryLowWan=job.salary_low,
        salaryHighWan=job.salary_high,
        location=row.location,
        industry=row.industry,
        workYears=row.workYears,
        education=row.education,
        track=row.track,
        role=row.role,
        keyword=row.keyword,
        dupes=row.dupes,
        url=row.url,
        hits=[h.label() for h in job.hits],
        penalties=[h.label() for h in job.penalties],
        offTrack=job.off_track,
    )
