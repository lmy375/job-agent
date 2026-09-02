"""当前配置（只读、脱敏）。

Web 端不提供改配置的接口：配置是文件，改文件比在网页上改更可靠、可进版本库、
也不会出现「网页上改了但下次 CLI 跑的是另一套」的错位。
"""

from __future__ import annotations

from fastapi import APIRouter

from job_agent.web.deps import ContextDep
from job_agent.web.schemas import ConfigResponse

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse, summary="当前生效的配置（密钥已打码）")
def get_config(context: ContextDep) -> ConfigResponse:
    settings = context.settings
    return ConfigResponse(
        # 密钥字段是 SecretStr，序列化成 JSON 时自动变 ``**********``
        settings=settings,
        paths=settings.paths(),
        reportExists=settings.report.output.is_file(),
    )
