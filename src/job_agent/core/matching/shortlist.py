"""候选清单骨架的渲染。

**这里刻意只写代码能确定的东西**：岗位、公司、薪资区间、
命中与扣分的信号、JD 摘录、链接。

「硬门槛对得上吗」「投不投」「怎么谈」三处一律留成待填标记——
它们需要读懂 JD 才能回答，属于 ``/job-match`` skill 的工作。
如果代码替它们填上模板话术，人会以为已经分析过了，这比留空更糟。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from job_agent.config import Settings
from job_agent.core.matching.scorer import ScoredJob

#: 留给 skill 填的标记。用同一个串，便于 skill 自检「还有几处没填」
TODO = "<待 /job-match 填写>"

_WS_RE = re.compile(r"\s+")
#: JD 摘录长度。够看清岗位在干什么，又不至于让清单长到没法读
EXCERPT_LEN = 600


def _excerpt(text: str, limit: int = EXCERPT_LEN) -> str:
    flat = _WS_RE.sub(" ", text or "").strip()
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "……"


def _salary_cell(job: ScoredJob) -> str:
    low, high = job.salary_low, job.salary_high
    if low is None or high is None:
        return job.row.get("salary") or "未标"
    return f"{low:.0f}–{high:.0f} 万"


def render_shortlist(
    jobs: Sequence[ScoredJob],
    settings: Settings,
    limit: int = 12,
    floor_wan: float | None = None,
) -> str:
    """渲染候选清单 Markdown。``jobs`` 应当已按分数排好序。"""
    selected = list(jobs[:limit])
    name = settings.profile.name or "候选人"
    threshold = floor_wan if floor_wan is not None else settings.match.salary_floor_wan

    lines: list[str] = [
        f"# 候选岗位清单 · {name} · {date.today().isoformat()}",
        "",
        f"由 `job shortlist` 生成：共 {len(jobs)} 条进入评分，取前 {len(selected)} 条。",
    ]
    if threshold is not None:
        lines.append(f"筛选门槛：薪资**上限** ≥ {threshold:.0f} 万（按上限而非下限，见下）。")
    lines += [
        "",
        "> **这份文件只有一半是自动生成的。** 岗位、薪资、命中信号由代码算出，",
        "> 可重跑、两次一样；「硬门槛核对」「投不投」「投递口径」三处标着"
        f" `{TODO}`，",
        "> 需要逐条读 JD 才能回答——跑 `/job-match` 让 Claude 填，或自己填。",
        ">",
        "> 两个必读的口径：",
        ">",
        "> - **薪资一律是税前**：JD 标的是税前，这里不做税后换算。",
        "> - **薪资按上限过滤**：JD 区间的上限才代表「这家最多给到多少」。"
        "按下限过滤会误杀「50-80k·20薪」这类实际能谈上去的岗位。",
        "",
        "---",
        "",
        "## 一览",
        "",
        "| # | 分 | 岗位 | 公司 | 年薪(万) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, job in enumerate(selected, 1):
        lines.append(
            f"| {index} | {job.score:.0f} | {job.title} | {job.company} "
            f"| {_salary_cell(job)} |"
        )

    lines += ["", "---", ""]

    for index, job in enumerate(selected, 1):
        row = job.row
        company = " · ".join(
            part
            for part in (job.company, row.get("companySize"), row.get("financingStage"))
            if part
        )
        conditions = " · ".join(
            part
            for part in (
                row.get("workYears") or "经验不限",
                row.get("education") or "学历不限",
                row.get("location"),
                row.get("industry"),
            )
            if part
        )
        lines += [
            f"## {index}. {job.title}",
            "",
            f"- **公司**：{company}",
            f"- **薪资**：{row.get('salary') or '未标'} → {_salary_cell(job)}",
            f"- **条件**：{conditions}",
            f"- **赛道 / 角色**：{row.get('track') or '—'} / {row.get('role') or '—'}"
            f" · 命中关键词「{row.get('keyword') or '—'}」",
            f"- **匹配分**：{job.score:.0f}",
        ]
        if job.hits:
            lines.append(f"- **命中信号**：{job.reasons()}")
        if job.penalties:
            lines.append(f"- **扣分信号**：{job.concerns()}")
        if (row.get("dupes") or 1) > 1:
            lines.append(
                f"- **注意**：同一份 JD 被 {row['dupes']} 家挂出（已按正文去重，保留标价最高的）"
            )
        lines += [
            f"- **链接**：{row.get('url') or '—'}",
            "",
            "<details><summary>JD 摘录</summary>",
            "",
            f"{_excerpt(row.get('description') or '')}",
            "",
            "</details>",
            "",
            f"- **硬门槛核对**：{TODO}",
            "  <!-- 逐条比 JD 的硬性要求与简历：学历、年限、带人规模、特定技术栈。"
            "对不上的直接写「差多少」，不要含糊 -->",
            f"- **投不投**：{TODO}",
            "  <!-- 投 / 观望 / 不投 + 一句话理由 -->",
            f"- **投递口径**：{TODO}",
            "  <!-- 简历里哪段最该往前放；面试大概率被追问什么；薪资怎么报 -->",
            "",
        ]

    lines += [
        "---",
        "",
        "## 未进前列但已评分的岗位",
        "",
        f"共 {max(len(jobs) - len(selected), 0)} 条。跑 `job match --top 50` 看完整排序，",
        "或调 `config/match.toml` 里的权重后重跑——**分数低不等于不合适**，",
        "只说明它和你配置的信号表重合度低。",
        "",
    ]
    return "\n".join(lines)


def write_shortlist(content: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
