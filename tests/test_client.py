"""猎聘客户端：错误码翻译、鉴权、重试、限速。全部用假 session，不发网络请求。"""

from __future__ import annotations

import pytest
import requests

from job_agent.core.liepin import (
    LiepinAuthError,
    LiepinClient,
    LiepinError,
    LiepinPageLimit,
    LiepinRateLimited,
    SearchJobInput,
)
from job_agent.core.liepin.ratelimit import SlidingWindowLimiter
from job_agent.errors import MissingTokenError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (str(payload) if payload else "")

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """按顺序吐出预置响应；也可以给出异常让客户端走重试。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, json or {}))
        item = self.responses.pop(0) if self.responses else FakeResponse(200, {"code": 0, "data": {}})
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def make_client(session, **kwargs):
    # 限速器给一个不会真的 sleep 的实现
    limiter = SlidingWindowLimiter(per_minute=100, clock=lambda: 0.0, sleep=lambda _s: None)
    return LiepinClient(token="t", session=session, limiter=limiter, **kwargs)


SEARCH_OK = {
    "code": 0,
    "msg": "",
    "data": {
        "list": [
            {
                "jobId": 1,
                "jobType": "2",
                "jobName": "AI Agent 工程师",
                "company": "某公司",
                "location": "北京",
                "salary": "60-80k·15薪",
                "education": "本科",
                "workYears": "5-10年",
                "industry": "软件",
            }
        ]
    },
}


def test_search_parses_jobs():
    session = FakeSession(FakeResponse(200, SEARCH_OK))
    client = make_client(session)
    result = client.search_jobs(SearchJobInput(jobName="AI Agent", page=0))
    assert [job.jobId for job in result.data.jobs] == [1]
    url, payload = session.calls[0]
    assert url.endswith("/mcp/search-job")
    # 空字段不发出去
    assert payload == {"jobName": "AI Agent", "page": 0}


def test_missing_token_rejected():
    with pytest.raises(MissingTokenError):
        LiepinClient(token="  ")


def test_401_becomes_auth_error():
    client = make_client(FakeSession(FakeResponse(401, text="<html>" + "x" * 5000)))
    with pytest.raises(LiepinAuthError) as exc:
        client.search_jobs(SearchJobInput())
    # 不要把几 KB 的 HTML 抛给用户
    assert len(str(exc.value)) < 200


def test_rate_limited_code():
    client = make_client(FakeSession(FakeResponse(200, {"code": 429001, "msg": "请求过于频繁"})))
    with pytest.raises(LiepinRateLimited):
        client.search_jobs(SearchJobInput())


def test_page_limit_is_not_rate_limit():
    """code=-1 的文案是「你查询过多，等会再查吧」，但其实只是翻页越界。"""
    client = make_client(FakeSession(FakeResponse(200, {"code": -1, "msg": "你查询过多"})))
    with pytest.raises(LiepinPageLimit):
        client.search_jobs(SearchJobInput(page=6))


def test_unknown_code_is_generic_error():
    client = make_client(FakeSession(FakeResponse(200, {"code": 500001, "msg": "服务异常"})))
    with pytest.raises(LiepinError, match="500001"):
        client.search_jobs(SearchJobInput())


def test_http_error_truncates_body():
    client = make_client(FakeSession(FakeResponse(502, text="y" * 5000)))
    with pytest.raises(LiepinError) as exc:
        client.search_jobs(SearchJobInput())
    assert len(str(exc.value)) < 300


def test_non_json_body():
    client = make_client(FakeSession(FakeResponse(200, None, text="<html>")))
    with pytest.raises(LiepinError, match="JSON"):
        client.search_jobs(SearchJobInput())


def test_network_error_is_retried_then_raises():
    session = FakeSession(
        requests.ConnectionError("boom"),
        requests.ConnectionError("boom"),
        requests.ConnectionError("boom"),
    )
    client = make_client(session)
    with pytest.raises(LiepinError, match="已重试"):
        client.search_jobs(SearchJobInput())
    assert len(session.calls) == 3


def test_network_error_then_success():
    session = FakeSession(requests.Timeout("slow"), FakeResponse(200, SEARCH_OK))
    client = make_client(session)
    assert client.search_jobs(SearchJobInput()).data.jobs[0].jobId == 1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("应聘成功", "ok"),
        ("应聘失败: 您已投递过该职位！", "already_applied"),
        ("应聘失败: 该职位已结束", "closed"),
        ("应聘失败: 其它原因", "failed"),
    ],
)
def test_apply_result_parsing(message, expected):
    """apply-job 的响应结构和 search-job 不同：errCode + data.result 中文文案。"""
    client = make_client(FakeSession(FakeResponse(200, {"errCode": 0, "data": {"result": message}})))
    result = client.apply_job(1, "2")
    assert result.status == expected
    assert result.message == message


def test_apply_rejects_bad_job_kind():
    client = make_client(FakeSession())
    with pytest.raises(ValueError, match="job_kind"):
        client.apply_job(1, "9")


def test_apply_rate_limited():
    client = make_client(FakeSession(FakeResponse(200, {"errCode": 429001})))
    with pytest.raises(LiepinRateLimited):
        client.apply_job(1, "2")


def test_limiter_waits_when_window_is_full():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = SlidingWindowLimiter(per_minute=2, clock=lambda: now[0], sleep=sleep)
    limiter.acquire()
    limiter.acquire()
    assert slept == []
    limiter.acquire()  # 第 3 次必须等窗口滑走
    assert slept and slept[0] == pytest.approx(60.1)


def test_limiter_does_not_wait_after_window_passes():
    now = [0.0]
    limiter = SlidingWindowLimiter(
        per_minute=1, clock=lambda: now[0], sleep=lambda s: pytest.fail("不该等待")
    )
    limiter.acquire()
    now[0] = 61.0
    assert limiter.acquire() == 0.0
