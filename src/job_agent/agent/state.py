"""图状态与数据模型。

刻意不 import langgraph：这里是纯数据结构，pipeline 层与测试
在没装 agent extra 的环境里也要能用。

全部是 pydantic model，不用裸 dict（仓库硬规则）：
状态在 checkpoint 里怎么序列化、节点之间传什么字段，都以这里的定义为准。
``JDVerdict`` 是整条路线里唯一由 LLM 产出的东西——字段固定、带校验，
两次运行的裁决**结构可比**（内容当然可能不同，判断本来就会变）。
"""

from __future__ import annotations

import operator
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class JDVerdict(BaseModel):
    """LLM 审读一条 JD 后的结构化裁决。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(description="职位 ID，从输入原样带回")
    hard_gate_pass: bool = Field(
        description="JD 明确写出的硬门槛（学历、经验年限、管理规模、语言、驻地等）是否全部满足"
    )
    gate_reasons: list[str] = Field(
        default_factory=list,
        description="逐条硬门槛的比对结论，通过与否都要写；JD 没写明的写「JD 未说明」",
    )
    priority: int = Field(ge=1, le=5, description="投递优先级，5 最高；硬门槛不过的一律给 1")
    pitch: str = Field(description="投递口径：两三句话说清楚为什么这个人适合这个岗")
    risks: list[str] = Field(default_factory=list, description="面试中可能被挑战的点")


class ShortlistJob(BaseModel):
    """规则分诊后送审的单个岗位载荷（确定性代码产出）。"""

    job_id: int
    title: str
    company: str
    salary_low: float | None = None
    salary_high: float | None = None
    score: float
    reasons: str
    concerns: str
    jd: str


class ReviewInput(BaseModel):
    """``Send`` 扇出时传给单个审读节点的输入。"""

    job: ShortlistJob
    resume: str
    preferences: str


class ApplyCandidate(BaseModel):
    """投递确认时展示给人的候选条目。"""

    job_id: int
    priority: int
    pitch: str


class ConfirmRequest(BaseModel):
    """interrupt 时抛给人的确认请求。"""

    question: str
    candidates: list[ApplyCandidate]
    plan_output: str


class AppliedResult(BaseModel):
    """一条投递结果（来自共享内核 ApplyService 的回执）。"""

    job_id: int
    status: str
    message: str


class AgentState(BaseModel):
    """主图状态。LangGraph 直接用 pydantic model 做 state schema。

    ``verdicts`` 挂了 ``operator.add`` reducer：审读节点按岗位并行扇出，
    各自返回单元素列表，由 LangGraph 汇总。
    """

    resume: str = ""
    preferences: str = ""
    #: 这次跑的是哪个 profile。和 ``model_label`` 同理：同一个库、不同的简历与
    #: 信号表，排出来的优先级本来就该不一样——回看时得先知道这是谁的计划
    profile_name: str = ""
    #: 这次审读用的模型（provider / model）。进状态是为了让 checkpoint 自带这条
    #: 记录——事后回放「当时为什么这么排」时，先得知道当时是谁在判断
    model_label: str = ""
    #: 运行开关，来自命令行；不进 config——同一份配置既能只分诊也能全流程
    collect: bool = False
    apply_enabled: bool = False
    shortlist: list[ShortlistJob] = Field(default_factory=list)
    verdicts: Annotated[list[JDVerdict], operator.add] = Field(default_factory=list)
    plan: str = ""
    approved_ids: list[int] = Field(default_factory=list)
    applied: list[AppliedResult] = Field(default_factory=list)
