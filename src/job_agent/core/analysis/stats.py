"""统计聚合：把行集合汇总成报告 / API 需要的结构化数据。"""

from __future__ import annotations

import statistics
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from job_agent.config import Settings
from job_agent.core.analysis.classify import YEARS_ORDER
from job_agent.core.analysis.dataset import AnalysisRow, load_rows
from job_agent.core.analysis.skills import SKILLS, skill_hits
from job_agent.core.storage import Database
from job_agent.tracks import OTHER, TRACKS, Track

#: 公司 / 行业等长尾维度在报告里展示的条数
TOP_COMPANIES = 15
TOP_INDUSTRIES = 10
TOP_STAGES = 8


class SkillStat(BaseModel):
    """某个技能词在一条赛道里的命中情况。``pct`` 是「提及它的 JD 占比」。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    count: int
    pct: float


class TrackStats(BaseModel):
    """一条赛道的全部统计量。

    长尾维度（角色 / 公司 / 行业 …）保持 ``(名称, 条数)`` 的有序列表：
    顺序本身就是信息（按数量降序，经验档位按固定梯度），换成 mapping 会丢掉它。
    """

    model_config = ConfigDict(extra="forbid")

    count: int
    roles: list[tuple[str, int]] = Field(default_factory=list)
    companies: list[tuple[str, int]] = Field(default_factory=list)
    industries: list[tuple[str, int]] = Field(default_factory=list)
    education: list[tuple[str, int]] = Field(default_factory=list)
    workYears: list[tuple[str, int]] = Field(default_factory=list)
    financing: list[tuple[str, int]] = Field(default_factory=list)
    companySize: list[tuple[str, int]] = Field(default_factory=list)
    salaryMedianLow: float | None = None
    salaryMedianHigh: float | None = None
    #: 用 90 分位而不是最大值：猎聘上偶有「200-400k·30薪」这类异常挂法，
    #: 最大值会被单条噪声拉到 1000 万以上，失去参考意义。
    salaryP90High: float | None = None
    #: 猎聘的薪资过滤是「区间重叠」而非「下限 ≥」，还会漏进明显不达标的条目，
    #: 所以单独统计真正够到 100 万的比例，避免读者误以为全部样本都是百万岗。
    meets100: int = 0
    salaryParsed: int = 0
    #: 技能分类名 -> 该分类下各技能词的命中率，按命中数降序
    skills: dict[str, list[SkillStat]] = Field(default_factory=dict)
    jobs: list[AnalysisRow] = Field(default_factory=list)


class Analysis(BaseModel):
    """一次完整统计的结果。``rows`` 含 JD 全文，只给报告用，不外传。"""

    model_config = ConfigDict(extra="forbid")

    total: int
    trackCounts: Counter[str] = Field(default_factory=Counter)
    tracks: dict[Track, TrackStats] = Field(default_factory=dict)
    rows: list[AnalysisRow] = Field(default_factory=list)


def quantile(values: list[float], q: float) -> float:
    """样本分位数（线性插值）。

    ``statistics.quantiles`` 在样本很小时会抛异常，而这里的赛道样本可能只有个位数，
    所以自己算。
    """
    ordered = sorted(values)
    if not ordered:
        raise ValueError("空样本没有分位数")
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def analyze_rows(rows: list[AnalysisRow]) -> Analysis:
    """产出报告所需的全部统计数据。``rows`` 来自 :func:`load_rows`。"""
    for row in rows:
        row.skills = skill_hits(row.description)

    result = Analysis(
        total=len(rows),
        trackCounts=Counter(row.track for row in rows),
        rows=rows,
    )

    for track in (*TRACKS, OTHER):
        sub = [row for row in rows if row.track == track]
        if not sub:
            continue
        result.tracks[track] = _track_stats(sub)
    return result


def analyze(db: Database, settings: Settings, dedupe: bool = True) -> Analysis:
    """从数据库直接算出统计结果。"""
    return analyze_rows(load_rows(db, settings, dedupe=dedupe))


def _track_stats(sub: list[AnalysisRow]) -> TrackStats:
    highs = [row.salaryHigh for row in sub if row.salaryHigh]
    lows = [row.salaryLow for row in sub if row.salaryLow]
    years = Counter(row.yearsBucket for row in sub)

    skill_pct: dict[str, list[SkillStat]] = {}
    for group in SKILLS:
        counter: Counter[str] = Counter()
        for row in sub:
            counter.update(row.skills.get(group, ()))
        skill_pct[group] = [
            SkillStat(name=name, count=n, pct=n / len(sub) * 100)
            for name, n in counter.most_common()
        ]

    return TrackStats(
        count=len(sub),
        roles=Counter(row.role for row in sub).most_common(),
        companies=Counter(row.company for row in sub).most_common(TOP_COMPANIES),
        industries=Counter(
            row.industry for row in sub if row.industry
        ).most_common(TOP_INDUSTRIES),
        education=Counter(row.education for row in sub).most_common(),
        # 经验分布按档位固定顺序展示（而不是按数量排序），才看得出「梯度」
        workYears=[(bucket, years[bucket]) for bucket in YEARS_ORDER if years[bucket]],
        financing=Counter(
            row.financingStage for row in sub if row.financingStage
        ).most_common(TOP_STAGES),
        companySize=Counter(
            row.companySize for row in sub if row.companySize
        ).most_common(TOP_STAGES),
        salaryMedianLow=round(statistics.median(lows), 1) if lows else None,
        salaryMedianHigh=round(statistics.median(highs), 1) if highs else None,
        salaryP90High=round(quantile(highs, 0.9), 1) if highs else None,
        meets100=sum(1 for high in highs if high >= 100),
        salaryParsed=len(highs),
        skills=skill_pct,
        jobs=sorted(sub, key=lambda row: -(row.salaryHigh or 0)),
    )
