"""健康检查。部署在别处时用它探活。"""

from __future__ import annotations

from fastapi import APIRouter

from job_agent import __version__
from job_agent.web.deps import ContextDep
from job_agent.web.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health(context: ContextDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        database=str(context.settings.storage.database),
        jobs=context.jobs.count(),
        tokenConfigured=bool(context.settings.account.user_token),
    )
