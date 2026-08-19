"""当前配置（只读、脱敏）。

Web 端不提供改配置的接口：配置是文件，改文件比在网页上改更可靠、可进版本库、
也不会出现「网页上改了但下次 CLI 跑的是另一套」的错位。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from job_agent.web.deps import ContextDep

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", summary="当前生效的配置（token 已脱敏）")
def get_config(context: ContextDep) -> dict[str, Any]:
    settings = context.settings
    data = settings.redacted()
    data["paths"] = {
        "root": str(settings.root),
        "configFile": str(settings.config_file) if settings.config_file else None,
        "database": str(settings.storage.database),
        "resume": str(settings.profile.resume),
        "preferences": str(settings.profile.preferences),
        "report": str(settings.report.output),
        "insightsDir": str(settings.report.insights_dir),
    }
    data["reportExists"] = settings.report.output.is_file()
    return data
