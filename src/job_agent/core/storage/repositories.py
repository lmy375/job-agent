"""仓储层：SQL 只写在这里，上层拿到的一律是 :mod:`~job_agent.core.storage.rows` 里的模型。

ORM 记录不出会话——每个查询在 ``with self.db.session()`` 里就转成行模型再返回，
上层因此不会碰到 detached 对象，也不会拿到没有 schema 的裸 dict。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from job_agent.core.liepin.models import Job
from job_agent.core.salary import parse_salary
from job_agent.core.storage.database import Database
from job_agent.core.storage.models import ApplicationRecord, JobDetailRecord, JobRecord
from job_agent.core.storage.rows import (
    ApplicationRow,
    JobBundle,
    JobDetailRow,
    JobRow,
    KeywordCount,
    PendingDetail,
    SalarySummary,
)
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 视为「已投递成功」的状态：already_applied 也算投过（服务端说已投过就是投过）
APPLIED_STATUSES = ("ok", "already_applied")

OrderBy = Literal["recent", "salary", "salary_asc"]

DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 2000


class JobQuery(BaseModel):
    """职位列表的查询条件。默认分页，避免一次把整库塞进响应。

    归一（空串当没填、分页夹到合法区间）交给字段校验器，
    构造出来的实例即已归一，调用方不需要再记得调一次什么方法。
    """

    model_config = ConfigDict(extra="forbid")

    keyword: str | None = None
    q: str | None = None
    has_detail: bool | None = None
    applied: bool | None = None
    min_salary: float | None = None  # 年薪下限（万元），比较的是 salaryHighWan
    order: OrderBy = "recent"
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    @field_validator("keyword", "q")
    @classmethod
    def _blank_is_unset(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("limit")
    @classmethod
    def _clamp_limit(cls, value: int) -> int:
        # 夹住而不是报错：上层已经在 HTTP 参数上校验过，这里只是兜底
        return max(1, min(value, MAX_PAGE_SIZE))

    @field_validator("offset")
    @classmethod
    def _floor_offset(cls, value: int) -> int:
        return max(0, value)


class JobPage(BaseModel):
    total: int
    items: list[JobRow] = Field(default_factory=list)


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
        q = query or JobQuery()
        base = self._apply_filters(select(JobRecord), q)

        with self.db.session() as s:
            total = s.scalar(
                self._apply_filters(select(func.count()).select_from(JobRecord), q)
            ) or 0
            stmt = base.order_by(*self._order_clause(q.order)).limit(q.limit).offset(q.offset)
            items = [JobRow.model_validate(r) for r in s.scalars(stmt)]
        return JobPage(total=total, items=items)

    def get(self, job_id: int) -> JobRow | None:
        with self.db.session() as s:
            record = s.get(JobRecord, job_id)
            return JobRow.model_validate(record) if record else None

    def get_with_detail(self, job_id: int) -> JobBundle | None:
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
            # 先按职位行校验，再挂上关联数据：两张表之间没有外键，
            # 让 ORM 去做 relationship 只会为一个接口引入懒加载的坑
            bundle = JobBundle.model_validate(job)
            bundle.detail = JobDetailRow.model_validate(detail) if detail else None
            bundle.applications = [ApplicationRow.model_validate(a) for a in applications]
            return bundle

    def keyword_counts(self) -> list[KeywordCount]:
        """各 searchKeyword 的职位数，按数量降序。"""
        stmt = (
            select(JobRecord.searchKeyword, func.count())
            .group_by(JobRecord.searchKeyword)
            .order_by(func.count().desc())
        )
        with self.db.session() as s:
            return [KeywordCount(keyword=k or "(未标记)", count=n) for k, n in s.execute(stmt)]

    def count(self) -> int:
        with self.db.session() as s:
            return s.scalar(select(func.count()).select_from(JobRecord)) or 0

    def missing_details(
        self, retry_failed: bool = False, limit: int | None = None
    ) -> list[PendingDetail]:
        """返回还需要抓详情的职位（jobId + 详情页地址）。

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
            return [
                PendingDetail(jobId=jid, jobDetailUrl=url) for jid, url in s.execute(stmt)
            ]

    def salary_summary(self) -> SalarySummary:
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
        return SalarySummary(
            parsed=parsed,
            meets100=meets_100,
            meets100Pct=round(meets_100 / parsed * 100, 1) if parsed else 0.0,
            avgHighWan=round(float(avg_high), 1),
        )

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

    def upsert(self, detail: JobDetailRow) -> None:
        """写入/覆盖一条职位详情（按 jobId）。``fetchTime`` 由这里盖章。

        这里的 mapping 是 SQLAlchemy ``insert().values()`` 的调用契约，
        不是跨层传递的数据结构——传进来和读出去的都是 :class:`JobDetailRow`。
        """
        row: dict[str, Any] = {
            **detail.model_dump(exclude={"fetchTime"}),
            "fetchTime": datetime.now(),
        }
        with self.db.session() as s:
            stmt = sqlite_insert(JobDetailRecord).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["jobId"],
                set_={k: stmt.excluded[k] for k in row if k != "jobId"},
            )
            s.execute(stmt)

    def get(self, job_id: int) -> JobDetailRow | None:
        with self.db.session() as s:
            record = s.get(JobDetailRecord, job_id)
            return JobDetailRow.model_validate(record) if record else None

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

    def record(self, job_id: int, status: str, message: str) -> ApplicationRow:
        with self.db.session() as s:
            row = ApplicationRecord(jobId=job_id, status=status, message=message)
            s.add(row)
            s.flush()
            return ApplicationRow.model_validate(row)

    def recent(self, limit: int = 500) -> list[ApplicationRow]:
        stmt = (
            select(ApplicationRecord)
            .order_by(ApplicationRecord.appliedAt.desc(), ApplicationRecord.id.desc())
            .limit(limit)
        )
        with self.db.session() as s:
            return [ApplicationRow.model_validate(r) for r in s.scalars(stmt)]

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
