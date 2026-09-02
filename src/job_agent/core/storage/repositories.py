"""仓储层：SQL 只写在这里，上层拿到的一律是 :mod:`~job_agent.core.storage.rows` 里的模型。

ORM 记录不出会话——每个查询在 ``with self.db.session()`` 里就转成行模型再返回，
上层因此不会碰到 detached 对象，也不会拿到没有 schema 的裸 dict。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Select, func, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from job_agent.core.liepin.enums import JobKind
from job_agent.core.liepin.models import Job
from job_agent.core.salary import parse_salary
from job_agent.core.storage.database import Database
from job_agent.core.storage.models import (
    ApplicationRecord,
    JobDetailRecord,
    JobRecord,
    JobScoreRecord,
)
from job_agent.core.storage.rows import (
    ApplicationRow,
    JobBundle,
    JobDetailRow,
    JobRow,
    KeywordCount,
    PendingDetail,
    SalarySummary,
    ScoreEntry,
    ScoreStatus,
)
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 视为「已投递成功」的状态：already_applied 也算投过（服务端说已投过就是投过）
APPLIED_STATUSES = ("ok", "already_applied")

OrderBy = Literal["score", "recent", "salary", "salary_asc"]

#: 一次最多返回多少条。**这不是分页**——本地单人用、职位数有限，
#: 前端一页显示完；这个上限只是别让一次响应大到离谱的兜底。
#: 命中数超过它时响应里的 total 会大于 jobs 长度，前端必须把这件事说出来
MAX_ROWS = 5000


def _attach_score(row: JobRow, record: JobScoreRecord | None) -> JobRow:
    """把 ``job_scores`` 的一行挂到职位行上。没打分就保持默认（score=None）。"""
    if record is not None:
        row.score = record.score
        row.scoreRank = record.rank
        row.offTrack = record.offTrack
        row.scoreHits = list(record.hits)
        row.scorePenalties = list(record.penalties)
        row.scoredAt = record.scoredAt
    return row


def _job_row(job: JobRecord, score: JobScoreRecord | None) -> JobRow:
    return _attach_score(JobRow.model_validate(job), score)


class JobQuery(BaseModel):
    """职位列表的查询条件。

    **不分页**：本地单人用、职位数有限，一次全给前端，排序在浏览器里做。
    ``limit`` 只是兜底上限，不是页大小；归一（空串当没填、上限夹到合法区间）
    交给字段校验器，构造出来的实例即已归一。
    """

    model_config = ConfigDict(extra="forbid")

    keyword: str | None = None
    q: str | None = None
    #: 只看 HR 直招（``JobKind.HR``）或只看猎头代招（``JobKind.HEADHUNTER``）。
    #: 猎聘的搜索接口不支持按它过滤，只能采回来之后在本地筛
    job_type: JobKind | None = None
    has_detail: bool | None = None
    applied: bool | None = None
    min_salary: float | None = None  # 年薪下限（万元），比较的是 salaryHighWan
    #: 只看打过分的（用来筛掉还没抓 JD、因此没有分数的那些）
    scored: bool | None = None
    order: OrderBy = "score"
    limit: int = MAX_ROWS

    @field_validator("keyword", "q")
    @classmethod
    def _blank_is_unset(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("limit")
    @classmethod
    def _clamp_limit(cls, value: int) -> int:
        # 夹住而不是报错：上层已经在 HTTP 参数上校验过，这里只是兜底
        return max(1, min(value, MAX_ROWS))


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
        """职位列表，LEFT JOIN 上 ``job_scores`` 的分数与排名。

        外连接而不是内连接：没抓 JD 的职位打不了分，但它们仍然该出现在列表里
        （前端要能筛「未抓到 JD」）。没分数的行 ``score`` / ``scoreRank`` 是 None。
        """
        q = query or JobQuery()
        base = self._apply_filters(
            select(JobRecord, JobScoreRecord).outerjoin(
                JobScoreRecord, JobRecord.jobId == JobScoreRecord.jobId
            ),
            q,
        )

        with self.db.session() as s:
            total = s.scalar(
                self._apply_filters(
                    select(func.count())
                    .select_from(JobRecord)
                    .outerjoin(JobScoreRecord, JobRecord.jobId == JobScoreRecord.jobId),
                    q,
                )
            ) or 0
            stmt = base.order_by(*self._order_clause(q.order)).limit(q.limit)
            items = [_job_row(job, score) for job, score in s.execute(stmt)]
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
            _attach_score(bundle, s.get(JobScoreRecord, job_id))
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

    def salary_summary(self, floor_wan: float | None = None) -> SalarySummary:
        """整库薪资概览（万元）。薪资解析不出来的行不计入。

        ``floor_wan`` 是拿来比的门槛，由调用方从当前 profile 传进来——
        「多少算达标」因人而异，不该写死在仓储里。
        """
        with self.db.session() as s:
            parsed = s.scalar(
                select(func.count()).select_from(JobRecord).where(
                    JobRecord.salaryHighWan.is_not(None)
                )
            ) or 0
            meets = (
                s.scalar(
                    select(func.count())
                    .select_from(JobRecord)
                    .where(JobRecord.salaryHighWan >= floor_wan)
                )
                or 0
            ) if floor_wan is not None else 0
            avg_high = s.scalar(select(func.avg(JobRecord.salaryHighWan))) or 0.0
        return SalarySummary(
            parsed=parsed,
            floorWan=floor_wan,
            meetsFloor=meets,
            meetsFloorPct=round(meets / parsed * 100, 1) if parsed and floor_wan else 0.0,
            avgHighWan=round(float(avg_high), 1),
        )

    # ---------------------------------------------------------------- 内部

    def _apply_filters(self, stmt: Select[Any], q: JobQuery) -> Select[Any]:
        if q.keyword:
            stmt = stmt.where(JobRecord.searchKeyword == q.keyword)
        if q.q:
            like = f"%{q.q}%"
            stmt = stmt.where(JobRecord.jobName.like(like) | JobRecord.company.like(like))
        if q.job_type is not None:
            stmt = stmt.where(JobRecord.jobType == q.job_type.value)
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
        if q.scored is not None:
            stmt = stmt.where(
                JobScoreRecord.jobId.is_not(None) if q.scored else JobScoreRecord.jobId.is_(None)
            )
        return stmt

    @staticmethod
    def _order_clause(order: OrderBy) -> tuple[Any, ...]:
        if order == "score":
            # 没打分的排在最后：nulls last 在 SQLite 上要自己拼，用 is_(None) 当第一键
            return (
                JobScoreRecord.score.is_(None),
                JobScoreRecord.score.desc(),
                JobRecord.salaryHighWan.desc(),
            )
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


class ScoreRepository:
    """``job_scores`` 表：整表重写 + 新鲜度查询。

    刻意只有「整表重写」这一种写法，没有按条更新：分数之间是有关系的
    （``rank`` 是全库排名），改一条的权重会牵动别人的名次。
    半张表新半张表旧的排名是错的，而且错得看不出来。
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def replace_all(self, entries: Sequence[ScoreEntry], fingerprint: str) -> int:
        """清表重写。一个事务，中途失败不会留下半新半旧的排名。"""
        stamped = datetime.now()
        with self.db.session() as s:
            s.query(JobScoreRecord).delete()
            if entries:
                s.execute(
                    insert(JobScoreRecord),
                    [
                        {
                            **entry.model_dump(),
                            "rulesFingerprint": fingerprint,
                            "scoredAt": stamped,
                        }
                        for entry in entries
                    ],
                )
        logger.debug("写入 %d 条分数（fingerprint=%s）", len(entries), fingerprint)
        return len(entries)

    def status(self, fingerprint: str) -> ScoreStatus:
        """落库分数新鲜不新鲜：有多少条、多少条有 JD 却没分、信号表变了没。"""
        scorable = (
            select(func.count())
            .select_from(JobRecord)
            .join(JobDetailRecord, JobRecord.jobId == JobDetailRecord.jobId)
            .where(JobDetailRecord.status == "ok")
        )
        with self.db.session() as s:
            scored = s.scalar(select(func.count()).select_from(JobScoreRecord)) or 0
            if not scored:
                return ScoreStatus(scored=0, missing=s.scalar(scorable) or 0, stale=False)
            total_scorable = s.scalar(scorable) or 0
            stamped = s.scalar(select(func.max(JobScoreRecord.scoredAt)))
            prints = set(s.scalars(select(JobScoreRecord.rulesFingerprint).distinct()))
        return ScoreStatus(
            scored=scored,
            missing=max(total_scorable - scored, 0),
            stale=prints != {fingerprint},
            scoredAt=stamped,
        )
