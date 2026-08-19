"""仓储层：SQL 只写在这里，上层拿到的是 dict / 模型对象。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from job_agent.core.liepin.models import Job
from job_agent.core.salary import parse_salary
from job_agent.core.storage.database import Database
from job_agent.core.storage.models import ApplicationRecord, JobDetailRecord, JobRecord
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 视为「已投递成功」的状态：already_applied 也算投过（服务端说已投过就是投过）
APPLIED_STATUSES = ("ok", "already_applied")

OrderBy = Literal["recent", "salary", "salary_asc"]

DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 2000


@dataclass(slots=True)
class JobQuery:
    """职位列表的查询条件。默认分页，避免一次把整库塞进响应。"""

    keyword: str | None = None
    q: str | None = None
    has_detail: bool | None = None
    applied: bool | None = None
    min_salary: float | None = None  # 年薪下限（万元），比较的是 salaryHighWan
    order: OrderBy = "recent"
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def normalized(self) -> JobQuery:
        limit = max(1, min(self.limit, MAX_PAGE_SIZE))
        return JobQuery(
            keyword=(self.keyword or "").strip() or None,
            q=(self.q or "").strip() or None,
            has_detail=self.has_detail,
            applied=self.applied,
            min_salary=self.min_salary,
            order=self.order,
            limit=limit,
            offset=max(0, self.offset),
        )


@dataclass(slots=True)
class JobPage:
    total: int
    items: list[dict[str, Any]] = field(default_factory=list)


class JobRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------------- 写入

    def upsert_many(self, jobs: Sequence[Job], keyword: str = "") -> int:
        """写入职位，按 jobId 去重（已存在则**整条跳过**），返回新增条数。

        跳过而不是更新是刻意的：``searchKeyword`` 要保持「最先命中它的方向」，
        它是后续按方向分组和分类兜底的依据，被后搜到的关键词覆盖就失真了。
        """
        if not jobs:
            return 0
        now = datetime.now()
        rows = []
        for job in jobs:
            band = parse_salary(job.salary)
            rows.append(
                {
                    **job.model_dump(),
                    "salaryLowWan": band.low if band else None,
                    "salaryHighWan": band.high if band else None,
                    "searchKeyword": keyword,
                    "searchTime": now,
                }
            )
        with self.db.session() as s:
            before = s.scalar(select(func.count()).select_from(JobRecord)) or 0
            stmt = sqlite_insert(JobRecord).on_conflict_do_nothing(index_elements=["jobId"])
            s.execute(stmt, rows)
            s.flush()
            after = s.scalar(select(func.count()).select_from(JobRecord)) or 0
        return after - before

    # ---------------------------------------------------------------- 查询

    def find(self, query: JobQuery | None = None) -> JobPage:
        q = (query or JobQuery()).normalized()
        base = self._apply_filters(select(JobRecord), q)

        with self.db.session() as s:
            total = s.scalar(
                self._apply_filters(select(func.count()).select_from(JobRecord), q)
            ) or 0
            stmt = base.order_by(*self._order_clause(q.order)).limit(q.limit).offset(q.offset)
            items = [r.as_dict() for r in s.scalars(stmt)]
        return JobPage(total=total, items=items)

    def get(self, job_id: int) -> dict[str, Any] | None:
        with self.db.session() as s:
            record = s.get(JobRecord, job_id)
            return record.as_dict() if record else None

    def get_with_detail(self, job_id: int) -> dict[str, Any] | None:
        """职位 + JD 详情 + 投递记录，供 Web 端详情面板一次取齐。"""
        with self.db.session() as s:
            job = s.get(JobRecord, job_id)
            if job is None:
                return None
            detail = s.get(JobDetailRecord, job_id)
            applications = s.scalars(
                select(ApplicationRecord)
                .where(ApplicationRecord.jobId == job_id)
                .order_by(ApplicationRecord.appliedAt.desc())
            ).all()
            return {
                **job.as_dict(),
                "detail": detail.as_dict() if detail else None,
                "applications": [a.as_dict() for a in applications],
            }

    def keyword_counts(self) -> list[dict[str, Any]]:
        """各 searchKeyword 的职位数，按数量降序。"""
        stmt = (
            select(JobRecord.searchKeyword, func.count())
            .group_by(JobRecord.searchKeyword)
            .order_by(func.count().desc())
        )
        with self.db.session() as s:
            return [{"keyword": k or "(未标记)", "count": n} for k, n in s.execute(stmt)]

    def count(self) -> int:
        with self.db.session() as s:
            return s.scalar(select(func.count()).select_from(JobRecord)) or 0

    def missing_details(
        self, retry_failed: bool = False, limit: int | None = None
    ) -> list[tuple[int, str]]:
        """返回还需要抓详情的 ``(jobId, jobDetailUrl)``。

        默认只取从未抓过的；``retry_failed=True`` 时把状态非 ok 的也算进来。
        """
        done = select(JobDetailRecord.jobId)
        if retry_failed:
            done = done.where(JobDetailRecord.status == "ok")
        stmt = (
            select(JobRecord.jobId, JobRecord.jobDetailUrl)
            .where(JobRecord.jobDetailUrl != "")
            .where(JobRecord.jobId.not_in(done))
            .order_by(JobRecord.jobId)
        )
        if limit:
            stmt = stmt.limit(limit)
        with self.db.session() as s:
            return [(jid, url) for jid, url in s.execute(stmt)]

    def salary_summary(self) -> dict[str, Any]:
        """整库薪资概览（万元）。薪资解析不出来的行不计入。"""
        with self.db.session() as s:
            parsed = s.scalar(
                select(func.count()).select_from(JobRecord).where(
                    JobRecord.salaryHighWan.is_not(None)
                )
            ) or 0
            meets_100 = s.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.salaryHighWan >= 100)
            ) or 0
            avg_high = s.scalar(select(func.avg(JobRecord.salaryHighWan))) or 0.0
        return {
            "parsed": parsed,
            # 猎聘的薪资筛选是「区间重叠」而非「下限 ≥」，还会漏进明显不达标的条目，
            # 所以单独暴露真正够到 100 万的比例，避免误以为全部样本都是百万岗
            "meets100": meets_100,
            "meets100Pct": round(meets_100 / parsed * 100, 1) if parsed else 0.0,
            "avgHighWan": round(float(avg_high), 1),
        }

    # ---------------------------------------------------------------- 内部

    def _apply_filters(self, stmt: Select[Any], q: JobQuery) -> Select[Any]:
        if q.keyword:
            stmt = stmt.where(JobRecord.searchKeyword == q.keyword)
        if q.q:
            like = f"%{q.q}%"
            stmt = stmt.where(JobRecord.jobName.like(like) | JobRecord.company.like(like))
        if q.min_salary is not None:
            stmt = stmt.where(JobRecord.salaryHighWan >= q.min_salary)
        if q.has_detail is not None:
            ok_details = select(JobDetailRecord.jobId).where(JobDetailRecord.status == "ok")
            stmt = stmt.where(
                JobRecord.jobId.in_(ok_details)
                if q.has_detail
                else JobRecord.jobId.not_in(ok_details)
            )
        if q.applied is not None:
            applied = select(ApplicationRecord.jobId).where(
                ApplicationRecord.status.in_(APPLIED_STATUSES)
            )
            stmt = stmt.where(
                JobRecord.jobId.in_(applied) if q.applied else JobRecord.jobId.not_in(applied)
            )
        return stmt

    @staticmethod
    def _order_clause(order: OrderBy) -> tuple[Any, ...]:
        if order == "salary":
            # NULL 排最后：薪资写「面议」的职位不该顶在「薪资最高」列表前面
            return (
                JobRecord.salaryHighWan.is_(None),
                JobRecord.salaryHighWan.desc(),
                JobRecord.jobId.desc(),
            )
        if order == "salary_asc":
            return (
                JobRecord.salaryHighWan.is_(None),
                JobRecord.salaryHighWan.asc(),
                JobRecord.jobId.desc(),
            )
        return (JobRecord.searchTime.desc(), JobRecord.jobId.desc())


class DetailRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, detail: dict[str, Any]) -> None:
        """写入/覆盖一条职位详情（按 jobId）。"""
        row = {**detail, "fetchTime": datetime.now()}
        with self.db.session() as s:
            stmt = sqlite_insert(JobDetailRecord).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["jobId"],
                set_={k: stmt.excluded[k] for k in row if k != "jobId"},
            )
            s.execute(stmt)

    def get(self, job_id: int) -> dict[str, Any] | None:
        with self.db.session() as s:
            record = s.get(JobDetailRecord, job_id)
            return record.as_dict() if record else None

    def status_counts(self) -> dict[str, int]:
        stmt = (
            select(JobDetailRecord.status, func.count())
            .group_by(JobDetailRecord.status)
            .order_by(func.count().desc())
        )
        with self.db.session() as s:
            return {status or "(空)": n for status, n in s.execute(stmt)}


class ApplicationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, job_id: int, status: str, message: str) -> dict[str, Any]:
        with self.db.session() as s:
            row = ApplicationRecord(jobId=job_id, status=status, message=message)
            s.add(row)
            s.flush()
            return row.as_dict()

    def recent(self, limit: int = 500) -> list[dict[str, Any]]:
        stmt = (
            select(ApplicationRecord)
            .order_by(ApplicationRecord.appliedAt.desc(), ApplicationRecord.id.desc())
            .limit(limit)
        )
        with self.db.session() as s:
            return [r.as_dict() for r in s.scalars(stmt)]

    def applied_ids(self) -> set[int]:
        stmt = select(ApplicationRecord.jobId).where(
            ApplicationRecord.status.in_(APPLIED_STATUSES)
        )
        with self.db.session() as s:
            return set(s.scalars(stmt))

    def status_counts(self) -> dict[str, int]:
        stmt = (
            select(ApplicationRecord.status, func.count())
            .group_by(ApplicationRecord.status)
            .order_by(func.count().desc())
        )
        with self.db.session() as s:
            return {status or "(空)": n for status, n in s.execute(stmt)}
