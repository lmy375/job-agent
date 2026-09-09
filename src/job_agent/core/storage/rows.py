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

    # ---- 以下来自 job_scores（LEFT JOIN，没打分就整块是 None / 空）
    #: `job score` 算出的分数
    score: float | None = None
    #: 全库密集排名（按分数降序，1 起），与看的时候的过滤条件无关
    scoreRank: int | None = None
    #: 职位名与 JD 都没命中 [score.require].pattern
    offTrack: bool | None = None
    scoreHits: list[str] = Field(default_factory=list)
    scorePenalties: list[str] = Field(default_factory=list)
    scoredAt: datetime | None = None

    # ---- 以下来自 llm_scores（LEFT JOIN，没送过模型就整块是 None / 空）
    #: 岗位吸引力（1-10，从求职者角度）
    llmAppeal: int | None = None
    #: 胜任匹配度（1-10，从招聘方角度）
    llmFit: int | None = None
    llmAppealReasons: list[str] = Field(default_factory=list)
    llmFitReasons: list[str] = Field(default_factory=list)
    #: 判这条的模型。分数换了模型就不可比，所以逐行记
    llmProvider: str | None = None
    llmModel: str | None = None
    llmScoredAt: datetime | None = None


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


class ScoreEntry(BaseModel):
    """一条要落库的打分结果。仓储收它，不收裸 dict。"""

    model_config = ConfigDict(extra="forbid")

    jobId: int
    score: float
    rank: int
    offTrack: bool = False
    hits: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)


class LlmScoreEntry(BaseModel):
    """一条要落库的 LLM 打分结果。仓储收它，不收裸 dict。

    刻意**不含** provider / model / promptFingerprint / scoredAt：
    同一次运行里这四样对所有行都一样，由仓储统一盖章——
    让调用方逐行填一遍，迟早会出现半张表盖 A、半张表盖 B。
    """

    model_config = ConfigDict(extra="forbid")

    jobId: int
    appealScore: int = Field(ge=1, le=10)
    fitScore: int = Field(ge=1, le=10)
    appealReasons: list[str] = Field(default_factory=list)
    fitReasons: list[str] = Field(default_factory=list)


class LlmScoreStatus(BaseModel):
    """LLM 打分的覆盖率与新鲜度。

    和 :class:`ScoreStatus` 的关键差别：``missing`` 在这里**不是问题**。
    关键词打分是全库刷新，漏一条就是没跑；LLM 打分按条计费，
    「大部分没打过」是常态，所以这里只报覆盖率，不报「该重打了」。
    ``stale`` 才是要提醒的：已打过的行里有换了模型或改了提示词的。
    """

    model_config = ConfigDict(extra="forbid")

    #: 库里有 JD、够格送模型的条数
    scorable: int = 0
    #: 已打过分的条数
    scored: int = 0
    #: 已打分的行里，用当前提示词 + 当前模型判的有几条
    current: int = 0
    #: 存在用别的提示词或别的模型判出来的分数——它们和现在这批不可比
    stale: bool = False
    scoredAt: datetime | None = None


class ScoreStatus(BaseModel):
    """落库分数的新鲜度。``job stats`` 与 Web 概览靠它提醒「该重新打分了」。"""

    model_config = ConfigDict(extra="forbid")

    #: 已打分的条数
    scored: int = 0
    #: 有 JD、却还没打分的条数（采完新数据没跑 job score 就会有）
    missing: int = 0
    #: 落库分数用的信号表指纹与当前配置不一致 = 改过 [score] 但没重新打分
    stale: bool = False
    scoredAt: datetime | None = None

    @property
    def fresh(self) -> bool:
        return self.scored > 0 and self.missing == 0 and not self.stale
