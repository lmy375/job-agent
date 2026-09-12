"""``job align``：拿库里的 LLM 分当参照，给当前 profile 的 ``[score]`` 信号表体检。

回答的是一个确定性的问题：**关键词分诊把模型认可的岗位送进视野了没有？**
输出全是统计——秩相关、窗口召回、逐条信号的命中均分与差值、漏网与误报清单、
候选正则的探针结果。**改哪条信号、权重调到几，它不说**：那是判断，
归 ``/job-align`` skill 与人。

它**不写库**（挑窗口用 ``score_all`` 内存现算），所以随便跑；
改完信号表要让 Web 与 ``job stats`` 看到新分数，仍然要跑 ``job score``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, clip, echo_ok, echo_warn
from job_agent.core.matching import AlignReport, AlignThresholds, align
from job_agent.core.matching.align import AlignJob, HitStat, ProbeStat, SignalStat

#: 漏网 / 误报清单在终端里最多列这么多；再多就该 --json 了
LIST_LIMIT = 40


def align_cmd(
    ctx: typer.Context,
    top: Annotated[
        int, typer.Option("--top", help="分诊窗口：view 里前几名算「进了视野」。")
    ] = 100,
    appeal_floor: Annotated[
        int,
        typer.Option(
            "--appeal-floor", help="LLM「认可」的吸引力下限（含）。默认对齐内置提示词锚点。"
        ),
    ] = 7,
    fit_floor: Annotated[
        int, typer.Option("--fit-floor", help="LLM「认可」的匹配度下限（含）。")
    ] = 5,
    low_ceiling: Annotated[
        int, typer.Option("--low", help="吸引力 ≤ 这个数算「模型明确不看」。")
    ] = 4,
    floor: Annotated[
        float | None,
        typer.Option("--floor", help="只看薪资上限 ≥ 这个数的岗位（万元/年，税前口径）。"),
    ] = None,
    split: Annotated[
        bool, typer.Option("--split", help="把每条信号按顶层 | 拆成子模式分别统计。")
    ] = False,
    probes: Annotated[
        list[str] | None,
        typer.Option("--probe", help="试一条候选正则（可重复）：标题 / 正文命中的岗位模型均分。"),
    ] = None,
    context_snippets: Annotated[
        bool, typer.Option("--context", help="探针附带命中处的文本快照。")
    ] = False,
    why: Annotated[
        bool, typer.Option("--why", help="漏网 / 误报清单展开模型的打分依据。")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON（给脚本用）。")] = False,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="把 JSON 写进这个文件（相对路径按当前 profile 的目录解析）。"
        ),
    ] = None,
) -> None:
    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings

    if not settings.score.signals:
        echo_warn(
            f"当前 profile 的 [score] 段里没有任何 [[score.signals]]：{settings.profile_file}\n"
            "  没有信号表就没有可校准的东西。跑 /job-init 先生成一份。"
        )
        raise typer.Exit(code=2)

    thresholds = AlignThresholds(
        appeal_floor=appeal_floor, fit_floor=fit_floor, low_ceiling=low_ceiling, top=top
    )
    report = align(
        context.db,
        settings,
        thresholds=thresholds,
        floor_wan=floor,
        probes=probes or [],
        split=split,
        snippets=context_snippets,
    )

    if report.scored == 0:
        echo_warn(
            f"view 里 {report.viewSize} 条岗位没有一条有 LLM 分数，没法对照。\n"
            "  先跑 job llm-score --top N（按条计费，N 自己定），再回来。"
        )
        raise typer.Exit(code=1)

    if as_json or output is not None:
        blob = report.model_dump_json(indent=2)
        if output is None:
            typer.echo(blob)
        else:
            target = settings.profile_dir / output
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(blob, encoding="utf-8")
            echo_ok(f"报告已写入：{target}")
        return

    _print_report(report, why)


# ---------------------------------------------------------------- 终端渲染


def _print_report(report: AlignReport, why: bool) -> None:
    t = report.thresholds
    typer.secho(
        f"对照范围：view {report.viewSize} 条，其中有 LLM 分 {report.scored} 条"
        f"（统计只算这些）",
        bold=True,
    )
    if report.mixed_verdicts:
        echo_warn(
            f"llm_scores 里混着 {len(report.verdictLabels)} 种口径（模型 / 提示词），"
            "分数互相不可比——先 job llm-score --force 统一，再校准。"
        )
    typer.echo(
        f"  LLM 认可（吸引力 ≥{t.appeal_floor} 且匹配 ≥{t.fit_floor}）：{report.approvedInView} 条"
        f"　明确不看 = 吸引力 ≤{t.low_ceiling}"
    )
    typer.echo(
        f"  Spearman 关键词分 ~ 吸引力 {_fmt(report.spearmanAppeal)}"
        f"　~ 匹配度 {_fmt(report.spearmanFit)}"
    )
    for point in report.recall:
        typer.echo(
            f"  前 {point.top:>4} 名：认可 {point.approved:>3} / {report.approvedInView}"
            f"　明确不看 {point.low}"
        )

    typer.secho("\n关键词分每 10 分一档 → 模型均分（分诊有效则应单调上升）", bold=True)
    for b in report.buckets:
        typer.echo(f"  {b.floor:>5}  n={b.n:<4} 吸引力 {b.meanAppeal:.2f}  匹配 {b.meanFit:.2f}")

    typer.secho(
        "\n逐条信号（按命中数）：Δ = 命中均分 − 未命中均分；正信号该正、负信号该负", bold=True
    )
    typer.echo(
        f"  {'信号':<30}{'权重':>5}{'命中':>5}{'标题':>5}"
        f"{'吸引力':>7}{'Δ':>6}{'匹配':>6}{'Δ':>6}{'认可率':>7}{'不看率':>7}"
    )
    for s in report.signals:
        _print_signal(s)

    _print_jobs(
        f"漏网：LLM 认可但排在前 {t.top} 名之外",
        report.missed,
        why,
        "看它缺什么正信号、被哪条负信号压了",
    )
    _print_jobs(
        f"误报：进了前 {t.top} 名但模型明确不看",
        report.falsePositives,
        why,
        "看哪条正信号在乱加分",
    )

    if report.probes:
        typer.secho("\n探针", bold=True)
        for p in report.probes:
            _print_probe(p)

    typer.echo(
        "\n下一步：改 profile.toml 的 [score]（job config validate 自检），"
        "再跑一次 job align 比数字；"
        "\n定稿后 job score 刷新库里的分数。改哪条是判断——在 Claude Code 里跑 /job-align。"
    )


def _print_signal(s: SignalStat) -> None:
    color = None
    if s.deltaAppeal is not None and s.hits.hits >= 5:
        wrong_way = (s.weight > 0) != (s.deltaAppeal > 0)
        if abs(s.deltaAppeal) < 0.3 or wrong_way:
            color = typer.colors.YELLOW
    typer.secho(
        f"  {clip(s.name, 28):<30}{s.weight:>5.0f}{s.hits.hits:>5}{s.titleHits:>5}"
        f"{_fmt(s.hits.meanAppeal, 2):>7}{_fmt(s.deltaAppeal, 2, '+'):>6}"
        f"{_fmt(s.hits.meanFit, 2):>6}{_fmt(s.deltaFit, 2, '+'):>6}"
        f"{_pct(s.hits.approvedRate):>7}{_pct(s.hits.lowRate):>7}",
        fg=color,
    )
    for sub in s.subPatterns:
        st = sub.stat
        typer.secho(
            f"      {clip(sub.pattern, 44):<46}{st.hits:>5}"
            f"     {_fmt(st.meanAppeal, 2):>7}      {_fmt(st.meanFit, 2):>6}"
            f"      {_pct(st.approvedRate):>7}{_pct(st.lowRate):>7}",
            fg=typer.colors.BRIGHT_BLACK,
        )


def _print_jobs(title: str, jobs: list[AlignJob], why: bool, hint: str) -> None:
    typer.secho(f"\n{title}：{len(jobs)} 条", bold=True)
    if not jobs:
        return
    typer.secho(f"  {hint}", fg=typer.colors.BRIGHT_BLACK)
    for j in jobs[:LIST_LIMIT]:
        high = "—" if j.salaryHighWan is None else f"{j.salaryHighWan:.0f}万"
        typer.echo(
            f"  #{j.viewRank:<4} 分 {j.keywordScore:>5.0f}  吸引力 {j.appeal} 匹配 {j.fit}  "
            f"{clip(j.title, 36)} | {clip(j.company, 16)} ({high})  jobId={j.jobId}"
        )
        if j.hits:
            typer.secho(f"        + {'、'.join(j.hits)}", fg=typer.colors.GREEN)
        if j.penalties:
            typer.secho(f"        − {'、'.join(j.penalties)}", fg=typer.colors.YELLOW)
        if why:
            for reason in j.appealReasons[:2]:
                typer.secho(f"        吸引力：{clip(reason, 110)}", fg=typer.colors.BRIGHT_BLACK)
            for reason in j.fitReasons[:2]:
                typer.secho(f"        匹配：{clip(reason, 110)}", fg=typer.colors.BRIGHT_BLACK)
    if len(jobs) > LIST_LIMIT:
        typer.echo(f"  …还有 {len(jobs) - LIST_LIMIT} 条，--json 看全部")


def _print_probe(p: ProbeStat) -> None:
    typer.echo(f"  {p.pattern}")
    typer.echo(f"      标题命中 {_stat_line(p.title)}")
    typer.echo(f"      正文命中 {_stat_line(p.body)}")
    for snip in p.snippets:
        typer.secho(
            f"      [吸引力 {snip.appeal} 匹配 {snip.fit}] …{snip.text}…  jobId={snip.jobId}",
            fg=typer.colors.BRIGHT_BLACK,
        )


def _stat_line(s: HitStat) -> str:
    if s.hits == 0:
        return "0 条"
    return (
        f"{s.hits} 条  吸引力 {_fmt(s.meanAppeal, 2)}  匹配 {_fmt(s.meanFit, 2)}"
        f"  认可率 {_pct(s.approvedRate)}  不看率 {_pct(s.lowRate)}"
    )


def _fmt(value: float | None, digits: int = 3, sign: str = "") -> str:
    return "—" if value is None else f"{value:{sign}.{digits}f}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"
