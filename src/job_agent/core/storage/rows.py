"""仓储读写用的行模型。

ORM 记录是**会话内**的对象：一旦 session 关闭就可能触发 detached 访问，
所以仓储在会话边界上把每一行转成这里的 pydantic model 再交出去。
转换只用 ``model_validate(record)``（靠 ``from_attributes=True`` 直接读属性），
不写手工的字段搬运函数——手抄一遍字段等于把字段表写两份，加列必漏改一处。

字段名与类型都对齐 ORM 列：名字沿用猎聘接口的 camelCase（库里的列和抓包看到的
字段一一对应，排查数据问题时不用在两套命名之间换算），时间就是 ``datetime``。
展示成什么格式是终端与前端各自的事，模型不预先转成字符串。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from job_agent.core.jd_parser import ParsedDetail


class JobRow(BaseModel):
    """``jobs`` 表的一行。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    jobId: int
    jobType: str = ""
    jobName: str = ""
    company: str = ""
    location: str = ""
    salary: str = ""
    #: 由 salary 文案解析出的年薪区间（万元，税前）；解析不出来时为 None
    salaryLowWan: float | None = None
    salaryHighWan: float | None = None
    education: str = ""
    workYears: str = ""
    industry: str = ""
    companyTags: list[str] = Field(default_factory=list)
    financingStage: str = ""
    companySize: str = ""
    companyLogo: str = ""
    jobDetailUrl: str = ""
    searchKeyword: str = ""
    searchTime: datetime


class JobDetailRow(ParsedDetail):
    """``job_details`` 表的一行：解析出的 JD 字段 + 落库时才有的身份与状态。

    继承 :class:`~job_agent.core.jd_parser.ParsedDetail` 是刻意的：
    这张表存的就是解析结果，字段列表只该有一份。
    """

    model_config = ConfigDict(from_attributes=True)

    jobId: int
    #: ok / no_jd / http_<code> / error:<类型> / blocked
    status: str = ""
    #: 写入时由仓储盖章，传进来的值会被忽略
    fetchTime: datetime | None = None


class ApplicationRow(BaseModel):
    """``applications`` 表的一行（一次投递尝试）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    jobId: int
    status: str = ""
    message: str = ""
    appliedAt: datetime


class JobBundle(JobRow):
    """职位 + JD 详情 + 投递记录，供 Web 端详情面板一次取齐。"""

    detail: JobDetailRow | None = None
    applications: list[ApplicationRow] = Field(default_factory=list)


class KeywordCount(BaseModel):
    """某个 ``searchKeyword`` 下的职位数。"""

    model_config = ConfigDict(extra="forbid")

    keyword: str
    count: int


class PendingDetail(BaseModel):
    """还需要抓详情的职位。"""

    model_config = ConfigDict(extra="forbid")

    jobId: int
    jobDetailUrl: str


class SalarySummary(BaseModel):
    """整库薪资概览（万元，税前）。薪资解析不出来的行不计入。"""

    model_config = ConfigDict(extra="forbid")

    parsed: int
    #: 用来比较的门槛（万元/年，税前），来自当前 profile；没配门槛时为 None
    floorWan: float | None = None
    #: 猎聘的薪资筛选是「区间重叠」而非「下限 ≥」，还会漏进明显不达标的条目，
    #: 所以单独暴露薪资上限真正够到门槛的比例，避免误以为全部样本都达标
    meetsFloor: int = 0
    meetsFloorPct: float = 0.0
    avgHighWan: float
