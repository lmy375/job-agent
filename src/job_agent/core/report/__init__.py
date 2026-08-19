"""报告层：定量统计 + 人工撰写的定性素材 → 自包含 HTML。"""

from __future__ import annotations

from job_agent.core.report.insights import Insights, MatchRow, load_insights
from job_agent.core.report.renderer import build, render

__all__ = ["Insights", "MatchRow", "build", "load_insights", "render"]
