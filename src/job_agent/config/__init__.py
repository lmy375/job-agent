"""配置层：把 ``config/*.toml`` + ``config/.env`` 解析成校验过的 :class:`Settings`。

这一层不依赖 core / cli / web，只依赖 :mod:`job_agent.core.liepin.enums`
（纯枚举，用来校验搜索参数）。
"""

from __future__ import annotations

from job_agent.config.loader import (
    ENV_CONFIG,
    ENV_HOME,
    default_config_path,
    example_config_path,
    find_config_file,
    find_project_root,
    load_settings,
)
from job_agent.config.models import (
    DetailConfig,
    KeywordGroup,
    LiepinConfig,
    LoggingConfig,
    ProfileConfig,
    ReportConfig,
    SearchConfig,
    Settings,
    StorageConfig,
    WebConfig,
)

__all__ = [
    "ENV_CONFIG",
    "ENV_HOME",
    "DetailConfig",
    "KeywordGroup",
    "LiepinConfig",
    "LoggingConfig",
    "ProfileConfig",
    "ReportConfig",
    "SearchConfig",
    "Settings",
    "StorageConfig",
    "WebConfig",
    "default_config_path",
    "example_config_path",
    "find_config_file",
    "find_project_root",
    "load_settings",
]
