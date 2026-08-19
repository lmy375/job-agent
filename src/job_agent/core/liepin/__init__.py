"""猎聘开放接口客户端。"""

from __future__ import annotations

from job_agent.core.liepin.client import LiepinClient
from job_agent.core.liepin.constants import MAX_PAGE, PAGE_SIZE
from job_agent.core.liepin.enums import EduLevel, SalaryKind, WorkExperience
from job_agent.core.liepin.errors import (
    LiepinAuthError,
    LiepinError,
    LiepinPageLimit,
    LiepinRateLimited,
)
from job_agent.core.liepin.models import ApplyJobResult, Job, SearchJobInput, SearchJobResponse

__all__ = [
    "MAX_PAGE",
    "PAGE_SIZE",
    "ApplyJobResult",
    "EduLevel",
    "Job",
    "LiepinAuthError",
    "LiepinClient",
    "LiepinError",
    "LiepinPageLimit",
    "LiepinRateLimited",
    "SalaryKind",
    "SearchJobInput",
    "SearchJobResponse",
    "WorkExperience",
]
