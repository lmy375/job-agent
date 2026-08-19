"""SQLite 存储层：数据库句柄 + ORM 模型 + 仓储。"""

from __future__ import annotations

from job_agent.core.storage.database import Database
from job_agent.core.storage.models import ApplicationRecord, Base, JobDetailRecord, JobRecord
from job_agent.core.storage.repositories import (
    ApplicationRepository,
    DetailRepository,
    JobQuery,
    JobRepository,
)

__all__ = [
    "ApplicationRecord",
    "ApplicationRepository",
    "Base",
    "Database",
    "DetailRepository",
    "JobDetailRecord",
    "JobQuery",
    "JobRecord",
    "JobRepository",
]
