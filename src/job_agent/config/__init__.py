"""配置层：把全局 ``config/config.toml`` 与 ``profiles/<名>/profile.toml``
解析成校验过的 :class:`Settings`（密钥也在里面）。

这一层不依赖 core / cli / web，只依赖 :mod:`job_agent.core.liepin.enums`
（纯枚举，用来校验搜索参数）。
"""

from __future__ import annotations

from job_agent.config.loader import (
    ENV_CONFIG,
    ENV_HOME,
    ENV_PROFILE,
    PROFILE_NAME,
    default_config_path,
    example_config_path,
    find_config_file,
    find_project_root,
    list_profiles,
    load_settings,
    profiles_root,
    resolve_profile,
    templates_dir,
)
from job_agent.config.models import (
    AgentConfig,
    ConfigPaths,
    DetailConfig,
    GlobalSettings,
    LangSmithConfig,
    LiepinAccount,
    LiepinConfig,
    LoggingConfig,
    ModelProvider,
    ProfileConfig,
    ProfilesConfig,
    ProfileSettings,
    RequireRule,
    ScoreConfig,
    SearchConfig,
    Secret,
    Settings,
    Signal,
    StorageConfig,
    WebConfig,
)

__all__ = [
    "ENV_CONFIG",
    "ENV_HOME",
    "ENV_PROFILE",
    "PROFILE_NAME",
    "AgentConfig",
    "ConfigPaths",
    "DetailConfig",
    "GlobalSettings",
    "LangSmithConfig",
    "LiepinAccount",
    "LiepinConfig",
    "LoggingConfig",
    "ModelProvider",
    "ProfileConfig",
    "ProfileSettings",
    "ProfilesConfig",
    "RequireRule",
    "ScoreConfig",
    "SearchConfig",
    "Secret",
    "Settings",
    "Signal",
    "StorageConfig",
    "WebConfig",
    "default_config_path",
    "example_config_path",
    "find_config_file",
    "find_project_root",
    "list_profiles",
    "load_settings",
    "profiles_root",
    "resolve_profile",
    "templates_dir",
]
