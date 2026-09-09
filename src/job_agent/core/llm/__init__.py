"""模型接入层：客户端构造 + 结构化输出适配 + LLM 打分的提示词。

两条执行路线共用（agent 路线的审读节点、CLI / Web 的 LLM 打分），
所以住在共享内核里——边界规则不许 ``cli`` / ``web`` import ``job_agent.agent``。
"""

from __future__ import annotations

from job_agent.core.llm.client import (
    bind_schema,
    build_llm,
    require_api_key,
    schema_instruction,
)
from job_agent.core.llm.prompts import (
    APPEAL_SYSTEM,
    FIT_SYSTEM,
    ScoreCandidate,
    ScorePrompts,
    load_score_prompts,
    read_prompt_file,
    score_system_message,
    score_user_message,
)

__all__ = [
    "APPEAL_SYSTEM",
    "FIT_SYSTEM",
    "ScoreCandidate",
    "ScorePrompts",
    "bind_schema",
    "build_llm",
    "load_score_prompts",
    "read_prompt_file",
    "require_api_key",
    "schema_instruction",
    "score_system_message",
    "score_user_message",
]
