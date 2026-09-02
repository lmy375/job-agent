"""``job score``：按当前 profile 的 ``[score]`` 信号表**重新给全库打分**并落库。

每次都是刷新：读 ``[score]`` 现在的样子，算一遍全库，整表重写 ``job_scores``。
改了权重就再跑一次，Web 端和后续命令读到的都是新分数。

打分是**确定性**的：同一份数据、同一份信号表，两次跑出来的分数与排序完全一样。
「该不该投」那一步是判断，归 ``/job-match`` skill，不在这里。

落库的是**全量、未过滤**的分数与全库排名；``--floor`` / ``-n`` / 去重只影响
这次**看到**什么，不影响写进库里的名次。

输出形式两个维度正交，共用同一次打分，所以排序必然一致：

===========  ==================================  ============================
             不带 ``--json``                     带 ``--json``
===========  ==================================  ============================
不带 ``-o``  终端表格                            JSON 打到 stdout
带 ``-o``    候选清单骨架 Markdown 写进文件      JSON 写进文件
===========  ==================================  ============================
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict, TypeAdapter

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.config import Settings
from job_agent.core.matching import ScoredJob, refresh, render_shortlist
from job_agent.core.matching.shortlist import TODO, write_shortlist

#: 终端默认只列这么多；再多就该写进文件（-o）或看 job web 了
DEFAULT_LIMIT = 20


class ScoreJson(BaseModel):
    """``--json`` 的输出条目。字段是脚本要读的契约，所以定成 model 而不是现拼 dict。"""

    model_config = ConfigDict(extra="forbid")

    jobId: int
    score: float
    #: 全库排名（按分数降序，1 起）；与 --floor / -n 无关
    rank: int
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
    limit: Annotated[int, typer.Option("-n", help="取前几条。")] = DEFAULT_LIMIT,
    why: Annotated[
        bool, typer.Option("--why", help="每条都展开命中与扣分的信号。")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON（给脚本用）。")] = False,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "写进这个文件而不是打到终端：默认写候选清单骨架，配 --json 则写 JSON。"
                "相对路径按当前 profile 的目录解析（产物跟着 profile 走）。"
            ),
        ),
    ] = None,
    no_dedupe: Annotated[
        bool, typer.Option("--no-dedupe", help="不按 JD 正文去重。")
    ] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings

    if not settings.score.signals:
        echo_warn(
            f"当前 profile 的 [score] 段里没有任何 [[score.signals]]：{settings.profile_file}\n"
            "  所有岗位都会是 0 分，排序没有意义。跑 /job-init 让 Claude 按访谈生成。"
        )
        raise typer.Exit(code=2)

    result = refresh(context.db, settings)
    jobs = result.view(settings, floor_wan=floor, dedupe=not no_dedupe)

    if not result.jobs:
        echo_warn(
            "库里没有带 JD 的职位，打不了分。先跑 job search（搜完会自动抓 JD）。"
        )
        raise typer.Exit(code=1)
    if not jobs:
        echo_warn(
            f"已给 {len(result.jobs)} 条打分入库，但没有一条过得了当前门槛——"
            "--floor / [score].salary_floor_wan 调低点再看。"
        )
        raise typer.Exit(code=1)

    # 相对路径落到 profile 目录里：产物跟着 profile 走，两个 profile 不会互相覆盖。
    # 这一层和 [storage].database 那些配置路径是同一个口径，别按 cwd 解析
    target = None if output is None else settings.profile_dir / output

    ranks = {job.job_id: i for i, job in enumerate(result.jobs, 1)}
    if as_json:
        payload = [_as_json(j, ranks[j.job_id]) for j in jobs[:limit]]
        blob = _SCORE_JSON.dump_json(payload, indent=2).decode()
        if target is None:
            typer.echo(blob)
        else:
            echo_ok(f"{min(limit, len(jobs))} 条已写入：{_write(blob, target)}")
        return

    if target is not None:
        _write_shortlist(jobs, settings, limit=limit, floor=floor, output=target)
        return

    threshold = floor if floor is not None else settings.score.salary_floor_wan
    scope = f"薪资上限 ≥ {threshold:.0f} 万" if threshold is not None else "全部"
    echo_ok(f"已重新打分并入库：{len(result.jobs)} 条（信号表指纹 {result.fingerprint}）")
    typer.echo("")
    typer.secho(f"{scope}：{len(jobs)} 条，按分数排序（前 {min(limit, len(jobs))} 条）", bold=True)
    typer.secho(
        "  分数只做分诊，不代表结论——该不该投要读 JD，跑 /job-match。",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.echo("")
    typer.echo(f"{'分':>5}  {'年薪(万)':<12}岗位 / 公司")

    for job in jobs[:limit]:
        typer.echo(f"{job.score:>5.0f}  {_band(job.salary_low, job.salary_high):<14}"
                   f"{_clip(job.title, 40)} | {_clip(job.company, 20)}")
        if why:
            if job.hits:
                typer.secho(f"        + {job.reasons()}", fg=typer.colors.GREEN)
            if job.penalties:
                typer.secho(f"        − {job.concerns()}", fg=typer.colors.YELLOW)

    typer.echo(
        "\n下一步：job score -n 12 -o data/shortlist.md 生成候选清单骨架，"
        "再跑 /job-match 让 Claude 逐条读 JD；或 job web 在页面上按分数翻。"
    )


def _write(content: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_shortlist(
    jobs: list[ScoredJob],
    settings: Settings,
    limit: int,
    floor: float | None,
    output: Path,
) -> None:
    """把前 ``limit`` 条渲染成候选清单骨架并落盘。

    判断部分刻意留成 :data:`TODO` 标记——填一段模板话术，人会以为已经分析过了。
    """
    content = render_shortlist(jobs, settings, limit=limit, floor_wan=floor)
    path = write_shortlist(content, output)

    echo_ok(f"候选清单已生成（{min(limit, len(jobs))}/{len(jobs)} 条）：{path}")
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


def _as_json(job: ScoredJob, rank: int) -> ScoreJson:
    row = job.row
    return ScoreJson(
        jobId=job.job_id,
        score=round(job.score, 1),
        rank=rank,
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
