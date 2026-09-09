"""把 ``jobs`` × ``job_details`` 关联成打分用的行集合。

**这一层只做事实，不做分析。** 关联、解析薪资、按 JD 正文去重——
每一步都有唯一正确答案，换谁来跑结果都一样。

「这条属于哪个赛道」「这个岗位是什么角色」「JD 里提到哪些技能」
一概不在这里，也不在这个仓库的任何地方：那是分析，因人而异，
归 skill 或用户自己的脚本（见 CLAUDE.md「不承担市场分析」一节）。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from job_agent.core.salary import parse_salary
from job_agent.core.storage import Database, JobDetailRecord, JobRecord
from job_agent.log import get_logger

logger = get_logger(__name__)

#: JD 正文短于这个长度视为没抓到有效内容
MIN_DESCRIPTION_LEN = 30

#: 单条 JD 送模型的正文上限。JD 正常几千字符，超长的多半是页面噪声，截断以控成本
JD_CHAR_LIMIT = 6000

_WS_RE = re.compile(r"\s+")


class JobFacts(BaseModel):
    """一条职位的**可校验事实**：``jobs`` × ``job_details`` 关联后附上年薪区间。

    打分（``core/matching``）与 agent 路线共用这一份行结构，所以字段只该定义一次。
    字段名沿用猎聘接口的 camelCase；派生字段（``salaryLow`` / ``salaryHigh`` /
    ``dupes``）一律带默认值，构造测试数据时不必写全。

    这里**没有** track / role / skills 这类字段——它们是判断，不是事实。
    """

    model_config = ConfigDict(extra="forbid")

    jobId: int
    jobName: str = ""
    company: str = ""
    salary: str = ""
    #: 年薪区间（万元，税前），由 salary 文案解析而来；解析不出来时为 None
    salaryLow: float | None = None
    salaryHigh: float | None = None
    education: str = ""
    workYears: str = ""
    industry: str = ""
    financingStage: str = ""
    companySize: str = ""
    location: str = ""
    url: str = ""
    #: 最先命中这条职位的 searchKeyword
    keyword: str = ""
    description: str = ""
    responsibilities: str = ""
    requirements: str = ""
    #: 同一份 JD 被几家挂出（去重后才 > 1）
    dupes: int = 1


def jd_key(description: str) -> str:
    """去重键：只用 JD 正文（去掉全部空白）。

    同一职位常被多家猎头重复挂出：正文一字不差，但职位名和标价各挂各的
    （实测有一份被挂了 8 次，同一岗位标价能差 2–3 倍）。
    把职位名也算进键里会漏掉大部分重复。
    """
    return _WS_RE.sub("", description)


def load_rows(db: Database, dedupe: bool = True) -> list[JobFacts]:
    """读取所有抓到 JD 的职位，附上年薪区间。

    ``dedupe=True`` 时按 JD 正文去重，保留标价最高的那条，并在 ``dupes`` 里记重复次数。
    """
    stmt = select(JobRecord, JobDetailRecord).join(
        JobDetailRecord, JobRecord.jobId == JobDetailRecord.jobId
    )
    rows: list[JobFacts] = []
    with db.session() as session:
        for job, detail in session.execute(stmt):
            if detail.status != "ok" or len(detail.description) < MIN_DESCRIPTION_LEN:
                continue
            band = parse_salary(job.salary)
            rows.append(
                JobFacts(
                    jobId=job.jobId,
                    jobName=job.jobName,
                    company=job.company,
                    salary=job.salary,
                    salaryLow=band.low if band else None,
                    salaryHigh=band.high if band else None,
                    education=job.education,
                    workYears=job.workYears,
                    industry=detail.industry or job.industry,
                    financingStage=job.financingStage,
                    companySize=job.companySize,
                    location=job.location,
                    url=job.jobDetailUrl,
                    keyword=job.searchKeyword,
                    description=detail.description,
                    responsibilities=detail.responsibilities,
                    requirements=detail.requirements,
                )
            )

    logger.debug("载入 %d 条有效 JD（dedupe=%s）", len(rows), dedupe)
    if not dedupe:
        return rows
    return dedupe_rows(rows)


def dedupe_rows(rows: list[JobFacts]) -> list[JobFacts]:
    """同一 JD 被多家猎头挂出时，保留标价最高的那条，并记下重复次数。

    **就地改 ``dupes``**：传进来的对象本身会被打上重复次数，
    所以打完分再调它，``ScoredJob.row.dupes`` 也跟着对——不需要再关联一次。
    """
    best: dict[str, JobFacts] = {}
    for row in rows:
        key = jd_key(row.description)
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        current.dupes += 1
        if (row.salaryHigh or 0) > (current.salaryHigh or 0):
            row.dupes = current.dupes
            best[key] = row
    return list(best.values())


def jd_text(row: JobFacts, limit: int = JD_CHAR_LIMIT) -> str:
    """把三段正文合成一份送模型的 JD 文本。

    ``description`` 通常已经包含职责与要求，三段直接拼会重复一大半，
    所以去掉被前文包含的段。超长截断只为控成本——JD 正常几千字符，
    上万的基本是页面噪声混了进来。
    """
    parts = [text.strip() for text in (row.description, row.responsibilities, row.requirements)]
    merged: list[str] = []
    for part in parts:
        if part and not any(part in kept for kept in merged):
            merged.append(part)
    text = "\n\n".join(merged)
    if len(text) > limit:
        text = text[:limit] + "\n……（超长截断）"
    return text
