"""ORM 模型。

字段名沿用猎聘接口的 camelCase：库里的列和抓包看到的字段一一对应，
排查数据问题时不需要在两套命名之间换算。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
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


class JobScoreRecord(Base):
    """``job score`` 落库的分数与排名。

    单独一张表，不塞进 ``jobs``：``jobs`` 存的是猎聘接口返回的**事实**，
    这里存的是按**用户自己的** ``[score]`` 信号表算出来的结论。
    两者的生命周期也不同——重新打分是整表重写，采集是按 jobId 累积。

    ``rulesFingerprint`` 每行都存一份（同一次刷新里所有行都一样）：
    整表是一次事务里重写的，不存在半新半旧，所以不需要再开一张运行记录表；
    读的时候拿它和当前配置的指纹一比，就知道分数过期没。
    """

    __tablename__ = "job_scores"

    jobId: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    #: 全库密集排名（按 score 降序，1 起）。**与 --floor / -n 无关**——
    #: 那些是看的时候的过滤条件，不该让同一条职位的名次随着看法变
    rank: Mapped[int] = mapped_column(Integer, default=0, index=True)
    #: 职位名与 JD 都没命中 [score.require].pattern
    offTrack: Mapped[bool] = mapped_column(Boolean, default=False)
    #: 命中 / 扣分信号的名字，给「为什么排这么高」留证据
    hits: Mapped[list[str]] = mapped_column(JSON, default=list)
    penalties: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: 算这批分数时 [score] 配置的指纹，见类文档
    rulesFingerprint: Mapped[str] = mapped_column(String, default="", index=True)
    scoredAt: Mapped[datetime] = mapped_column(DateTime, default=_now)


class LlmScoreRecord(Base):
    """``job llm-score`` 落库的两维语义打分。

    和 ``job_scores`` 分两张表，因为**刷新语义正相反**：那张是整表重写的全库排名
    （改一条权重会牵动所有人的名次），这张是按条产出、按条累积的——LLM 打分按条
    计费，不可能因为多采了 10 条职位就把全库几千条重打一遍。混在一张表里，
    两种刷新会互相把对方的结果抹掉。

    也**不存全库排名**：名次是「全量重算一遍」才有的概念，而这张表天然是残缺的
    （只打过一部分）。排序交给读的那一方（Web 点表头、CLI 按分排）。

    ``promptFingerprint`` + ``provider`` + ``model`` 三者一起判过期：换了模型或改了
    提示词，同一条 JD 的分数就不再可比——回看时得能分清「分数变了」是因为
    JD 变了，还是因为换了判断的人。
    """

    __tablename__ = "llm_scores"

    jobId: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: 岗位吸引力（1-10）：从求职者角度，这份工作本身值多少分
    appealScore: Mapped[int] = mapped_column(Integer, default=0, index=True)
    #: 胜任匹配度（1-10）：从招聘方角度，这个人拿到它的概率有多大
    fitScore: Mapped[int] = mapped_column(Integer, default=0, index=True)
    #: 两个维度各自的打分依据，一条或多条。没有依据的分数不可复核
    appealReasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    fitReasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: 判这条的模型（[agent.providers.*] 的表名 + 模型名）
    provider: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    #: 两段提示词最终文本的指纹，见类文档
    promptFingerprint: Mapped[str] = mapped_column(String, default="", index=True)
    scoredAt: Mapped[datetime] = mapped_column(DateTime, default=_now)
