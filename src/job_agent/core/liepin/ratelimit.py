"""客户端侧滑动窗口限速。

服务端限流一旦触发就要冷却 20 分钟以上，所以宁可自己先慢下来。
时钟与休眠函数都可注入，测试里不需要真的 sleep。
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from job_agent.log import get_logger

logger = get_logger(__name__)


class SlidingWindowLimiter:
    """保证任意 60 秒窗口内不超过 ``per_minute`` 次调用。"""

    def __init__(
        self,
        per_minute: int,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if per_minute < 1:
            raise ValueError("per_minute 必须 >= 1")
        self.per_minute = per_minute
        self.window = window
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()

    def acquire(self) -> float:
        """占用一个配额，必要时阻塞。返回实际等待的秒数（便于观测）。"""
        waited = 0.0
        now = self._clock()
        self._evict(now)
        if len(self._calls) >= self.per_minute:
            waited = self.window - (now - self._calls[0]) + 0.1
            if waited > 0:
                logger.debug("本地限速：等待 %.1fs 后继续", waited)
                self._sleep(waited)
                now = self._clock()
                self._evict(now)
        self._calls.append(now)
        return max(waited, 0.0)

    def _evict(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self.window:
            self._calls.popleft()
