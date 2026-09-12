"""匹配层：按当前 profile 的 ``[score]`` 信号表给职位分诊排序。

分工提醒——**这一层只做分诊，不下结论**：
它把几百条职位砍到几十条并给出「为什么」，
「该不该投」要读 JD：``job llm-score`` 让模型读，或人自己读。

信号表本身是配置（``profiles/<名>/profile.toml`` 的 ``[score]`` 段，
模型见 :mod:`job_agent.config.models`），这一层只负责用它。

:func:`refresh` 会把分数与排名写进 ``job_scores`` 表——``job score`` 与
``job agent`` 都走它，所以两条路线看到的永远是同一批分数。

旁边还有一层 **LLM 语义打分**（:mod:`~job_agent.core.matching.llm_scorer`）：
两个维度、各 1-10 分、各带依据，读得懂关键词读不出的语义门槛。
两套分数**并列**，不合成——谁重要由看的人决定。

两套都有了，就能拿 LLM 分当参照给信号表体检（:mod:`~job_agent.core.matching.align`，
``job align``）：哪条信号不区分好坏、哪些好岗被漏在窗口外。统计是代码，
改哪条是判断——归 ``/job-align`` skill。
"""

from __future__ import annotations

from job_agent.core.matching.align import AlignReport, AlignThresholds, align
from job_agent.core.matching.llm_scorer import (
    LlmScorer,
    LlmScoreResult,
    LlmScoreSummary,
    LlmVerdict,
    build_candidates,
    build_scorer,
)
from job_agent.core.matching.scorer import (
    Hit,
    ScoredJob,
    ScoreRefresh,
    body_text,
    refresh,
    score_all,
    score_row,
)
from job_agent.core.matching.shortlist import render_shortlist

__all__ = [
    "AlignReport",
    "AlignThresholds",
    "Hit",
    "LlmScoreResult",
    "LlmScoreSummary",
    "LlmScorer",
    "LlmVerdict",
    "ScoreRefresh",
    "ScoredJob",
    "align",
    "body_text",
    "build_candidates",
    "build_scorer",
    "refresh",
    "render_shortlist",
    "score_all",
    "score_row",
]
