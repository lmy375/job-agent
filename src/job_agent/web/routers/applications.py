"""投递记录。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from job_agent.web.deps import ContextDep

router = APIRouter(prefix="/applications", tags=["apply"])


@router.get("", summary="投递记录（按时间倒序）")
def list_applications(
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> dict[str, Any]:
    records = context.applications.recent(limit=limit)
    jobs = {job_id: context.jobs.get(job_id) for job_id in {r["jobId"] for r in records}}
    for record in records:
        job = jobs.get(record["jobId"])
        record["jobName"] = job["jobName"] if job else ""
        record["company"] = job["company"] if job else ""
        record["salary"] = job["salary"] if job else ""
    return {
        "total": len(records),
        "statusCounts": context.applications.status_counts(),
        "applications": records,
    }
