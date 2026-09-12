"""``job llm-score``：让模型给职位打两个维度的分，各 1-10 分并附依据。

和 ``job score`` 是两回事，摆在一起看最清楚：

=============  =======================  ==============================
               ``job score``            ``job llm-score``
=============  =======================  ==============================
判断依据       ``[score]`` 关键词命中   读 JD 与简历的语义判断
成本           本地几毫秒               每条一次模型调用，按条计费
刷新粒度       整表重写全库排名         按条 upsert，已打的留着
默认范围       全库                     **必须显式指定**
=============  =======================  ==============================

「必须显式指定」是这个命令唯一的强约束：不给 jobId、不给 ``--top``、
不给 ``--all``，直接报错退出。一条命令顺手花掉几千次调用的钱，
不该是「忘了带参数」就能触发的。

两个维度并列落库，不合成总分——「够不着的好岗」和「够得着的烂岗」
合成出来一样高，而这两种情况该做的事完全不同。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict, TypeAdapter

from job_agent.cli.help import h
from job_agent.cli.state import CliState, band, clip, echo_ok, echo_warn
from job_agent.config import Settings
from job_agent.context import AppContext
from job_agent.core.matching import LlmScoreSummary, build_scorer, score_all


class LlmScoreJson(BaseModel):
    """``--json`` 的输出条目。脚本要读的契约，所以定成 model 而不是现拼 dict。"""

    model_config = ConfigDict(extra="forbid")

    jobId: int
    title: str
    company: str
    salaryLowWan: float | None
    salaryHighWan: float | None
    #: 岗位吸引力（1-10）：从求职者角度，这份工作本身值多少分
    appeal: int
    #: 胜任匹配度（1-10）：从招聘方角度，这个人拿到它的概率
    fit: int
    appealReasons: list[str]
    fitReasons: list[str]


_LLM_SCORE_JSON = TypeAdapter(list[LlmScoreJson])


def llm_score(
    ctx: typer.Context,
    job_ids: Annotated[
        list[int] | None, typer.Argument(help="要打分的 jobId，可以传多个。")
    ] = None,
    top: Annotated[
        int | None,
        typer.Option("--top", help=h("按 [score] 关键词分数取前 N 条送模型。")),
    ] = None,
    every: Annotated[
        bool,
        typer.Option("--all", help="库里所有抓到 JD 的职位。要二次确认（--yes 跳过）。"),
    ] = False,
    floor: Annotated[
        float | None,
        typer.Option("--floor", help="只取薪资上限 ≥ 这个数的岗位（万元/年，税前口径）。"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="同模型同提示词已经打过的也重打（默认跳过，省钱）。"),
    ] = False,
    concurrency: Annotated[
        int | None,
        typer.Option("--concurrency", "-j", help=h("并发上限，默认取 [llm_score].concurrency。")),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help=h("临时换接入点（[agent.providers.*] 里的表名）。")),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="临时换模型名（不改配置文件）。")
    ] = None,
    why: Annotated[bool, typer.Option("--why", help="展开每条的打分依据。")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="输出 JSON（给脚本用）。")
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "把 JSON 写进这个文件而不是打到终端（给了它就等于带上 --json）。"
                "相对路径按当前 profile 的目录解析。"
            ),
        ),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过 --all 的二次确认。")] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings
    _override_model(settings, provider, model)

    targets = _resolve_targets(settings, context, job_ids, top, every, floor)
    if every and not yes:
        typer.confirm(
            f"将对 {len(targets)} 条职位调用 {settings.llm_score_model_label}"
            "（按条计费，已打过的会自动跳过），继续？",
            abort=True,
        )

    target_file = None if output is None else settings.profile_dir / output
    # 要往 stdout 吐 JSON 时，进度改走 stderr——管道另一头等的是能解析的文本
    to_stdout_json = as_json and target_file is None
    scorer = build_scorer(
        settings, context.db, context.llm_scores, state.progress(err=to_stdout_json)
    )
    summary = scorer.run(targets, force=force, concurrency=concurrency)

    if as_json or target_file is not None:
        _emit_json(summary, target_file)
        return
    _emit_table(summary, why)


# ---------------------------------------------------------------- 范围与覆盖


def _override_model(settings: Settings, provider: str | None, model: str | None) -> None:
    """``--provider`` / ``--model`` 的临时覆盖，照抄 agent runner 的做法。

    直接赋值不会重跑 ``model_validator``，所以 provider 存不存在得自己挡一下。
    """
    if provider is not None:
        if provider not in settings.agent.providers:
            known = "、".join(sorted(settings.agent.providers))
            echo_warn(
                f"--provider {provider} 没有对应的 [agent.providers.{provider}] 表；"
                f"已定义的有：{known}"
            )
            raise typer.Exit(code=2)
        settings.llm_score.provider = provider
    if model is not None:
        settings.llm_score_active.model = model


def _resolve_targets(
    settings: Settings,
    context: AppContext,
    job_ids: list[int] | None,
    top: int | None,
    every: bool,
    floor: float | None,
) -> list[int]:
    """确定这次给哪些职位打分。三种指定方式互斥，一个都不给就报错。"""
    if job_ids:
        return list(dict.fromkeys(job_ids))

    if top is None and not every:
        echo_warn(
            "LLM 打分按条计费，必须说清楚打哪些。三选一：\n"
            "  job llm-score 1234 5678     指定 jobId\n"
            "  job llm-score --top 30      按关键词分数取前 30 条\n"
            "  job llm-score --all         全库（会要求确认）"
        )
        raise typer.Exit(code=2)

    # 关键词分数只用来挑人，不落库：库里的名次什么时候变该由 job score 说了算
    ranked = score_all(context.db, settings).view(settings, floor_wan=floor)
    if not ranked:
        echo_warn(
            "没有符合条件的职位——库里可能还没抓到 JD（先跑 job search），"
            "或者 --floor / [score].salary_floor_wan 卡得太高。"
        )
        raise typer.Exit(code=1)
    return [job.job_id for job in (ranked if every else ranked[:top])]


# ------------------------------------------------------------------ 输出


def _emit_json(summary: LlmScoreSummary, target: Path | None) -> None:
    payload = [
        LlmScoreJson(
            jobId=r.jobId,
            title=r.title,
            company=r.company,
            salaryLowWan=r.salaryLow,
            salaryHighWan=r.salaryHigh,
            appeal=r.appeal,
            fit=r.fit,
            appealReasons=r.appealReasons,
            fitReasons=r.fitReasons,
        )
        for r in summary.results
    ]
    blob = _LLM_SCORE_JSON.dump_json(payload, indent=2).decode()
    if target is None:
        typer.echo(blob)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(blob, encoding="utf-8")
    echo_ok(f"{len(payload)} 条已写入：{target}")


def _emit_table(summary: LlmScoreSummary, why: bool) -> None:
    echo_ok(
        f"新打 {summary.scored} 条，跳过 {summary.skipped} 条，失败 {summary.failed} 条"
        f"（模型 {summary.provider} / {summary.model}，提示词指纹 {summary.fingerprint}）"
    )
    if summary.errors:
        typer.secho(f"  失败明细：{'；'.join(summary.errors[:5])}", fg=typer.colors.YELLOW)
    if not summary.results:
        typer.echo("这次没有新打的分数。库里已有的用 job web 或 job stats 看。")
        return

    typer.echo("")
    typer.echo(f"{'吸引':>4}{'胜任':>6}  {'年薪(万)':<12}岗位 / 公司")
    # 先看吸引力再看胜任度：值不值得投是第一问，够不够得着是第二问
    for r in sorted(summary.results, key=lambda x: (-x.appeal, -x.fit)):
        typer.echo(
            f"{r.appeal:>4}{r.fit:>6}  {band(r.salaryLow, r.salaryHigh):<14}"
            f"{clip(r.title, 40)} | {clip(r.company, 20)}"
        )
        if why:
            for reason in r.appealReasons:
                typer.secho(f"        岗位 · {reason}", fg=typer.colors.GREEN)
            for reason in r.fitReasons:
                typer.secho(f"        胜任 · {reason}", fg=typer.colors.CYAN)

    typer.echo(
        "\n两个分数是并列的，代码不替你合成总分："
        "吸引力高但胜任度低 = 值得投但要准备说服，反过来 = 稳但未必想去。"
        "\n下一步：job web 在页面上按任一列排序；打够了样本就跑 job align，"
        "看关键词信号表跟模型判断差在哪（/job-align 帮你改）。"
    )
