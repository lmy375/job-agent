"""数据概览与赛道分析。

赛道分析要把两千多份 JD 全部跑一遍正则，秒级耗时，不能每次请求都算，
所以按「职位数 + 详情数」做缓存键——数据没变就直接复用。
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Request

from job_agent.context import AppContext
from job_agent.core.analysis import Analysis, SkillStat, analyze
from job_agent.web.deps import ContextDep
from job_agent.web.schemas import OverviewResponse, TrackStatsResponse, TrackSummary

router = APIRouter(prefix="/stats", tags=["stats"])

#: 每条赛道在响应里保留的条目数（前端只展示前几条，全量在 HTML 报告里）
TOP_ROLES = 10
TOP_COMPANIES = 8
TOP_SKILLS = 10


class TrackStatsCache:
    """赛道统计的进程内缓存。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple[int, int] | None = None
        self._data: TrackStatsResponse | None = None

    def get(self, context: AppContext) -> TrackStatsResponse:
        key = (context.jobs.count(), context.details.status_counts().get("ok", 0))
        with self._lock:
            if self._key == key and self._data is not None:
                return self._data
        data = _summarize(analyze(context.db, context.settings))
        with self._lock:
            self._key, self._data = key, data
        return data


def _summarize(data: Analysis) -> TrackStatsResponse:
    """只保留可以塞进 JSON 的汇总部分（原始行含 JD 全文，不外传）。"""
    tracks = [
        TrackSummary(
            track=track,
            count=info.count,
            roles=info.roles[:TOP_ROLES],
            salaryMedianLow=info.salaryMedianLow,
            salaryMedianHigh=info.salaryMedianHigh,
            salaryP90High=info.salaryP90High,
            meets100=info.meets100,
            salaryParsed=info.salaryParsed,
            topCompanies=info.companies[:TOP_COMPANIES],
            workYears=info.workYears,
            topSkills={
                group: [
                    SkillStat(name=item.name, count=item.count, pct=round(item.pct, 1))
                    for item in items[:TOP_SKILLS]
                ]
                for group, items in info.skills.items()
            },
        )
        for track, info in data.tracks.items()
    ]
    tracks.sort(key=lambda item: -item.count)
    return TrackStatsResponse(total=data.total, tracks=tracks)


@router.get("", response_model=OverviewResponse, summary="库内数据概览")
def overview(context: ContextDep) -> OverviewResponse:
    return OverviewResponse(
        jobs=context.jobs.count(),
        details=context.details.status_counts(),
        applications=context.applications.status_counts(),
        salary=context.jobs.salary_summary(),
        keywords=context.jobs.keyword_counts(),
        pendingDetails=len(context.jobs.missing_details()),
    )


@router.get(
    "/tracks",
    response_model=TrackStatsResponse,
    summary="赛道 / 角色 / 技能分布（结果有缓存）",
)
def track_stats(request: Request, context: ContextDep) -> TrackStatsResponse:
    cache: TrackStatsCache = request.app.state.track_cache
    return cache.get(context)
