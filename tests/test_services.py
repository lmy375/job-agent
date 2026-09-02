"""服务层：搜索 / 详情 / 投递的编排逻辑（客户端与 HTTP 都是假的）。"""

from __future__ import annotations

import pytest

from conftest import ld_json_page, make_job
from job_agent.core.liepin import LiepinError, LiepinPageLimit, LiepinRateLimited
from job_agent.core.liepin.models import ApplyJobResult, SearchJobResponse
from job_agent.core.services import ApplyService, DetailService, SearchService


class FakeClient:
    """按 (关键词, 页码) 返回预置结果；也能按需抛异常。"""

    def __init__(self, pages=None, errors=None, apply_results=None):
        self.pages = pages or {}
        self.errors = errors or {}
        self.apply_results = apply_results or {}
        self.searched: list[tuple[str, int]] = []
        self.applied: list[tuple[int, str]] = []

    def search_jobs(self, query):
        key = (query.jobName, query.page)
        self.searched.append(key)
        if key in self.errors:
            raise self.errors[key]
        jobs = self.pages.get(key, [])
        return SearchJobResponse.model_validate(
            {"code": 0, "data": {"list": [job.model_dump() for job in jobs]}}
        )

    def apply_job(self, job_id, job_kind):
        self.applied.append((job_id, job_kind))
        result = self.apply_results.get(job_id)
        if isinstance(result, Exception):
            raise result
        return result or ApplyJobResult(ok=True, message="应聘成功")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


# ---------------------------------------------------------------- 搜索


def test_search_writes_jobs_and_stops_on_page_limit(settings, context):
    client = FakeClient(
        pages={("AI Agent", 0): [make_job(1), make_job(2)]},
        errors={("AI Agent", 1): LiepinPageLimit("分页越界")},
    )
    service = SearchService(settings, client, context.jobs)
    summary = service.run(keywords=["AI Agent"])

    assert summary.total_found == 2
    assert summary.total_new == 2
    assert not summary.aborted
    assert context.jobs.count() == 2
    assert context.jobs.get(1).searchKeyword == "AI Agent"


def test_search_stops_paging_on_empty_page(settings, context):
    client = FakeClient(pages={("大模型", 0): [make_job(1)]})
    service = SearchService(settings, client, context.jobs)
    service.run(keywords=["大模型"])
    # max_pages=2，第 1 页空了就停，不该继续翻
    assert client.searched == [("大模型", 0), ("大模型", 1)]


def test_rate_limit_aborts_whole_batch(settings, context):
    """限流必须中止整批，并交代清楚剩下哪些没跑——否则看起来像「这些方向没有职位」。"""
    client = FakeClient(
        pages={("AI Agent", 0): [make_job(1)]},
        errors={("大模型", 0): LiepinRateLimited("429001")},
    )
    service = SearchService(settings, client, context.jobs)
    summary = service.run(keywords=["AI Agent", "大模型", "安全专家"])

    assert summary.aborted
    assert "限流" in summary.aborted_reason
    assert summary.remaining == ["大模型", "安全专家"]
    assert ("安全专家", 0) not in client.searched


def test_other_errors_only_skip_that_keyword(settings, context):
    client = FakeClient(
        errors={("AI Agent", 0): LiepinError("接口错误")},
        pages={("大模型", 0): [make_job(9)]},
    )
    service = SearchService(settings, client, context.jobs)
    summary = service.run(keywords=["AI Agent", "大模型"])
    assert not summary.aborted
    assert summary.results[0].error
    assert summary.total_new == 1


def test_truncated_flag(settings, context):
    """命中数撞到 max_pages × 20 说明真实总量被服务端截断了。"""
    page0 = [make_job(i) for i in range(1, 21)]
    page1 = [make_job(i) for i in range(21, 41)]
    client = FakeClient(pages={("AI Agent", 0): page0, ("AI Agent", 1): page1})
    service = SearchService(settings, client, context.jobs)
    summary = service.run(keywords=["AI Agent"])
    assert summary.results[0].truncated


def test_search_can_be_cancelled(settings, context):
    client = FakeClient(pages={("AI Agent", 0): [make_job(1)]})
    service = SearchService(settings, client, context.jobs)
    summary = service.run(keywords=["AI Agent", "大模型"], stop_check=lambda: True)
    assert summary.aborted_reason == "已取消"
    assert client.searched == []


def test_search_without_configured_keywords_is_a_noop(settings, context):
    """一个关键词都没启用时要明确提示，而不是静默什么都不做。"""
    empty = settings.model_copy(deep=True)
    empty.search.keywords = []
    events = []
    service = SearchService(empty, FakeClient(), context.jobs, events.append)
    summary = service.run()
    assert summary.results == []
    assert any("关键词" in event.message for event in events)


def test_empty_keyword_list_falls_back_to_config(settings, context):
    """传空列表（比如页面上没填）按「用配置里的全部」处理。"""
    client = FakeClient()
    summary = SearchService(settings, client, context.jobs).run(keywords=[])
    assert [r.keyword for r in summary.results] == settings.search.keywords


def test_progress_events_are_emitted(settings, context):
    events = []
    client = FakeClient(pages={("AI Agent", 0): [make_job(1)]})
    SearchService(settings, client, context.jobs, events.append).run(keywords=["AI Agent"])
    assert events[0].total == 1
    assert events[-1].percent == 100.0


# ---------------------------------------------------------------- 详情


class FakeHttpSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.headers: dict[str, str] = {}
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        item = self.responses.pop(0) if self.responses else _Resp(200, "<html></html>")
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300


def make_detail_service(settings, context, session):
    return DetailService(
        settings, context.jobs, context.details, session=session, sleeper=lambda _s: None
    )


def test_detail_fetch_and_persist(settings, context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    session = FakeHttpSession(_Resp(200, ld_json_page()), _Resp(200, ld_json_page()))
    summary = make_detail_service(settings, context, session).run()

    assert summary.total == 2
    assert summary.statuses["ok"] == 2
    assert "Agent 平台建设" in context.details.get(1).responsibilities


def test_detail_marks_no_jd_and_http_error(settings, context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    session = FakeHttpSession(_Resp(200, "<html>已下线</html>"), _Resp(404, "not found"))
    summary = make_detail_service(settings, context, session).run()
    assert summary.statuses["no_jd"] == 1
    assert summary.statuses["http_404"] == 1


def test_detail_retries_then_gives_up(settings, context):
    import requests

    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    session = FakeHttpSession(requests.ConnectionError("x"), requests.ConnectionError("x"))
    summary = make_detail_service(settings, context, session).run()
    assert summary.statuses["error:ConnectionError"] == 1


def test_detail_backs_off_on_403_then_gives_up(settings, context):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    session = FakeHttpSession(_Resp(403, ""), _Resp(429, ""))
    summary = make_detail_service(settings, context, session).run()
    assert summary.statuses["blocked"] == 1


def test_detail_limit_and_resume(settings, context):
    context.jobs.upsert_many([make_job(1), make_job(2), make_job(3)], keyword="AI Agent")
    session = FakeHttpSession(_Resp(200, ld_json_page()))
    summary = make_detail_service(settings, context, session).run(limit=1)
    assert summary.total == 1
    # 剩下的还在待抓列表里（进度落库，可续跑）
    assert len(context.jobs.missing_details()) == 2


def test_detail_cancellation_keeps_progress(settings, context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    session = FakeHttpSession(_Resp(200, ld_json_page()))
    summary = make_detail_service(settings, context, session).run(stop_check=lambda: True)
    assert summary.aborted_reason == "已取消"
    assert summary.fetched == 0


# ---------------------------------------------------------------- 投递


def test_apply_records_outcomes(context):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    client = FakeClient(apply_results={1: ApplyJobResult(ok=True, message="应聘成功")})
    summary = ApplyService(client, context.jobs, context.applications).run([1])

    assert summary.succeeded == 1
    assert client.applied == [(1, "2")]  # jobKind 取库里的 jobType
    assert context.applications.applied_ids() == {1}


def test_apply_skips_unknown_job_without_kind(context):
    client = FakeClient()
    summary = ApplyService(client, context.jobs, context.applications).run([999])
    assert summary.outcomes[0].status == "skipped"
    assert client.applied == []


def test_apply_uses_explicit_kind_for_unknown_job(context):
    client = FakeClient()
    ApplyService(client, context.jobs, context.applications).run([999], job_kind="1")
    assert client.applied == [(999, "1")]


def test_apply_already_applied_is_recorded_not_raised(context):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    client = FakeClient(
        apply_results={
            1: ApplyJobResult(
                ok=False, message="应聘失败: 您已投递过该职位！", already_applied=True
            )
        }
    )
    summary = ApplyService(client, context.jobs, context.applications).run([1])
    assert summary.succeeded == 0
    assert context.applications.status_counts() == {"already_applied": 1}


def test_apply_aborts_on_rate_limit(context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    client = FakeClient(apply_results={1: LiepinRateLimited("429001")})
    summary = ApplyService(client, context.jobs, context.applications).run([1, 2])
    assert summary.aborted
    assert summary.remaining == [1, 2]
    assert client.applied == [(1, "2")]  # 第二个没有再试


def test_apply_rejects_bad_kind(context):
    with pytest.raises(ValueError, match="job_kind"):
        ApplyService(FakeClient(), context.jobs, context.applications).run([1], job_kind="7")
