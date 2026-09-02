"""把 jobs + job_details 关联成分析用的行集合（含赛道、角色、年薪）。"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from job_agent.config import Settings
from job_agent.core.analysis.classify import classify, norm_years
from job_agent.core.salary import parse_salary
from job_agent.core.storage import Database, JobDetailRecord, JobRecord
from job_agent.log import get_logger
from job_agent.tracks import OTHER, Track

logger = get_logger(__name__)

#: JD 正文短于这个长度视为没抓到有效内容
MIN_DESCRIPTION_LEN = 30

_WS_RE = re.compile(r"\s+")


class AnalysisRow(BaseModel):
    """一条参与分析的职位：``jobs`` × ``job_details`` 关联后附上赛道 / 角色 / 年薪。

    这是分析、报告、匹配三层共用的行结构——统计要读它，打分要读它，
    清单渲染也要读它，所以字段定义只该有一份。
    字段名混用 camelCase（来自猎聘接口的原样字段）与派生字段
    （``yearsBucket`` / ``track`` / ``role`` / ``dupes``），
    派生字段一律带默认值，构造测试数据时不必写全。
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
    #: workYears 归一到固定档位，见 :func:`~job_agent.core.analysis.classify.norm_years`
    yearsBucket: str = ""
    industry: str = ""
    financingStage: str = ""
    companySize: str = ""
    location: str = ""
    url: str = ""
    #: 最先命中这条职位的 searchKeyword
    keyword: str = ""
    track: Track = OTHER
    role: str = ""
    description: str = ""
    responsibilities: str = ""
    requirements: str = ""
    #: 同一份 JD 被几家挂出（去重后才 > 1）
    dupes: int = 1
    #: 技能词命中：分类名 -> 命中的展示名集合。由 analyze_rows 填，载入时为空
    skills: dict[str, set[str]] = Field(default_factory=dict)


def jd_key(description: str) -> str:
    """去重键：只用 JD 正文（去掉全部空白）。

    同一职位常被多家猎头重复挂出：正文一字不差，但职位名和标价各挂各的
    （实测有一份被挂了 8 次，同一岗位标价能差 2–3 倍）。
    把职位名也算进键里会漏掉大部分重复，而重复会让被多家代理的岗位在统计里放大数倍。
    """
    return _WS_RE.sub("", description)


def load_rows(db: Database, settings: Settings, dedupe: bool = True) -> list[AnalysisRow]:
    """读取所有抓到 JD 的职位，附上赛道 / 角色 / 年薪区间。

    ``dedupe=True`` 时按 JD 正文去重，保留标价最高的那条，并在 ``dupes`` 里记重复次数。
    """
    stmt = select(JobRecord, JobDetailRecord).join(
        JobDetailRecord, JobRecord.jobId == JobDetailRecord.jobId
    )
    rows: list[AnalysisRow] = []
    with db.session() as session:
        for job, detail in session.execute(stmt):
            if detail.status != "ok" or len(detail.description) < MIN_DESCRIPTION_LEN:
                continue
            track, role = classify(
                job.jobName,
                detail.description,
                settings.search.track_for_keyword(job.searchKeyword),
            )
            band = parse_salary(job.salary)
            rows.append(
                AnalysisRow(
                    jobId=job.jobId,
                    jobName=job.jobName,
                    company=job.company,
                    salary=job.salary,
                    salaryLow=band.low if band else None,
                    salaryHigh=band.high if band else None,
                    education=job.education,
                    workYears=job.workYears,
                    yearsBucket=norm_years(job.workYears),
                    industry=detail.industry or job.industry,
                    financingStage=job.financingStage,
                    companySize=job.companySize,
                    location=job.location,
                    url=job.jobDetailUrl,
                    keyword=job.searchKeyword,
                    track=track,
                    role=role,
                    description=detail.description,
                    responsibilities=detail.responsibilities,
                    requirements=detail.requirements,
                )
            )

    logger.debug("载入 %d 条有效 JD（dedupe=%s）", len(rows), dedupe)
    if not dedupe:
        return rows
    return _dedupe(rows)


def _dedupe(rows: list[AnalysisRow]) -> list[AnalysisRow]:
    """同一 JD 被多家猎头挂出时，保留标价最高的那条，并记下重复次数。"""
    best: dict[str, AnalysisRow] = {}
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
