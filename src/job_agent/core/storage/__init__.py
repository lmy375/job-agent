"""SQLite 存储层：数据库句柄 + ORM 模型 + 仓储 + 行模型。"""

from __future__ import annotations

from job_agent.core.storage.database import Database
from job_agent.core.storage.models import (
    ApplicationRecord,
    Base,
    JobDetailRecord,
    JobRecord,
    JobScoreRecord,
    LlmScoreRecord,
)
from job_agent.core.storage.repositories import (
    ApplicationRepository,
    DetailRepository,
    JobQuery,
    JobRepository,
    LlmScoreRepository,
    ScoreRepository,
)
from job_agent.core.storage.rows import (
    ApplicationRow,
    JobBundle,
    JobDetailRow,
    JobRow,
    KeywordCount,
    LlmScoreEntry,
    LlmScoreStatus,
    PendingDetail,
    SalarySummary,
    ScoreEntry,
    ScoreStatus,
)

__all__ = [
    "ApplicationRecord",
    "ApplicationRepository",
    "ApplicationRow",
    "Base",
    "Database",
    "DetailRepository",
    "JobBundle",
    "JobDetailRecord",
    "JobDetailRow",
    "JobQuery",
    "JobRecord",
    "JobRepository",
    "JobRow",
    "JobScoreRecord",
    "KeywordCount",
    "LlmScoreEntry",
    "LlmScoreRecord",
    "LlmScoreRepository",
    "LlmScoreStatus",
    "PendingDetail",
    "SalarySummary",
    "ScoreEntry",
    "ScoreRepository",
    "ScoreStatus",
]
