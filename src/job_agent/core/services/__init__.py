"""服务层：把客户端、存储、解析编排成一个个可以从 CLI / Web 调用的用例。"""

from __future__ import annotations

from job_agent.core.services.apply import ApplyOutcome, ApplyService, ApplySummary
from job_agent.core.services.detail import DetailService, DetailSummary
from job_agent.core.services.progress import Progress, ProgressEvent, ProgressHook
from job_agent.core.services.search import KeywordResult, SearchService, SearchSummary

__all__ = [
    "ApplyOutcome",
    "ApplyService",
    "ApplySummary",
    "DetailService",
    "DetailSummary",
    "KeywordResult",
    "Progress",
    "ProgressEvent",
    "ProgressHook",
    "SearchService",
    "SearchSummary",
]
