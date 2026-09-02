"""agent 路线里的确定性部分：读档案、分诊、渲染计划。

全部是纯函数 + 共享内核调用，不 import langgraph、不碰 LLM——
没装 agent extra 也能单测。判断类逻辑（读 JD 比硬门槛）在 nodes.py 的审读节点里。
"""

from __future__ import annotations

from job_agent.agent.state import JDVerdict, ShortlistJob
from job_agent.config import Settings
from job_agent.context import AppContext
from job_agent.core.analysis import AnalysisRow
from job_agent.core.matching.rules import load_rules
from job_agent.core.matching.scorer import ScoredJob, rank
from job_agent.errors import ConfigError

#: 单条 JD 送审的正文上限。JD 正常几千字符，超长的多半是页面噪声，截断以控成本
JD_CHAR_LIMIT = 6000


def load_profile(settings: Settings) -> tuple[str, str]:
    """读简历与求职偏好原文。缺文件直接报错——没有档案的审读毫无意义。"""
    texts: list[str] = []
    for label, path in (
        ("简历", settings.profile.resume),
        ("求职偏好", settings.profile.preferences),
    ):
        if not path.is_file():
            raise ConfigError(
                f"{label}文件不存在：{path}\n  先在 Claude Code 里跑 `/job-init` 生成，"
                "或手工按 config/templates/ 下的模板填写。"
            )
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ConfigError(f"{label}文件是空的：{path}")
        texts.append(content)
    return texts[0], texts[1]


def build_shortlist(ctx: AppContext, top_n: int) -> list[ShortlistJob]:
    """规则分诊：读库、打分、取前 ``top_n``，转成审读节点用的载荷。

    与 ``job match`` 用的是同一套 ``load_rules`` + ``rank``，
    两条执行路线对同一份数据得到同一个 shortlist。
    """
    rules = load_rules(ctx.settings.match.rules)
    scored = rank(ctx.db, ctx.settings, rules)
    return [_payload(job) for job in scored[:top_n]]


def _payload(job: ScoredJob) -> ShortlistJob:
    return ShortlistJob(
        job_id=job.job_id,
        title=job.title,
        company=job.company,
        salary_low=job.salary_low,
        salary_high=job.salary_high,
        score=job.score,
        reasons=job.reasons(),
        concerns=job.concerns(),
        jd=_jd_text(job.row),
    )


def _jd_text(row: AnalysisRow) -> str:
    parts = [
        text.strip() for text in (row.description, row.responsibilities, row.requirements)
    ]
    # description 通常已包含职责与要求，三段拼接会重复；去掉被前文包含的段
    merged: list[str] = []
    for part in parts:
        if part and not any(part in kept for kept in merged):
            merged.append(part)
    text = "\n\n".join(merged)
    if len(text) > JD_CHAR_LIMIT:
        text = text[:JD_CHAR_LIMIT] + "\n……（超长截断）"
    return text


def render_plan(
    shortlist: list[ShortlistJob],
    verdicts: list[JDVerdict],
    model_label: str,
    profile_name: str = "",
) -> str:
    """把审读裁决渲染成投递计划 Markdown。

    排序是确定性的：先看硬门槛，再按优先级、薪资上限降序。
    LLM 只负责单岗位的裁决，跨岗位的排序不交给模型——可比性要靠代码保证。

    ``profile_name`` 与 ``model_label`` 会写进计划头部。换了 profile 就是换了
    简历与信号表，换了模型就是换了裁决口径——过两周回看这份计划，
    得能分清优先级的差异是 JD 变了、换了人，还是换了模型。
    """
    by_id = {job.job_id: job for job in shortlist}

    def _salary_high(verdict: JDVerdict) -> float:
        job = by_id.get(verdict.job_id)
        return (job.salary_high if job else None) or 0.0

    ordered = sorted(
        verdicts,
        key=lambda v: (not v.hard_gate_pass, -v.priority, -_salary_high(v)),
    )
    go = [v for v in ordered if v.hard_gate_pass]
    hold = [v for v in ordered if not v.hard_gate_pass]

    lines = [
        "# 投递计划（agent 路线生成）",
        "",
        f"审读 {len(verdicts)} 个岗位：建议投递 {len(go)} 个，暂缓 {len(hold)} 个。",
        f"profile：{profile_name or '未记录'}　审读模型：{model_label or '未记录'}",
        "薪资均为税前口径。投递前逐条核对「硬门槛比对」——裁决是模型给的，理由才可复核。",
        "",
        "## 建议投递",
        "",
    ]
    if not go:
        lines.append("（没有通过硬门槛的岗位）")
    for verdict in go:
        lines.extend(_entry(verdict, by_id.get(verdict.job_id)))
    lines.extend(["", "## 暂缓（硬门槛存疑或不过）", ""])
    if not hold:
        lines.append("（无）")
    for verdict in hold:
        lines.extend(_entry(verdict, by_id.get(verdict.job_id)))
    return "\n".join(lines).rstrip() + "\n"


def _entry(verdict: JDVerdict, job: ShortlistJob | None) -> list[str]:
    title = job.title if job else f"job {verdict.job_id}"
    company = job.company if job else "?"
    low = job.salary_low if job else None
    high = job.salary_high if job else None
    salary = f"{low or '?'}-{high or '?'} 万/年" if (low or high) else "薪资未标"
    lines = [
        f"### {title} @ {company}",
        "",
        f"- job_id：{verdict.job_id}　优先级：{verdict.priority}/5　{salary}",
        f"- 硬门槛比对：{'；'.join(verdict.gate_reasons) or '（模型未给出比对明细）'}",
    ]
    if verdict.pitch:
        lines.append(f"- 投递口径：{verdict.pitch}")
    if verdict.risks:
        lines.append(f"- 面试风险点：{'；'.join(verdict.risks)}")
    lines.append("")
    return lines
