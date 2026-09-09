"""图节点。

节点分两种，边界与全仓库一致：
- **确定性节点**（collect / triage / plan / apply）：直接调共享内核，零 LLM。
- **判断节点**（review）：整条路线里唯一调 LLM 的地方——读 JD 比硬门槛、写投递口径。

状态与载荷全是 pydantic model（见 state.py）；节点的**返回值**是「状态更新」，
按 LangGraph 的框架契约必须是 mapping，这是仓库「禁止裸 dict」规则的豁免点。

需要 agent extra（langgraph、langchain-anthropic）。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END
from langgraph.types import Send, interrupt

from job_agent.agent.pipeline import build_shortlist, render_plan
from job_agent.agent.prompts import review_system_message, review_user_message
from job_agent.agent.state import (
    AgentState,
    AppliedResult,
    ApplyCandidate,
    ConfirmRequest,
    JDVerdict,
    ReviewInput,
)
from job_agent.context import AppContext
from job_agent.core.llm import bind_schema
from job_agent.core.profile import load_profile
from job_agent.core.services.apply import ApplyService
from job_agent.core.services.detail import DetailService
from job_agent.core.services.progress import ProgressEvent
from job_agent.core.services.search import SearchService
from job_agent.errors import JobAgentError
from job_agent.log import get_logger

logger = get_logger(__name__)


def _print_progress(event: ProgressEvent) -> None:
    """agent 路线是纯终端程序，进度直接打 stdout。"""
    prefix = {"info": "  ", "warn": "! ", "error": "!!"}[event.level]
    print(f"{prefix}{event.message}")


class GraphNodes:
    """把节点函数绑到 ``AppContext`` 与 LLM 上。

    ctx 不进图状态：状态要能 checkpoint 序列化，数据库连接和配置树不属于它。
    """

    def __init__(self, ctx: AppContext, llm: Any) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        # 结构化输出：裁决必须符合 JDVerdict 的 schema，字段口径跨次运行一致。
        # 用哪种实现方式由 [agent.providers.*].structured_output 决定——各家支持度不同
        method = self.settings.agent.active.structured_output
        self._review_llm = bind_schema(llm, JDVerdict, method)
        self._review_system = review_system_message(method)

    # ------------------------------------------------------------ 确定性节点

    def profile(self, state: AgentState) -> dict[str, Any]:
        resume, preferences = load_profile(self.settings)
        return {
            "resume": resume,
            "preferences": preferences,
            "profile_name": self.settings.profile_name,
            "model_label": self.settings.agent.model_label,
        }

    def collect(self, state: AgentState) -> dict[str, Any]:
        """采集：search + detail，直接复用两条路线共享的服务层。默认跳过。"""
        if not state.collect:
            return {}
        client = self.ctx.client()  # 这里才要猎聘 token；纯分诊/审读不需要
        summary = SearchService(
            self.settings, client, self.ctx.jobs, on_progress=_print_progress
        ).run()
        if summary.aborted:
            # 限流中止不是致命错误：库里已有的数据照样能分诊，继续往下走
            print(f"! 采集中止（{summary.aborted_reason}），继续用库内已有数据")
        detail = DetailService(
            self.settings, self.ctx.jobs, self.ctx.details, on_progress=_print_progress
        )
        try:
            detail.run()
        finally:
            detail.close()
        return {}

    def triage(self, state: AgentState) -> dict[str, Any]:
        shortlist = build_shortlist(self.ctx, self.settings.agent.top_n)
        print(f"  规则分诊完成：送审 {len(shortlist)} 个岗位（top_n={self.settings.agent.top_n}）")
        return {"shortlist": shortlist}

    def dispatch(self, state: AgentState) -> list[Send] | str:
        """条件边：每个岗位一个并行审读任务；一个都没有就直接去出计划。"""
        if not state.shortlist:
            return "plan"
        return [
            Send(
                "review",
                ReviewInput(job=job, resume=state.resume, preferences=state.preferences),
            )
            for job in state.shortlist
        ]

    def plan(self, state: AgentState) -> dict[str, Any]:
        content = render_plan(
            state.shortlist, state.verdicts, state.model_label, state.profile_name
        )
        output = self.settings.agent.plan_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"  投递计划已写入 {output}")
        return {"plan": content}

    def apply_gate(self, state: AgentState) -> str:
        """条件边：没开 --apply、或没有过硬门槛的岗位，都在出完计划后结束。"""
        if state.apply_enabled and any(v.hard_gate_pass for v in state.verdicts):
            return "confirm"
        return END

    def confirm(self, state: AgentState) -> dict[str, Any]:
        """人工闸门：投递不可撤销，必须 interrupt 等人拍板。"""
        candidates = [
            ApplyCandidate(job_id=v.job_id, priority=v.priority, pitch=v.pitch)
            for v in state.verdicts
            if v.hard_gate_pass
        ]
        decision = interrupt(
            ConfirmRequest(
                question="以下岗位通过硬门槛，回复要投递的 job_id 列表（空列表 = 全部放弃）",
                candidates=candidates,
                plan_output=str(self.settings.agent.plan_output),
            )
        )
        allowed = {c.job_id for c in candidates}
        approved = [int(j) for j in (decision or []) if int(j) in allowed]
        return {"approved_ids": approved}

    def apply(self, state: AgentState) -> dict[str, Any]:
        if not state.approved_ids:
            print("  没有确认投递的岗位，跳过投递。")
            return {"applied": []}
        service = ApplyService(
            self.ctx.client(), self.ctx.jobs, self.ctx.applications, on_progress=_print_progress
        )
        summary = service.run(state.approved_ids)
        return {
            "applied": [
                AppliedResult(job_id=o.jobId, status=o.status, message=o.message)
                for o in summary.outcomes
            ]
        }

    # -------------------------------------------------------------- 判断节点

    def review(self, payload: ReviewInput) -> dict[str, Any]:
        """审读单个岗位。异常降级成「审读失败」裁决——单条失败不拖垮整批，
        checkpoint 里也留得下记录。"""
        job = payload.job
        try:
            verdict: JDVerdict = self._review_llm.invoke(
                [
                    ("system", self._review_system),
                    ("user", review_user_message(payload.resume, payload.preferences, job)),
                ]
            )
            # job_id 以载荷为准，不信任模型回显
            verdict = verdict.model_copy(update={"job_id": job.job_id})
        except JobAgentError:
            raise
        except Exception as exc:  # 网络/限流/schema 均可能，逐条兜底
            logger.warning("岗位 %s 审读失败：%s", job.job_id, exc)
            verdict = JDVerdict(
                job_id=job.job_id,
                hard_gate_pass=False,
                gate_reasons=[f"审读失败，未获得裁决：{exc}"],
                priority=1,
                pitch="",
                risks=["本条是失败占位，重跑同一 thread 可补审"],
            )
        return {"verdicts": [verdict]}
