"""职位查询与投递。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query

from job_agent.core.services import ApplyService
from job_agent.core.storage import JobQuery
from job_agent.core.storage.repositories import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from job_agent.web.deps import ContextDep
from job_agent.web.schemas import ApplyRequest, ApplyResponse, JobListResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse, summary="职位列表（分页）")
def list_jobs(
    context: ContextDep,
    keyword: Annotated[str | None, Query(description="按 searchKeyword 精确筛选")] = None,
    q: Annotated[str | None, Query(description="在职位名 / 公司名里模糊搜索")] = None,
    has_detail: Annotated[bool | None, Query(description="是否已抓到 JD")] = None,
    applied: Annotated[bool | None, Query(description="是否已投递")] = None,
    min_salary: Annotated[
        float | None, Query(ge=0, description="年薪上限不低于该值（万元）")
    ] = None,
    order: Annotated[
        Literal["recent", "salary", "salary_asc"], Query(description="排序方式")
    ] = "recent",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    page = context.jobs.find(
        JobQuery(
            keyword=keyword,
            q=q,
            has_detail=has_detail,
            applied=applied,
            min_salary=min_salary,
            order=order,
            limit=limit,
            offset=offset,
        )
    )
    return JobListResponse(total=page.total, limit=limit, offset=offset, jobs=page.items)


@router.get("/{job_id}", summary="单条职位（含 JD 与投递记录）")
def get_job(
    context: ContextDep, job_id: Annotated[int, Path(description="职位 ID")]
) -> dict[str, Any]:
    job = context.jobs.get_with_detail(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"职位 {job_id} 不在数据库中")
    return job


@router.post("/{job_id}/apply", response_model=ApplyResponse, summary="投递该职位")
def apply_job(
    context: ContextDep,
    job_id: Annotated[int, Path(description="职位 ID")],
    payload: ApplyRequest | None = None,
) -> ApplyResponse:
    """投递是不可撤销的动作，前端必须先向用户确认再调这个接口。

    投递结果（包括「已投递过」「职位已结束」）都会记进本地投递表——
    猎聘没有查询投递记录的接口，这张表是唯一的账本。
    """
    body = payload or ApplyRequest()
    # 先确认能定出 jobKind 再建客户端：库里没有的职位应当直接 400，
    # 而不是先去要 token、最后报一个跟原因无关的错
    if body.job_kind is None and context.jobs.get(job_id) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"职位 {job_id} 不在数据库中，请先搜索入库，"
                "或显式指定 job_kind（1 猎头 / 2 普通）"
            ),
        )
    with context.client() as client:
        service = ApplyService(client, context.jobs, context.applications)
        summary = service.run([job_id], body.job_kind)

    if summary.aborted:
        raise HTTPException(status_code=429, detail=summary.aborted_reason or "触发限流")
    outcome = summary.outcomes[0]
    if outcome.status == "skipped":
        raise HTTPException(status_code=400, detail=outcome.message)
    return ApplyResponse(
        jobId=outcome.jobId, status=outcome.status, message=outcome.message, label=outcome.label
    )
