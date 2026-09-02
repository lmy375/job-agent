"""投递记录。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from job_agent.web.deps import ContextDep
from job_agent.web.schemas import ApplicationEntry, ApplicationsResponse

router = APIRouter(prefix="/applications", tags=["apply"])


@router.get("", response_model=ApplicationsResponse, summary="投递记录（按时间倒序）")
def list_applications(
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> ApplicationsResponse:
    records = context.applications.recent(limit=limit)
    jobs = {job_id: context.jobs.get(job_id) for job_id in {r.jobId for r in records}}
    entries = []
    for record in records:
        job = jobs.get(record.jobId)
        entries.append(
            ApplicationEntry(
                **record.model_dump(),
                jobName=job.jobName if job else "",
                company=job.company if job else "",
                salary=job.salary if job else "",
            )
        )
    return ApplicationsResponse(
        total=len(entries),
        statusCounts=context.applications.status_counts(),
        applications=entries,
    )
