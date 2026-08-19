"""投递职位，并把结果记进本地投递表。

猎聘没有查询投递记录的接口，所以本地记录是唯一可靠的账本。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.core.liepin import LiepinClient, LiepinError, LiepinRateLimited
from job_agent.core.liepin.constants import JOB_KINDS
from job_agent.core.services.progress import Progress, ProgressHook
from job_agent.core.storage import ApplicationRepository, JobRepository
from job_agent.log import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class ApplyOutcome:
    jobId: int
    status: str  # ok / already_applied / closed / failed / error / skipped
    message: str
    label: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(slots=True)
class ApplySummary:
    outcomes: list[ApplyOutcome] = field(default_factory=list)
    remaining: list[int] = field(default_factory=list)
    aborted_reason: str | None = None

    @property
    def aborted(self) -> bool:
        return self.aborted_reason is not None

    @property
    def succeeded(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)


class ApplyService:
    def __init__(
        self,
        client: LiepinClient,
        jobs: JobRepository,
        applications: ApplicationRepository,
        on_progress: ProgressHook | None = None,
    ) -> None:
        self.client = client
        self.jobs = jobs
        self.applications = applications
        self.progress = Progress(on_progress, "services.apply")

    def run(self, job_ids: list[int], job_kind: str | None = None) -> ApplySummary:
        """逐个投递。

        ``jobKind`` 优先用显式传入的，否则读库里的 ``jobType``。
        触发限流立即中止剩余投递：配额按天计、跨零点重置，重试只会延长封禁。
        """
        summary = ApplySummary()
        if job_kind is not None and job_kind not in JOB_KINDS:
            raise ValueError(f"job_kind 必须是 '1'（猎头）或 '2'（普通），传入了 {job_kind!r}")

        for index, job_id in enumerate(job_ids, 1):
            job = self.jobs.get(job_id)
            kind = job_kind or (job["jobType"] if job else None)
            label = f"{job['jobName']} @ {job['company']}" if job else "（不在数据库中）"

            if not kind:
                outcome = ApplyOutcome(
                    jobId=job_id,
                    status="skipped",
                    message=(
                        "数据库里没有该职位，请先搜索入库，"
                        "或显式指定 job_kind（1 猎头 / 2 普通）"
                    ),
                    label=label,
                )
                summary.outcomes.append(outcome)
                self.progress.emit(f"[{job_id}] 跳过：{outcome.message}", index, len(job_ids),
                                   level="warn")
                continue

            try:
                result = self.client.apply_job(job_id, str(kind))
            except LiepinRateLimited as exc:
                summary.remaining = job_ids[index - 1 :]
                summary.aborted_reason = f"触发投递限流：{exc}"
                self.progress.emit(
                    f"[{job_id}] 触发限流，中止剩余 {len(summary.remaining)} 个投递"
                    "（等零点配额重置后再试）",
                    index - 1,
                    len(job_ids),
                    level="error",
                )
                return summary
            except LiepinError as exc:
                outcome = ApplyOutcome(jobId=job_id, status="error", message=str(exc), label=label)
                summary.outcomes.append(outcome)
                self.applications.record(job_id, "error", str(exc))
                self.progress.emit(f"[{job_id}] 失败：{exc}", index, len(job_ids), level="warn")
                continue

            outcome = ApplyOutcome(
                jobId=job_id, status=result.status, message=result.message, label=label
            )
            summary.outcomes.append(outcome)
            self.applications.record(job_id, result.status, result.message)
            self.progress.emit(
                f"[{job_id}] {result.message}  {label}", index, len(job_ids),
                level="info" if result.ok or result.already_applied else "warn",
            )

        return summary
