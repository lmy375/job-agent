"""猎聘接口的请求 / 响应模型。字段名保持服务端的 camelCase，便于对照抓包。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from job_agent.core.liepin.enums import EduLevel, SalaryKind, WorkExperience


class SearchJobInput(BaseModel):
    """搜索职位入参，字段均可选；不传即不按该维度过滤。

    说明：

    - 关键词类字段（jobName / companyName / address）为服务端模糊匹配。
    - 枚举字段（eduLevel / workExperience / salaryKind）传枚举外的值会被静默忽略。
    - salaryFloor / salaryCap 单位为「元」，按区间**重叠**过滤；
      salaryKind=年薪 时把职位薪资（月薪 × 月数）年化后比较。
      年薪 100 万以上 → salaryKind=年薪, salaryFloor="1000000"。
    - compNature 为弱匹配：``国企 / 外企 / 合资 / 事业单位 / 政府机关 / 国内上市公司``
      等可命中，``民营 / 上市公司 / 创业公司`` 等实测被忽略，故保留为自由文本。
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    jobName: str | None = Field(default=None, description="职位名称关键词，模糊匹配")
    companyName: str | None = Field(default=None, description="公司名称，模糊匹配")
    address: str | None = Field(default=None, description="工作地点，如「北京」「上海-浦东」")
    eduLevel: EduLevel | None = Field(default=None, description="学历要求")
    workExperience: WorkExperience | None = Field(default=None, description="工作经验要求")
    compNature: str | None = Field(
        default=None, description="公司性质，如 国企 / 外企 / 合资 / 事业单位（弱匹配）"
    )
    salaryKind: SalaryKind | None = Field(
        default=None, description="薪资类型，需配合 salaryFloor / salaryCap 使用"
    )
    salaryFloor: str | None = Field(
        default=None, description="薪资下限，单位为元；年薪 100 万 = 1000000"
    )
    salaryCap: str | None = Field(default=None, description="薪资上限，单位为元")
    page: Annotated[int, Field(ge=0)] | None = Field(
        default=None, description="分页页码，0 表示第 1 页；不传按 0 处理"
    )


class Job(BaseModel):
    """单条职位。字段直接来自 search-job 响应中的 data.list 元素。"""

    jobId: int = Field(description="职位 ID，投递时作为 jobId")
    jobType: str = Field(
        description='职位类型："2" 普通职位（链接 /job/），"1" 猎头职位（链接 /a/）；'
        "投递时作为 jobKind"
    )
    jobName: str = Field(description="职位名称")
    company: str = Field(description="公司名称")
    location: str = Field(description="工作地点，如「北京-中关村」")
    salary: str = Field(description="薪资，如「35-45k·15薪」「10-18k」")
    education: str = Field(description="学历要求，取值同 EduLevel")
    workYears: str = Field(description="经验要求展示文案，如「3-5年」「经验不限」")
    industry: str = Field(description="所属行业，可能为逗号分隔的多个")
    companyTags: list[str] = Field(default=[], description="公司标签，如「大平台」「五险一金」")
    financingStage: str = Field(
        default="", description="融资阶段，如「已上市」「天使轮融资」，可能为空"
    )
    companySize: str = Field(default="", description="公司规模，如「10000人以上」，可能为空")
    companyLogo: str = Field(default="", description="公司 logo 文件名")
    jobDetailUrl: str = Field(default="", description="职位详情页 URL")


class SearchJobData(BaseModel):
    jobs: list[Job] = Field(default=[], alias="list")


class SearchJobResponse(BaseModel):
    code: int  # 业务状态码，0 为成功；非 0 表示错误（如 429001 请求过于频繁）
    msg: str = ""
    data: SearchJobData


class ApplyJobResult(BaseModel):
    """apply-job 的解析结果。

    服务端把业务失败也放在正常响应里（errCode=0 + 中文文案），所以不抛异常，
    由调用方根据字段决定如何处理。已知的两种失败原因单独解析成布尔字段。
    """

    ok: bool = Field(description="是否投递成功")
    message: str = Field(
        description="服务端原始文案，如「应聘成功」「应聘失败: 您已投递过该职位！」"
    )
    already_applied: bool = Field(default=False, description="失败原因：此前已投递过")
    closed: bool = Field(default=False, description="失败原因：职位已下线")

    @property
    def status(self) -> str:
        """归一化状态，用于落库：ok / already_applied / closed / failed。"""
        if self.ok:
            return "ok"
        if self.already_applied:
            return "already_applied"
        if self.closed:
            return "closed"
        return "failed"
