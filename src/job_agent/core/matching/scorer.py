"""按信号表给职位打分排序。

**打分只做分诊**：把几百条砍到几十条，交给人或 skill 去读 JD 下判断。
它不回答「该不该投」——「这个岗要 50 人管理经验而你带 5 人」这种判断
需要读懂文字，是 skill 的事（见 ``.claude/skills/job-match``）。

因此这里刻意保留了每条命中/扣分的**理由**：排名本身不可信，
理由才是让人能快速复核「为什么它排第一」的东西。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from job_agent.config import Settings
from job_agent.core.analysis import AnalysisRow, load_rows
from job_agent.core.matching.rules import MatchRules
from job_agent.core.storage import Database
from job_agent.log import get_logger

logger = get_logger(__name__)


class Hit(BaseModel):
    """一条命中的信号。``in_title`` 决定权重是否被 ``title_multiplier`` 放大。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float
    in_title: bool

    def label(self) -> str:
        return f"{self.name}（标题）" if self.in_title else self.name


class ScoredJob(BaseModel):
    """一条打完分的职位。``row`` 是 :func:`load_rows` 的原始行，字段见 :class:`AnalysisRow`。"""

    model_config = ConfigDict(extra="forbid")

    row: AnalysisRow
    score: float
    hits: list[Hit] = Field(default_factory=list)
    penalties: list[Hit] = Field(default_factory=list)
    #: 职位名与 JD 都没命中 require.pattern
    off_track: bool = False

    # 常用字段的直通访问，省得调用方到处写 job.row["..."]
    @property
    def job_id(self) -> int:
        return self.row.jobId

    @property
    def title(self) -> str:
        return self.row.jobName

    @property
    def company(self) -> str:
        return self.row.company

    @property
    def salary_low(self) -> float | None:
        return self.row.salaryLow

    @property
    def salary_high(self) -> float | None:
        return self.row.salaryHigh

    def reasons(self) -> str:
        return "、".join(h.label() for h in self.hits)

    def concerns(self) -> str:
        return "、".join(h.label() for h in self.penalties)


def score_row(row: AnalysisRow, rules: MatchRules) -> ScoredJob:
    """给一行打分。同一条信号在标题和正文都命中时只算标题（取高的那份）。"""
    title = row.jobName
    body = " ".join((row.description, row.responsibilities, row.requirements))
    haystack = f"{title}\n{body}"

    scored = ScoredJob(row=row, score=0.0)
    for signal in rules.signals:
        regex = signal.regex
        in_title = bool(regex.search(title))
        if not in_title and not regex.search(haystack):
            continue
        weight = signal.weight * (rules.options.title_multiplier if in_title else 1.0)
        scored.score += weight
        hit = Hit(name=signal.name, weight=weight, in_title=in_title)
        (scored.hits if signal.weight > 0 else scored.penalties).append(hit)

    require = rules.require_regex
    if require is not None and not require.search(haystack):
        scored.off_track = True
        scored.score += rules.require.penalty
        scored.penalties.append(
            Hit(name="不含目标赛道关键词", weight=rules.require.penalty, in_title=False)
        )

    scored.hits.sort(key=lambda h: -h.weight)
    scored.penalties.sort(key=lambda h: h.weight)
    return scored


def rank(
    db: Database,
    settings: Settings,
    rules: MatchRules,
    floor_wan: float | None = None,
    dedupe: bool = True,
) -> list[ScoredJob]:
    """读库、打分、排序。

    ``floor_wan`` 过滤的是**薪资上限**而不是下限：JD 标的区间上限才代表
    「这家最多能给到多少」，按下限过滤会把「50-80k·20薪」这种谈得上去的岗位误杀。
    """
    rows = load_rows(db, settings, dedupe=dedupe)
    threshold = floor_wan if floor_wan is not None else settings.match.salary_floor_wan

    out: list[ScoredJob] = []
    skipped = 0
    for row in rows:
        high = row.salaryHigh
        if threshold is not None and (high is None or high < threshold):
            skipped += 1
            continue
        out.append(score_row(row, rules))

    out.sort(key=lambda s: (-s.score, -(s.salary_high or 0.0)))
    logger.debug("打分 %d 条，按薪资上限门槛滤掉 %d 条", len(out), skipped)
    return out
