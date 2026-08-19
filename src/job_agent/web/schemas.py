"""Web API 的请求 / 响应模型。带上它们，``/docs`` 才是能照着调的文档。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from job_agent.core.storage.repositories import MAX_PAGE_SIZE
from job_agent.web.tasks import TaskKind


class JobListResponse(BaseModel):
    total: int = Field(description="满足筛选条件的总条数（不受分页影响）")
    limit: int
    offset: int
    jobs: list[dict[str, Any]]


class KeywordsResponse(BaseModel):
    keywords: list[dict[str, Any]]


class ApplyRequest(BaseModel):
    job_kind: Literal["1", "2"] | None = Field(
        default=None, description="职位类型：1 猎头 / 2 普通。省略时取库里的 jobType。"
    )


class ApplyResponse(BaseModel):
    jobId: int
    status: str = Field(description="ok / already_applied / closed / failed")
    message: str
    label: str = ""


class CreateTaskRequest(BaseModel):
    kind: TaskKind
    # search
    keywords: list[str] | None = Field(default=None, description="仅 search：只搜这些关键词")
    pages: int | None = Field(default=None, ge=1, le=6, description="仅 search：每个关键词翻几页")
    # detail
    limit: int | None = Field(
        default=None, ge=1, le=MAX_PAGE_SIZE, description="仅 detail：本次最多抓多少条"
    )
    retry_failed: bool = Field(default=False, description="仅 detail：重试此前失败的")
    # report
    dedupe: bool = Field(default=True, description="仅 report：是否按 JD 正文去重")


class TaskResponse(BaseModel):
    task: dict[str, Any]


class TaskListResponse(BaseModel):
    tasks: list[dict[str, Any]]
    running: str | None = Field(default=None, description="正在执行或排队中的任务 id")


class ErrorResponse(BaseModel):
    detail: str
    type: str
