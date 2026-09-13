"""API 路由。"""

from __future__ import annotations

from fastapi import APIRouter

from job_agent.web.routers import (
    applications,
    config,
    health,
    jobs,
    keywords,
    profiles,
    scores,
    stats,
    tasks,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(jobs.router)
api_router.include_router(keywords.router)
api_router.include_router(scores.router)
api_router.include_router(stats.router)
api_router.include_router(tasks.router)
api_router.include_router(applications.router)
api_router.include_router(config.router)
api_router.include_router(profiles.router)

__all__ = ["api_router"]
