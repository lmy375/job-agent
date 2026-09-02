"""猎聘接口的错误类型。

区分它们不是洁癖：``LiepinPageLimit`` 是正常的翻页终止条件，
而 ``LiepinRateLimited`` 必须中止整批采集——服务端文案却极像，
混在一起会把「被限流」误读成「这个方向没有职位」。
"""

from __future__ import annotations

from job_agent.core.liepin.constants import TOKEN_HELP_URL
from job_agent.errors import JobAgentError


class LiepinError(JobAgentError):
    """接口调用失败（网络错误、HTTP 非 2xx、未知业务码）。"""

    exit_code = 5


class LiepinRateLimited(LiepinError):  # noqa: N818 - 名字读起来就是状态，比 ...Error 更贴切
    """触发服务端限流（code=429001）。

    冷却 20 分钟以上，期间任何请求都会被拒，且失败是静默的。
    调用方碰到它就该中止整批采集：继续换关键词只会全部失败。
    限流按 token 记账（鉴权在网关层、业务层之前），换 IP 无效。
    """

    exit_code = 6


class LiepinAuthError(LiepinError):
    """token 无效或已过期。

    实测无效/缺失 token 时网关直接返回 HTTP 401 + 一整页 HTML（约 4.9KB，非 JSON），
    必须单独拦掉，否则错误信息里会是一大坨 HTML。
    """

    exit_code = 2

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or f"token 无效或已过期，请前往 {TOKEN_HELP_URL} 重新生成，"
            "并更新 config/config.toml 里 [liepin] 的 user_token"
        )


class LiepinPageLimit(LiepinError):  # noqa: N818 - 它是正常的翻页终止条件，不是错误
    """分页越界（code=-1，page >= MAX_PAGE）。

    属于正常的翻页终止条件，不是限流——服务端文案是「你查询过多，等会再查吧」，
    和限流的措辞极像但含义完全不同。
    """
