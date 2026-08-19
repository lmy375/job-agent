"""抓取职位详情页并把解析后的 JD 落库。

限流策略：**串行**请求 + 请求间随机休眠，遇 403/429 长退避。
单请求本身耗时 2~4s，天然限速到 ~15 次/分钟。累计 2000+ 条实测全程无限流。
进度直接落库，中断后重跑会自动跳过已完成项。
"""

from __future__ import annotations

import random
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from job_agent.config import Settings
from job_agent.core.jd_parser import EMPTY_DETAIL, parse_detail
from job_agent.core.services.progress import Progress, ProgressHook
from job_agent.core.storage import DetailRepository, JobRepository
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 视为「被限流」的 HTTP 状态码
BLOCKED_STATUSES = (403, 429)
#: 每 N 条上报一次进度
PROGRESS_EVERY = 10
#: 单条平均耗时（秒），仅用于估算总时长
SECONDS_PER_JOB = 4


@dataclass(slots=True)
class DetailSummary:
    total: int = 0
    fetched: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    elapsed: float = 0.0
    #: 非空表示提前结束（目前只有「已取消」一种）
    aborted_reason: str | None = None

    @property
    def ok(self) -> int:
        return self.statuses.get("ok", 0)


class DetailService:
    """串行抓取详情页。``sleeper`` 可注入，测试里不必真的等。"""

    def __init__(
        self,
        settings: Settings,
        jobs: JobRepository,
        details: DetailRepository,
        session: requests.Session | None = None,
        on_progress: ProgressHook | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self.details = details
        self.progress = Progress(on_progress, "services.detail")
        self.sleeper = sleeper
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._session.headers.update(
            {"User-Agent": settings.detail.user_agent, "Accept-Language": "zh-CN,zh;q=0.9"}
        )

    def run(
        self,
        limit: int | None = None,
        retry_failed: bool = False,
        stop_check: Callable[[], bool] | None = None,
    ) -> DetailSummary:
        """串行抓取。``stop_check`` 返回 True 时在条目边界停下（进度已落库，可续跑）。"""
        targets = self.jobs.missing_details(retry_failed=retry_failed, limit=limit)
        summary = DetailSummary(total=len(targets))
        if not targets:
            self.progress.emit("没有需要抓取的职位详情。")
            return summary

        eta = summary.total * SECONDS_PER_JOB / 60
        self.progress.emit(
            f"待抓取 {summary.total} 条职位详情（串行，预计 {eta:.0f} 分钟）", 0, summary.total
        )

        started = time.monotonic()
        for index, (job_id, url) in enumerate(targets, 1):
            if stop_check is not None and stop_check():
                summary.aborted_reason = "已取消"
                self.progress.emit(
                    f"已取消：完成 {summary.fetched}/{summary.total} 条，进度已落库，重跑会续上",
                    summary.fetched,
                    summary.total,
                    level="warn",
                )
                break
            detail = self.fetch_one(url)
            self.details.upsert({"jobId": job_id, **detail})
            summary.fetched += 1
            summary.statuses[detail["status"]] += 1

            if index % PROGRESS_EVERY == 0 or index == summary.total:
                elapsed = time.monotonic() - started
                remaining = elapsed / index * (summary.total - index)
                self.progress.emit(
                    f"[{index}/{summary.total}] {dict(sorted(summary.statuses.items()))} "
                    f"已用 {elapsed / 60:.1f}min，剩余约 {remaining / 60:.1f}min",
                    index,
                    summary.total,
                )
            if index < summary.total:
                self.sleeper(
                    random.uniform(self.settings.detail.sleep_min, self.settings.detail.sleep_max)
                )

        summary.elapsed = time.monotonic() - started
        if summary.aborted_reason is None:
            self.progress.emit(
                f"抓取完成：{dict(sorted(summary.statuses.items()))}", summary.total, summary.total
            )
        return summary

    def fetch_one(self, url: str) -> dict[str, str]:
        """抓一个详情页并解析，返回带 ``status`` 的字段字典（不落库）。

        403/429 视为被限流：长退避后重试，重试用尽才记为 ``blocked``。
        """
        config = self.settings.detail
        for attempt in range(1, config.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=config.timeout)
            except requests.RequestException as exc:
                if attempt == config.max_retries:
                    return {**EMPTY_DETAIL, "status": f"error:{type(exc).__name__}"}
                self.sleeper(5 * attempt)
                continue

            if resp.status_code in BLOCKED_STATUSES:
                self.progress.emit(
                    f"HTTP {resp.status_code}，疑似限流，退避 {config.block_backoff:.0f}s",
                    level="warn",
                )
                self.sleeper(config.block_backoff)
                continue
            if not resp.ok:
                return {**EMPTY_DETAIL, "status": f"http_{resp.status_code}"}

            parsed = parse_detail(resp.text)
            if parsed is None:
                # 页面没有 JobPosting，多为职位已下线
                return {**EMPTY_DETAIL, "status": "no_jd"}
            return {**parsed, "status": "ok"}

        return {**EMPTY_DETAIL, "status": "blocked"}

    def close(self) -> None:
        if self._owns_session:
            self._session.close()
