"""统一异常体系。

CLI 只捕获 :class:`JobAgentError`，据 ``exit_code`` 决定退出码；
Web 层把它映射成 4xx/5xx。任何预期内的失败都应该抛这里的子类，
而不是让 requests / sqlalchemy 的原始异常冒到用户面前。
"""

from __future__ import annotations


class JobAgentError(Exception):
    """所有可预期错误的基类。"""

    exit_code = 1


class ConfigError(JobAgentError):
    """配置文件缺失、字段非法、路径不存在。"""

    exit_code = 2


class MissingTokenError(ConfigError):
    """没有配置猎聘 token，无法访问任何远端接口。"""

    exit_code = 2

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "缺少猎聘 token：请在 config/.env 里填写 LIEPIN_USER_TOKEN，"
            "或设置同名环境变量。token 前往 https://www.liepin.com/mcp/auth 生成。"
        )


class StorageError(JobAgentError):
    """数据库不可用或迁移失败。"""

    exit_code = 3


class ReportError(JobAgentError):
    """报告渲染失败，通常是 config/insights 下的素材缺失。"""

    exit_code = 4
