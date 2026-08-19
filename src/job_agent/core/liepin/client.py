"""猎聘开放接口客户端。

与旧版的区别：**客户端只负责网络**，不再顺手写数据库——
落库由 :mod:`job_agent.core.services` 决定，这样客户端可以被脚本、测试单独复用。
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Any

import requests

from job_agent.core.liepin.constants import (
    CODE_OK,
    CODE_PAGE_LIMIT,
    CODE_RATE_LIMITED,
    DEFAULT_BASE_URL,
    DEFAULT_RATE_LIMIT_PER_MIN,
    DEFAULT_TIMEOUT,
    JOB_KINDS,
)
from job_agent.core.liepin.errors import (
    LiepinAuthError,
    LiepinError,
    LiepinPageLimit,
    LiepinRateLimited,
)
from job_agent.core.liepin.models import ApplyJobResult, SearchJobInput, SearchJobResponse
from job_agent.core.liepin.ratelimit import SlidingWindowLimiter
from job_agent.errors import MissingTokenError
from job_agent.log import get_logger

if TYPE_CHECKING:  # 仅类型注解需要；运行时导入会与 config 层形成循环
    from job_agent.config import Settings

logger = get_logger(__name__)

#: 网络层错误（连接重置 / 超时）的重试次数。业务错误码一律不重试。
NETWORK_RETRIES = 2
_ERROR_BODY_LIMIT = 200  # 非 JSON 的错误页可能有数 KB，截断后再放进异常消息


class LiepinClient:
    """搜索与投递。线程不安全：每个线程自己建一个（限速窗口是实例级的）。"""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN,
        session: requests.Session | None = None,
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        if not (token or "").strip():
            raise MissingTokenError
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token.strip()
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._limiter = limiter or SlidingWindowLimiter(rate_limit_per_min)

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> LiepinClient:
        """按配置构造；缺 token 时抛 :class:`~job_agent.errors.MissingTokenError`。"""
        return cls(
            token=settings.require_token(),
            base_url=settings.liepin.base_url,
            timeout=settings.liepin.timeout,
            rate_limit_per_min=settings.liepin.rate_limit_per_min,
            **kwargs,
        )

    # ------------------------------------------------------------------ 接口

    def search_jobs(self, query: SearchJobInput) -> SearchJobResponse:
        """搜索职位。翻到分页上限会抛 :class:`LiepinPageLimit`（正常终止条件）。"""
        body = self._post("/mcp/search-job", query.model_dump(exclude_none=True))
        code = body.get("code")
        self._raise_for_code(code, body)
        return SearchJobResponse.model_validate(body)

    def apply_job(self, job_id: int, job_kind: str) -> ApplyJobResult:
        """投递职位。

        - ``job_kind`` 复用搜索结果里的 ``jobType``："1" 猎头职位、"2" 普通职位。
        - **响应结构和 search-job 不同**（2026-08-13 实测）：顶层是 ``errCode`` 而非
          ``code``，结果是 ``data.result`` 里的中文文案，如「应聘成功」
          「应聘失败: 您已投递过该职位！」「应聘失败: 该职位已结束」。
        - 业务失败（已投递过 / 职位已结束）不抛异常，解析进 :class:`ApplyJobResult`；
          重复投递会被服务端无害拒绝，可用来核对投递状态（猎聘没有查询投递记录的接口）。
        """
        if job_kind not in JOB_KINDS:
            raise ValueError(
                f"job_kind 必须是 '1'（猎头职位）或 '2'（普通职位），传入了 {job_kind!r}"
            )
        body = self._post("/mcp/apply-job", {"jobId": job_id, "jobKind": job_kind})
        # 防御性地兼容两种键名：apply-job 实测用 errCode，search-job 用 code
        self._raise_for_code(body.get("errCode", body.get("code")), body, page_limit=False)
        message = str((body.get("data") or {}).get("result", ""))
        return ApplyJobResult(
            ok=message.startswith("应聘成功"),
            message=message,
            already_applied="已投递" in message,
            closed="已结束" in message,
        )

    # ------------------------------------------------------------------ 内部

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_exc: requests.RequestException | None = None

        for attempt in range(1, NETWORK_RETRIES + 2):
            self._limiter.acquire()
            try:
                resp = self._session.post(
                    url,
                    headers={"x-user-token": self._token},
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("请求 %s 失败（第 %d 次）：%s", path, attempt, exc)
                continue

            if resp.status_code == 401:
                raise LiepinAuthError
            if not resp.ok:
                raise LiepinError(
                    f"请求失败（HTTP {resp.status_code}）：{resp.text[:_ERROR_BODY_LIMIT]}"
                )
            try:
                body = resp.json()
            except ValueError as exc:
                raise LiepinError(
                    f"响应不是合法 JSON：{resp.text[:_ERROR_BODY_LIMIT]}"
                ) from exc
            if not isinstance(body, dict):
                raise LiepinError(f"响应结构异常（期望对象）：{str(body)[:_ERROR_BODY_LIMIT]}")
            return body

        raise LiepinError(f"请求失败（已重试 {NETWORK_RETRIES} 次）：{last_exc}")

    @staticmethod
    def _raise_for_code(code: Any, body: dict[str, Any], page_limit: bool = True) -> None:
        """把业务错误码翻译成异常。

        接口以 HTTP 200 + 业务 code 返回错误，不判断的话限流会被当成「没有结果」。
        """
        if code == CODE_OK:
            return
        message = body.get("msg") or body
        if code == CODE_RATE_LIMITED:
            raise LiepinRateLimited(f"触发限流（code={code}）：{message}")
        if page_limit and code == CODE_PAGE_LIMIT:
            raise LiepinPageLimit(f"分页越界（code={code}）：{message}")
        raise LiepinError(f"接口错误（code={code}）：{message}")

    # ------------------------------------------------------------ 生命周期

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> LiepinClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
