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
    """当前 profile 用的猎聘账号没有 token，无法访问任何远端接口。"""

    exit_code = 2

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "缺少猎聘 token：请在 config/config.toml 的 "
            "[liepin.accounts.<账号名>] 下填写 user_token，"
            "并确认当前 profile 的 [profile].account 指的就是它"
            "（跑 job config path 看当前用的是哪个 profile）。"
            "token 前往 https://www.liepin.com/mcp/auth 生成。"
        )


class ProfileNotFoundError(ConfigError):
    """指定的 profile 不存在，或者有多个 profile 但没说用哪个。

    一个 profile = 一个用户或一种求职场景。有歧义时绝不猜：
    猜错了就是往别人的库里写数据。
    """

    exit_code = 2


class StorageError(JobAgentError):
    """数据库不可用或迁移失败。"""

    exit_code = 3
