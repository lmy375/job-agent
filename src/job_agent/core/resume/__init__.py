"""简历文件的文本抽取。整理成结构化 Markdown 是 skill 的事，不是代码的事。"""

from __future__ import annotations

from job_agent.core.resume.extract import (
    TEXT_SUFFIXES,
    ResumeExtractError,
    extract_text,
)

__all__ = ["TEXT_SUFFIXES", "ResumeExtractError", "extract_text"]
