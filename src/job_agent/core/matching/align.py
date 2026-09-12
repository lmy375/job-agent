"""对照 LLM 打分校准关键词信号表：**只算统计，不下结论**。

关键词打分（``job score``）是分诊，LLM 打分（``job llm-score``）读得懂语义。
两套分数都在库里时，就能回答一个确定性的问题：**信号表把模型认可的岗位
送进视野了没有？** 具体拆成几件都有唯一答案的事：

- 关键词分与两个 LLM 维度的秩相关（Spearman）
- 分诊窗口（view 前 N 名）里 LLM 认可的有几条、模型明确不看的有几条
- 每条信号：命中它的岗位模型平均给几分，与没命中的差多少——
  正信号该是正差，负信号该是负差，差不多的就是噪声
- 每条信号按顶层 ``|`` 拆开，哪个子模式在乱命中
- 漏网：模型认可但关键词排到窗口之外；误报：进了窗口但模型明确不看
- 探针：任意候选正则在标题 / 正文命中的岗位模型均分——改信号表之前先试

「LLM 认可」「明确不看」的分数线是参数（:class:`AlignThresholds`），默认值
照内置提示词的分数锚点取，**不是**代码替用户定的取向。改了哪条信号、
权重调到几、要不要加一条新的，是判断——归 ``/job-align`` skill 与人。

这里**不写库**：挑窗口用 :func:`~job_agent.core.matching.scorer.score_all`
（内存里现算），库里的名次什么时候变仍由 ``job score`` 说了算。
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from job_agent.config import Settings
from job_agent.core.dataset import JobFacts
from job_agent.core.matching.scorer import ScoredJob, body_text, score_all
from job_agent.core.storage import Database, LlmScoreRepository, LlmScoreRow

#: 探针快照里每条命中前后各留多少字符
SNIPPET_MARGIN = 30
#: 探针最多带几条快照——要的是「为什么命中」的手感，不是全文
SNIPPET_LIMIT = 8


class AlignThresholds(BaseModel):
    """分数线。默认值对齐内置提示词的锚点：7-8「优先方向」、5-6「硬门槛无明确冲突」、
    3-4「方向不在期望里」。用户改了提示词就该一起改这里。"""

    model_config = ConfigDict(extra="forbid")

    #: LLM「认可」= 吸引力 ≥ appeal_floor 且匹配度 ≥ fit_floor
    appeal_floor: int = Field(default=7, ge=1, le=10)
    fit_floor: int = Field(default=5, ge=1, le=10)
    #: 吸引力 ≤ 这个数算「模型明确不看」
    low_ceiling: int = Field(default=4, ge=1, le=10)
    #: 分诊窗口：view 里前几名算「进了视野」
    top: int = Field(default=100, ge=1)

    def approved(self, appeal: int, fit: int) -> bool:
        return appeal >= self.appeal_floor and fit >= self.fit_floor

    def low(self, appeal: int) -> bool:
        return appeal <= self.low_ceiling


class AlignJob(BaseModel):
    """一条同时有两种分数的岗位。``viewRank`` 是在**有 LLM 分的 view 行**里的名次。"""

    model_config = ConfigDict(extra="forbid")

    jobId: int
    title: str
    company: str
    salaryHighWan: float | None
    keywordScore: float
    viewRank: int
    appeal: int
    fit: int
    hits: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)
    appealReasons: list[str] = Field(default_factory=list)
    fitReasons: list[str] = Field(default_factory=list)


class HitStat(BaseModel):
    """一组岗位的 LLM 分数概况。``hits`` 为 0 时其余都是 None。"""

    model_config = ConfigDict(extra="forbid")

    hits: int = 0
    meanAppeal: float | None = None
    meanFit: float | None = None
    #: 这组里 LLM 认可的比例
    approvedRate: float | None = None
    #: 这组里模型明确不看的比例
    lowRate: float | None = None


class SubPatternStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str
    stat: HitStat


class SignalStat(BaseModel):
    """一条信号的体检结果。``delta*`` = 命中均分 − 未命中均分。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float
    hits: HitStat
    titleHits: int
    others: HitStat
    deltaAppeal: float | None = None
    deltaFit: float | None = None
    subPatterns: list[SubPatternStat] = Field(default_factory=list)


class RecallPoint(BaseModel):
    """view 前 ``top`` 名里 LLM 认可 / 明确不看各有几条。"""

    model_config = ConfigDict(extra="forbid")

    top: int
    approved: int
    low: int


class BucketStat(BaseModel):
    """关键词分每 10 分一档，档内 LLM 均分。分诊单调不单调一眼看得出。"""

    model_config = ConfigDict(extra="forbid")

    floor: int
    n: int
    meanAppeal: float
    meanFit: float


class ProbeSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: int
    appeal: int
    fit: int
    text: str


class ProbeStat(BaseModel):
    """候选正则的试探结果：标题命中与正文命中分开看，因为权重会被 title_multiplier 放大。"""

    model_config = ConfigDict(extra="forbid")

    pattern: str
    title: HitStat
    body: HitStat
    snippets: list[ProbeSnippet] = Field(default_factory=list)


class AlignReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: AlignThresholds
    #: view（去重 + 薪资门槛）里有几条
    viewSize: int
    #: 其中同时有 LLM 分的几条——下面所有统计都只算这些
    scored: int
    approvedInView: int
    #: llm_scores 里出现过的口径（provider / model / 提示词指纹）。多于一种就不可比
    verdictLabels: list[str] = Field(default_factory=list)
    spearmanAppeal: float | None = None
    spearmanFit: float | None = None
    recall: list[RecallPoint] = Field(default_factory=list)
    buckets: list[BucketStat] = Field(default_factory=list)
    signals: list[SignalStat] = Field(default_factory=list)
    missed: list[AlignJob] = Field(default_factory=list)
    falsePositives: list[AlignJob] = Field(default_factory=list)
    probes: list[ProbeStat] = Field(default_factory=list)

    @property
    def mixed_verdicts(self) -> bool:
        return len(self.verdictLabels) > 1


# ---------------------------------------------------------------- 纯函数


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman 秩相关，同分取平均秩。样本不足或一侧全相同时返回 None。"""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def split_alternatives(pattern: str) -> list[str]:
    """按**顶层** ``|`` 拆正则：括号与字符类里的不拆，转义的 ``\\|`` 不拆。

    信号表里一条信号常是十几个词用 ``|`` 拼的；「这条信号乱命中」的下一问
    永远是「是哪个词」，所以要能拆开分别统计。只处理这一种写法——
    信号表的注释已经要求「坚持一条一行、顶层用 |」。
    """
    parts: list[str] = []
    depth = 0
    in_class = False
    current: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            current.append(pattern[i : i + 2])
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return [p for p in parts if p]


def hit_stat(jobs: Iterable[AlignJob], thresholds: AlignThresholds) -> HitStat:
    rows = list(jobs)
    if not rows:
        return HitStat()
    n = len(rows)
    return HitStat(
        hits=n,
        meanAppeal=round(statistics.fmean(j.appeal for j in rows), 2),
        meanFit=round(statistics.fmean(j.fit for j in rows), 2),
        approvedRate=round(sum(thresholds.approved(j.appeal, j.fit) for j in rows) / n, 3),
        lowRate=round(sum(thresholds.low(j.appeal) for j in rows) / n, 3),
    )


# ---------------------------------------------------------------- 主流程


def align(
    db: Database,
    settings: Settings,
    thresholds: AlignThresholds | None = None,
    floor_wan: float | None = None,
    probes: Sequence[str] = (),
    split: bool = False,
    snippets: bool = False,
) -> AlignReport:
    """按当前 ``[score]`` 现算一遍关键词分，与库里的 LLM 分对齐后出报告。**不写库。**

    统计范围是「去重、过薪资门槛、且有 LLM 分」的行：关键词打分本来就只给这批排序，
    LLM 没判过的行没法比。``probes`` 是候选正则，``split`` 决定要不要拆子模式，
    ``snippets`` 决定探针要不要带命中快照。
    """
    t = thresholds or AlignThresholds()
    llm = {row.jobId: row for row in LlmScoreRepository(db).all()}
    refresh = score_all(db, settings)
    view = refresh.view(settings, floor_wan=floor_wan)

    scored_jobs = [job for job in view if job.job_id in llm]
    facts = {job.job_id: job.row for job in scored_jobs}
    rows = [
        _align_job(job, llm[job.job_id], rank) for rank, job in enumerate(scored_jobs, 1)
    ]
    by_id = {r.jobId: r for r in rows}

    report = AlignReport(
        thresholds=t,
        viewSize=len(view),
        scored=len(rows),
        approvedInView=sum(t.approved(r.appeal, r.fit) for r in rows),
        verdictLabels=sorted(
            {f"{v.provider} / {v.model} / {v.promptFingerprint}" for v in llm.values()}
        ),
    )
    if not rows:
        return report

    keyword = [r.keywordScore for r in rows]
    report.spearmanAppeal = _round(spearman(keyword, [r.appeal for r in rows]))
    report.spearmanFit = _round(spearman(keyword, [r.fit for r in rows]))
    report.recall = [
        RecallPoint(
            top=top,
            approved=sum(t.approved(r.appeal, r.fit) for r in rows[:top]),
            low=sum(t.low(r.appeal) for r in rows[:top]),
        )
        for top in sorted({t.top // 2, t.top, t.top * 3 // 2, t.top * 2})
        if top > 0
    ]
    report.buckets = _buckets(rows)
    report.signals = _signal_stats(settings, scored_jobs, by_id, facts, t, split)
    report.missed = [r for r in rows if t.approved(r.appeal, r.fit) and r.viewRank > t.top]
    report.falsePositives = [r for r in rows if r.viewRank <= t.top and t.low(r.appeal)]
    report.probes = [_probe(p, facts, by_id, t, snippets) for p in probes]
    return report


def _align_job(job: ScoredJob, verdict: LlmScoreRow, rank: int) -> AlignJob:
    return AlignJob(
        jobId=job.job_id,
        title=job.title,
        company=job.company,
        salaryHighWan=job.salary_high,
        keywordScore=round(job.score, 1),
        viewRank=rank,
        appeal=verdict.appealScore,
        fit=verdict.fitScore,
        hits=[h.name for h in job.hits],
        penalties=[h.name for h in job.penalties],
        appealReasons=list(verdict.appealReasons),
        fitReasons=list(verdict.fitReasons),
    )


def _buckets(rows: Sequence[AlignJob]) -> list[BucketStat]:
    groups: dict[int, list[AlignJob]] = {}
    for r in rows:
        groups.setdefault(int(r.keywordScore // 10) * 10, []).append(r)
    return [
        BucketStat(
            floor=floor,
            n=len(group),
            meanAppeal=round(statistics.fmean(j.appeal for j in group), 2),
            meanFit=round(statistics.fmean(j.fit for j in group), 2),
        )
        for floor, group in sorted(groups.items())
    ]


def _signal_stats(
    settings: Settings,
    scored_jobs: Sequence[ScoredJob],
    by_id: dict[int, AlignJob],
    facts: dict[int, JobFacts],
    t: AlignThresholds,
    split: bool,
) -> list[SignalStat]:
    out: list[SignalStat] = []
    for signal in settings.score.signals:
        hit_ids: set[int] = set()
        title_hits = 0
        for job in scored_jobs:
            for hit in (*job.hits, *job.penalties):
                if hit.name == signal.name:
                    hit_ids.add(job.job_id)
                    title_hits += hit.in_title
        hits = hit_stat((by_id[i] for i in hit_ids), t)
        others = hit_stat((r for i, r in by_id.items() if i not in hit_ids), t)
        stat = SignalStat(
            name=signal.name,
            weight=signal.weight,
            hits=hits,
            titleHits=title_hits,
            others=others,
            deltaAppeal=_delta(hits.meanAppeal, others.meanAppeal),
            deltaFit=_delta(hits.meanFit, others.meanFit),
        )
        if split:
            alternatives = split_alternatives(signal.pattern)
            if len(alternatives) > 1:
                stat.subPatterns = [
                    SubPatternStat(pattern=alt, stat=_search_stat(alt, facts, by_id, t))
                    for alt in alternatives
                ]
                stat.subPatterns.sort(key=lambda s: -s.stat.hits)
        out.append(stat)
    out.sort(key=lambda s: -s.hits.hits)
    return out


def _search_stat(
    pattern: str, facts: dict[int, JobFacts], by_id: dict[int, AlignJob], t: AlignThresholds
) -> HitStat:
    regex = re.compile(pattern, re.IGNORECASE)
    matched = (
        by_id[i] for i, f in facts.items() if regex.search(f"{f.jobName}\n{body_text(f)}")
    )
    return hit_stat(matched, t)


def _probe(
    pattern: str,
    facts: dict[int, JobFacts],
    by_id: dict[int, AlignJob],
    t: AlignThresholds,
    with_snippets: bool,
) -> ProbeStat:
    regex = re.compile(pattern, re.IGNORECASE)
    in_title: list[AlignJob] = []
    in_body: list[AlignJob] = []
    snippets: list[ProbeSnippet] = []
    for job_id, fact in facts.items():
        row = by_id[job_id]
        if regex.search(fact.jobName):
            in_title.append(row)
            continue
        body = body_text(fact)
        match = regex.search(body)
        if match is None:
            continue
        in_body.append(row)
        if with_snippets and len(snippets) < SNIPPET_LIMIT:
            start = max(0, match.start() - SNIPPET_MARGIN)
            end = min(len(body), match.end() + SNIPPET_MARGIN)
            text = body[start:end].replace("\n", " ")
            snippets.append(ProbeSnippet(jobId=job_id, appeal=row.appeal, fit=row.fit, text=text))
    return ProbeStat(
        pattern=pattern,
        title=hit_stat(in_title, t),
        body=hit_stat(in_body, t),
        snippets=snippets,
    )


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(a - b, 2)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
