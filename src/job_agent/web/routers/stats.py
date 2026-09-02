"""库内数据概览。

**只报库存，不做分析**：多少职位、抓了多少 JD、投了多少、薪资什么水位。
赛道 / 角色 / 技能分布这类市场分析不在这个仓库里，见 CLAUDE.md。
"""

from __future__ import annotations

from fastapi import APIRouter

from job_agent.web.deps import ContextDep
from job_agent.web.schemas import OverviewResponse

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=OverviewResponse, summary="库内数据概览")
def overview(context: ContextDep) -> OverviewResponse:
    return OverviewResponse(
        jobs=context.jobs.count(),
        details=context.details.status_counts(),
        applications=context.applications.status_counts(),
        salary=context.jobs.salary_summary(
            floor_wan=context.settings.score.salary_floor_wan
        ),
        keywords=context.jobs.keyword_counts(),
        pendingDetails=len(context.jobs.missing_details()),
    )
