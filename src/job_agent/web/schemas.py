"""Web API 的请求 / 响应模型。带上它们，``/docs`` 才是能照着调的文档。

响应一律是模型而不是现拼的 dict：字段拼错会在这里就炸，而不是等前端渲染出空白。
能直接复用内核的行模型（``JobRow`` / ``ApplicationRow`` / ``KeywordCount`` …）就复用，
Web 端只在需要额外字段时继承它们——两处各写一份字段表，迟早会对不上。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from job_agent.config import ConfigPaths, Settings
from job_agent.core.storage import (
    ApplicationRow,
    JobRow,
    KeywordCount,
    SalarySummary,
    ScoreStatus,
)
from job_agent.core.storage.repositories import MAX_ROWS


class JobListResponse(BaseModel):
    """职位列表。**不分页**——本地单人用、职位数有限，一次全给前端。

    ``limit`` 只是「别让一次响应大到离谱」的兜底。真被截断时
    ``total > len(jobs)``，前端必须把这件事显示出来，不能装作全给了。
    """

    total: int = Field(description="满足筛选条件的总条数")
    limit: int = Field(description="本次上限（兜底，不是页大小）")
    jobs: list[JobRow]

    @property
    def truncated(self) -> bool:
        return self.total > len(self.jobs)


class KeywordsResponse(BaseModel):
    """各搜索关键词的职位数。纯库存计数，不带任何赛道 / 分类判断。"""

    keywords: list[KeywordCount]


class ApplyRequest(BaseModel):
    job_kind: Literal["1", "2"] | None = Field(
        default=None, description="职位类型：1 猎头 / 2 普通。省略时取库里的 jobType。"
    )


class ApplyResponse(BaseModel):
    jobId: int
    status: str = Field(description="ok / already_applied / closed / failed")
    message: str
    label: str = ""


class ApplicationEntry(ApplicationRow):
    """一条投递记录，附上职位信息，前端一行就能展示（职位已删则为空串）。"""

    jobName: str = ""
    company: str = ""
    salary: str = ""


class ApplicationsResponse(BaseModel):
    total: int
    statusCounts: dict[str, int] = Field(description="各投递状态的条数")
    applications: list[ApplicationEntry]


class OverviewResponse(BaseModel):
    """库内数据概览。``details`` / ``applications`` 是「状态 -> 条数」的分布。"""

    jobs: int
    details: dict[str, int]
    applications: dict[str, int]
    salary: SalarySummary
    keywords: list[KeywordCount]
    pendingDetails: int = Field(description="还没抓过详情的职位数")
    score: ScoreStatus = Field(
        description="落库分数的新鲜度：改过 [score] 或采了新数据就该重跑 job score"
    )


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    jobs: int
    tokenConfigured: bool


class ConfigResponse(BaseModel):
    """当前配置（密钥已打码）。

    ``settings`` 就是 :class:`~job_agent.config.Settings` 本身：
    配置树随它演进，在这里再抄一份字段表只会让两边对不上。
    密钥字段是 ``SecretStr``，序列化成 JSON 时自动变 ``**********``——
    往配置树里加密钥不需要再来这里补脱敏逻辑。
    """

    model_config = ConfigDict(extra="forbid")

    settings: Settings
    paths: ConfigPaths


class TaskKind(StrEnum):
    SEARCH = "search"
    DETAIL = "detail"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskParams(BaseModel):
    """采集任务的参数。按 kind 只有其中一部分有意义，其余保持默认。"""

    model_config = ConfigDict(extra="forbid")

    keywords: list[str] | None = Field(default=None, description="仅 search：只搜这些关键词")
    pages: int | None = Field(default=None, ge=1, le=6, description="仅 search：每个关键词翻几页")
    fetch_detail: bool = Field(
        default=True, description="仅 search：搜完接着抓 JD。默认开——没有 JD 的库没法打分"
    )
    limit: int | None = Field(
        default=None, ge=1, le=MAX_ROWS, description="抓 JD 时本次最多抓多少条"
    )
    retry_failed: bool = Field(default=False, description="抓 JD 时连之前失败的一起重试")


class CreateTaskRequest(BaseModel):
    """提交任务：``kind`` 决定跑什么，``params`` 是这次的参数快照。

    参数单独嵌一层，任务对象就能原样收下它，不需要在中间再拆一次字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    params: TaskParams = Field(default_factory=TaskParams)


class TaskResult(BaseModel):
    """任务产出的结构化结果。每个 runner 返回下面对应的子类。"""

    model_config = ConfigDict(extra="forbid")


class SearchKeywordResult(BaseModel):
    """一个关键词的搜索结果。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    keyword: str
    found: int
    new: int
    truncated: bool
    error: str | None = None


class DetailTaskResult(TaskResult):
    total: int
    fetched: int
    statuses: dict[str, int]
    elapsedSeconds: float
    abortedReason: str | None = None


class SearchTaskResult(TaskResult):
    totalFound: int
    totalNew: int
    keywords: list[SearchKeywordResult]
    remaining: list[str] = Field(default_factory=list, description="限流中止时未搜的关键词")
    #: params.fetch_detail 为真时，同一个任务顺带抓的 JD 结果
    detail: DetailTaskResult | None = None


class TaskView(BaseModel):
    """一个后台任务对前端的视图（不含日志）。

    ``from_attributes``：直接 ``TaskView.model_validate(task)``，
    字段名与 :class:`~job_agent.web.tasks.Task` 对齐，``percent`` /
    ``cancelRequested`` 读的是那边的 property，不手工搬运。
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    kind: TaskKind
    status: TaskStatus
    params: TaskParams
    message: str = ""
    current: int | None = None
    total: int | None = None
    percent: float | None = None
    createdAt: datetime
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    cancelRequested: bool = False
    #: SerializeAsAny：结果是各 runner 的 TaskResult 子类，按声明类型序列化会只剩空对象
    result: SerializeAsAny[TaskResult] | None = None
    error: str | None = None


class TaskDetail(TaskView):
    """任务详情：比列表多一份日志。

    列表接口刻意不带日志——50 个历史任务 × 几百行会把响应撑爆。
    """

    logs: list[str] = Field(default_factory=list)


class TaskResponse(BaseModel):
    task: TaskDetail


class TaskListResponse(BaseModel):
    tasks: list[TaskView]
    running: str | None = Field(default=None, description="正在执行或排队中的任务 id")


class ErrorResponse(BaseModel):
    detail: str
    type: str
