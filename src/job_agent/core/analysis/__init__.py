"""分析层：赛道 / 角色分类、技能词频、薪资与经验分布统计。"""

from __future__ import annotations

from job_agent.core.analysis.classify import YEARS_ORDER, classify, norm_years
from job_agent.core.analysis.dataset import jd_key, load_rows
from job_agent.core.analysis.rules import ROLE_RULES, TRACK_SIGNALS, signal_count
from job_agent.core.analysis.skills import SKILLS, skill_hits
from job_agent.core.analysis.stats import analyze, analyze_rows, quantile

__all__ = [
    "ROLE_RULES",
    "SKILLS",
    "TRACK_SIGNALS",
    "YEARS_ORDER",
    "analyze",
    "analyze_rows",
    "classify",
    "jd_key",
    "load_rows",
    "norm_years",
    "quantile",
    "signal_count",
    "skill_hits",
]
