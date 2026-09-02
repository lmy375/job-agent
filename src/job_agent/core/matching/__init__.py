"""匹配层：按当前 profile 的 ``match.toml`` 信号表给职位分诊排序。

分工提醒——**这一层只做分诊，不下结论**：
它把几百条职位砍到几十条并给出「为什么」，
「该不该投」由 ``/job-match`` skill 读 JD 后判断。
"""

from __future__ import annotations

from job_agent.core.matching.rules import (
    MatchRules,
    Options,
    RequireRule,
    Signal,
    load_rules,
)
from job_agent.core.matching.scorer import (
    Hit,
    ScoredJob,
    rank,
    score_row,
)
from job_agent.core.matching.shortlist import render_shortlist

__all__ = [
    "Hit",
    "MatchRules",
    "Options",
    "RequireRule",
    "ScoredJob",
    "Signal",
    "load_rules",
    "rank",
    "render_shortlist",
    "score_row",
]
