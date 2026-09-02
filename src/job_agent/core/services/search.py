"""按配置的关键词批量搜索职位并落库。"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from job_agent.config import Settings
from job_agent.core.liepin import (
    MAX_PAGE,
    PAGE_SIZE,
    LiepinClient,
    LiepinError,
    LiepinPageLimit,
    LiepinRateLimited,
    SearchJobInput,
)
from job_agent.core.services.progress import Progress, ProgressHook
from job_agent.core.storage import JobRepository
from job_agent.log import get_logger

logger = get_logger(__name__)


class KeywordResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str
    found: int = 0
    new: int = 0
    pages: int = 0
    #: 命中数撞到 ``max_pages × 20`` 的硬顶，说明真实总量被服务端截断了
    truncated: bool = False
    error: str | None = None


class SearchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[KeywordResult] = Field(default_factory=list)
    remaining: list[str] = Field(default_factory=list)
    #: 非空表示整批被中止（目前只有触发限流一种原因）
    aborted_reason: str | None = None

    @property
    def aborted(self) -> bool:
        return self.aborted_reason is not None

    @property
    def total_found(self) -> int:
        return sum(r.found for r in self.results)

    @property
    def total_new(self) -> int:
        return sum(r.new for r in self.results)


class SearchService:
    """把「关键词 × 分页」展开成请求，去重落库。

    关键词按配置顺序（= 优先级）搜，因为按 jobId 去重且先搜高优先级方向，
    每条职位记录到的 ``searchKeyword`` 就是「最先命中它的方向」。
    """

    def __init__(
        self,
        settings: Settings,
        client: LiepinClient,
        jobs: JobRepository,
        on_progress: ProgressHook | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.jobs = jobs
        self.progress = Progress(on_progress, "services.search")

    def run(
        self,
        keywords: list[str] | None = None,
        max_pages: int | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> SearchSummary:
        """执行批量搜索。

        ``stop_check`` 返回 True 时在关键词边界优雅停止（Web 端的「取消」用）。

        触发限流会**中止整批**并在 summary 里写明原因：冷却期长达 20 分钟以上，
        继续往下跑只会让剩余关键词全部静默失败，看起来像「这些方向没有职位」。
        """
        search = self.settings.search
        todo = list(keywords or search.keywords)
        pages = min(max_pages or search.max_pages, MAX_PAGE)
        summary = SearchSummary()

        if not todo:
            self.progress.emit(
                "没有可用的搜索关键词：请在 profile.toml 的 [search].keywords 里配置",
                level="warn",
            )
            return summary

        self.progress.emit(f"开始搜索 {len(todo)} 个关键词，每个最多 {pages} 页", 0, len(todo))

        for index, keyword in enumerate(todo, 1):
            if stop_check is not None and stop_check():
                summary.remaining = todo[index - 1 :]
                summary.aborted_reason = "已取消"
                self.progress.emit(
                    f"已取消：剩余 {len(summary.remaining)} 个关键词未搜索",
                    index - 1,
                    len(todo),
                    level="warn",
                )
                return summary
            result = KeywordResult(keyword=keyword)
            summary.results.append(result)
            try:
                self._search_keyword(keyword, pages, result)
            except LiepinRateLimited as exc:
                summary.remaining = todo[index - 1 :]
                summary.aborted_reason = f"触发限流：{exc}"
                self.progress.emit(
                    f"[{keyword}] 触发限流，中止整批。已完成 {index - 1}/{len(todo)} 个关键词，"
                    f"未完成：{'、'.join(summary.remaining)}",
                    index - 1,
                    len(todo),
                    level="error",
                )
                return summary

            note = "（已达服务端上限，实际更多）" if result.truncated else ""
            if result.error:
                self.progress.emit(
                    f"[{keyword}] 失败：{result.error}", index, len(todo), level="warn"
                )
            else:
                self.progress.emit(
                    f"[{keyword}] 命中 {result.found} 条，新增 {result.new} 条{note}",
                    index,
                    len(todo),
                )

        self.progress.emit(
            f"搜索完成：命中 {summary.total_found} 条，新增 {summary.total_new} 条",
            len(todo),
            len(todo),
        )
        return summary

    def _search_keyword(self, keyword: str, pages: int, result: KeywordResult) -> None:
        search = self.settings.search
        for page in range(pages):
            query = SearchJobInput(
                jobName=keyword,
                address=search.address,
                salaryKind=search.salary_kind,
                salaryFloor=str(search.salary_floor) if search.salary_floor else None,
                salaryCap=str(search.salary_cap) if search.salary_cap else None,
                eduLevel=search.edu_level,
                workExperience=search.work_experience,
                page=page,
            )
            try:
                jobs = self.client.search_jobs(query).data.jobs
            except LiepinPageLimit:
                break  # 翻到分页上限，正常结束
            except LiepinRateLimited:
                raise
            except LiepinError as exc:
                result.error = str(exc)
                break

            result.pages = page + 1
            if not jobs:
                break
            result.found += len(jobs)
            result.new += self.jobs.upsert_many(jobs, keyword=keyword)

        result.truncated = result.found >= pages * PAGE_SIZE
