"""``job score``：按当前 profile 的 ``match.toml`` 信号表给库里的职位分诊排序。

打分是**确定性**的：同一份数据、同一份信号表，两次跑出来的分数与排序完全一样。
「该不该投」那一步是判断，归 ``/job-match`` skill，不在这里。

三种输出形式共用同一次打分，所以三者的排序必然一致：终端表格（默认）、
``--json``（给脚本）、``--shortlist``（候选清单骨架 Markdown，判断部分留白）。
"""

from __future__ import annotations

from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict, TypeAdapter

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.config import Settings
from job_agent.core.matching import ScoredJob, load_rules, rank, render_shortlist
from job_agent.core.matching.shortlist import TODO, write_shortlist

#: 终端默认只列这么多；再多就该看 --shortlist 或 job web 了
DEFAULT_TOP = 20


class ScoreJson(BaseModel):
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
    keyword: str
    dupes: int
    url: str
    hits: list[str]
    penalties: list[str]
    offTrack: bool


#: 一次构造、反复使用；顺带保证 --json 的输出始终符合 ScoreJson 的 schema
_SCORE_JSON = TypeAdapter(list[ScoreJson])


def score(
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
    as_shortlist: Annotated[
        bool,
        typer.Option(
            "--shortlist",
            help="写出候选清单骨架 Markdown（路径取 match.shortlist_output），判断部分留白。",
        ),
    ] = False,
    no_dedupe: Annotated[
        bool, typer.Option("--no-dedupe", help="不按 JD 正文去重。")
    ] = False,
) -> None:
    if as_json and as_shortlist:
        raise typer.BadParameter("--json 与 --shortlist 是两种输出形式，一次只能选一种。")

    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings

    rules = load_rules(settings.match.rules)
    jobs = rank(context.db, settings, rules, floor_wan=floor, dedupe=not no_dedupe)

    if not jobs:
        echo_warn(
            "没有可排序的职位。先跑 job search（搜完会自动抓 JD）；"
            "如果库里有数据，可能是 --floor / match.salary_floor_wan 门槛太高。"
        )
        raise typer.Exit(code=1)

    if as_json:
        payload = [_as_json(job) for job in jobs[:top]]
        typer.echo(_SCORE_JSON.dump_json(payload, indent=2).decode())
        return

    if as_shortlist:
        _write_shortlist(jobs, settings, top=top, floor=floor)
        return

    threshold = floor if floor is not None else settings.match.salary_floor_wan
    scope = f"薪资上限 ≥ {threshold:.0f} 万" if threshold is not None else "全部"
    typer.secho(f"{scope}：{len(jobs)} 条，按分数排序（前 {min(top, len(jobs))} 条）", bold=True)
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

    typer.echo(
        "\n下一步：job score --shortlist 生成候选清单骨架，"
        "再跑 /job-match 让 Claude 逐条读 JD。"
    )


def _write_shortlist(
    jobs: list[ScoredJob], settings: Settings, top: int, floor: float | None
) -> None:
    """把前 ``top`` 条渲染成候选清单骨架并落盘。

    判断部分刻意留成 :data:`TODO` 标记——填一段模板话术，人会以为已经分析过了。
    """
    content = render_shortlist(jobs, settings, limit=top, floor_wan=floor)
    path = write_shortlist(content, settings.match.shortlist_output)

    echo_ok(f"候选清单已生成（{min(top, len(jobs))}/{len(jobs)} 条）：{path}")
    typer.echo(
        f"\n里面有 {content.count(TODO)} 处 `{TODO}` 等着填——那是需要读 JD 才能回答的部分。"
        "\n下一步：在 Claude Code 里跑 `/job-match`，它会逐条读 JD、比硬门槛、排投递优先级。"
    )


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


def _as_json(job: ScoredJob) -> ScoreJson:
    row = job.row
    return ScoreJson(
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
        keyword=row.keyword,
        dupes=row.dupes,
        url=row.url,
        hits=[h.label() for h in job.hits],
        penalties=[h.label() for h in job.penalties],
        offTrack=job.off_track,
    )
