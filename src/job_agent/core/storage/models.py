"""ORM 模型。

字段名沿用猎聘接口的 camelCase：库里的列和抓包看到的字段一一对应，
排查数据问题时不需要在两套命名之间换算。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now()


class JobRecord(Base):
    """搜索结果里的职位，以 jobId 去重、持续累积。"""

    __tablename__ = "jobs"

    jobId: Mapped[int] = mapped_column(Integer, primary_key=True)
    jobType: Mapped[str] = mapped_column(String, default="")
    jobName: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    salary: Mapped[str] = mapped_column(String, default="")
    education: Mapped[str] = mapped_column(String, default="")
    workYears: Mapped[str] = mapped_column(String, default="")
    industry: Mapped[str] = mapped_column(String, default="")
    companyTags: Mapped[list[str]] = mapped_column(JSON, default=list)
    financingStage: Mapped[str] = mapped_column(String, default="")
    companySize: Mapped[str] = mapped_column(String, default="")
    companyLogo: Mapped[str] = mapped_column(String, default="")
    jobDetailUrl: Mapped[str] = mapped_column(String, default="")
    # 由 salary 文案解析出的年薪区间（万元）。写库时算好，是为了能在 SQL 里排序 /
    # 过滤——否则「按薪资排序」只能在内存里做，一分页就错。
    salaryLowWan: Mapped[float | None] = mapped_column(Float, default=None)
    salaryHighWan: Mapped[float | None] = mapped_column(Float, default=None)
    # 采集元数据
    searchKeyword: Mapped[str] = mapped_column(String, default="", index=True)
    searchTime: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (Index("ix_jobs_salary_high", "salaryHighWan"),)

    def as_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.jobId,
            "jobType": self.jobType,
            "jobName": self.jobName,
            "company": self.company,
            "location": self.location,
            "salary": self.salary,
            "salaryLowWan": self.salaryLowWan,
            "salaryHighWan": self.salaryHighWan,
            "education": self.education,
            "workYears": self.workYears,
            "industry": self.industry,
            "companyTags": self.companyTags or [],
            "financingStage": self.financingStage,
            "companySize": self.companySize,
            "companyLogo": self.companyLogo,
            "jobDetailUrl": self.jobDetailUrl,
            "searchKeyword": self.searchKeyword,
            "searchTime": _iso(self.searchTime),
        }


class JobDetailRecord(Base):
    """职位详情页（jobDetailUrl）解析结果，一条对应一个 jobId。

    数据源为详情页里的 ``application/ld+json`` JobPosting 结构化数据，
    比 HTML 结构稳定得多。``status`` 记录抓取结果，便于失败后只重跑失败项。
    """

    __tablename__ = "job_details"

    jobId: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, default="")
    # 完整职位描述（岗位职责 + 任职要求），保留原始换行
    description: Mapped[str] = mapped_column(Text, default="")
    # 从 description 中按小标题切分出的两段；切不出来时为空
    responsibilities: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[str] = mapped_column(Text, default="")
    industry: Mapped[str] = mapped_column(String, default="")
    experienceRequirements: Mapped[str] = mapped_column(String, default="")
    educationRequirements: Mapped[str] = mapped_column(String, default="")
    employmentType: Mapped[str] = mapped_column(String, default="")
    datePosted: Mapped[str] = mapped_column(String, default="")
    companyName: Mapped[str] = mapped_column(String, default="")
    companyUrl: Mapped[str] = mapped_column(String, default="")
    streetAddress: Mapped[str] = mapped_column(String, default="")
    # ok / no_jd（页面无 JobPosting，多为职位已下线）/ http_<code> / error:<类型> / blocked
    status: Mapped[str] = mapped_column(String, default="", index=True)
    fetchTime: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.jobId,
            "title": self.title,
            "description": self.description,
            "responsibilities": self.responsibilities,
            "requirements": self.requirements,
            "industry": self.industry,
            "experienceRequirements": self.experienceRequirements,
            "educationRequirements": self.educationRequirements,
            "employmentType": self.employmentType,
            "datePosted": self.datePosted,
            "companyName": self.companyName,
            "companyUrl": self.companyUrl,
            "streetAddress": self.streetAddress,
            "status": self.status,
            "fetchTime": _iso(self.fetchTime),
        }


class ApplicationRecord(Base):
    """投递记录。

    猎聘**没有**查询投递记录的接口，所以本地必须自己记：否则只能靠重复投递
    （服务端会无害地拒掉）去反推投过没投过。一个 jobId 允许多条，保留每次尝试。
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jobId: Mapped[int] = mapped_column(Integer, index=True)
    # ok / already_applied / closed / failed / error
    status: Mapped[str] = mapped_column(String, default="", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    appliedAt: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "jobId": self.jobId,
            "status": self.status,
            "message": self.message,
            "appliedAt": _iso(self.appliedAt),
        }


def _iso(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""
