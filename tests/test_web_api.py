"""Web API：路由、筛选、错误码映射、后台任务生命周期。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from conftest import make_job
from job_agent.context import AppContext
from job_agent.core.liepin.errors import LiepinRateLimited
from job_agent.core.liepin.models import ApplyJobResult
from job_agent.web import create_app

AI_JD = "岗位职责：\n负责大模型 Agent 平台\n任职要求：\n熟悉 Python、LLM、RAG 与智能体"


@pytest.fixture
def client(context):
    app = create_app(context.settings, context)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded(context):
    context.jobs.upsert_many(
        [
            make_job(1, jobName="AI Agent 工程师", salary="80-100k·15薪"),
            make_job(2, jobName="安全专家", company="安全公司", salary="30-40k"),
        ],
        keyword="AI Agent",
    )
    context.details.upsert({"jobId": 1, "description": AI_JD, "status": "ok"})
    return context


def test_health(client, context):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["jobs"] == context.jobs.count()


def test_jobs_list_and_filters(client, seeded):
    body = client.get("/api/jobs").json()
    assert body["total"] == 2
    assert body["limit"] == 200

    assert client.get("/api/jobs", params={"q": "安全"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"min_salary": 100}).json()["total"] == 1
    assert client.get("/api/jobs", params={"has_detail": True}).json()["total"] == 1

    ordered = client.get("/api/jobs", params={"order": "salary", "limit": 1}).json()
    assert ordered["jobs"][0]["jobId"] == 1


def test_jobs_pagination(client, seeded):
    first = client.get("/api/jobs", params={"limit": 1, "offset": 0}).json()
    second = client.get("/api/jobs", params={"limit": 1, "offset": 1}).json()
    assert first["total"] == second["total"] == 2
    assert first["jobs"][0]["jobId"] != second["jobs"][0]["jobId"]


def test_invalid_query_param_is_422(client):
    assert client.get("/api/jobs", params={"limit": 99999}).status_code == 422
    assert client.get("/api/jobs", params={"order": "random"}).status_code == 422


def test_job_detail_and_404(client, seeded):
    body = client.get("/api/jobs/1").json()
    assert body["detail"]["description"] == AI_JD
    assert body["applications"] == []

    missing = client.get("/api/jobs/999")
    assert missing.status_code == 404
    assert "不在数据库" in missing.json()["detail"]


def test_keywords_include_track(client, seeded):
    keywords = client.get("/api/keywords").json()["keywords"]
    assert keywords[0]["keyword"] == "AI Agent"
    assert keywords[0]["track"] == "AI"


def test_stats_and_tracks(client, seeded):
    stats = client.get("/api/stats").json()
    assert stats["jobs"] == 2
    assert stats["details"] == {"ok": 1}
    assert stats["pendingDetails"] == 1

    tracks = client.get("/api/stats/tracks").json()
    assert tracks["total"] == 1
    assert tracks["tracks"][0]["track"] == "AI"
    # JD 全文不该被塞进统计响应里
    assert "rows" not in tracks


def test_config_is_redacted(client):
    body = client.get("/api/config").json()
    assert body["token"] in (None, "已配置")
    assert body["paths"]["database"].endswith("test.db")


def test_apply_flow(client, seeded, monkeypatch):
    called = {}

    class FakeClient:
        def apply_job(self, job_id, job_kind):
            called["args"] = (job_id, job_kind)
            return ApplyJobResult(ok=True, message="应聘成功")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(AppContext, "client", lambda _self: FakeClient())
    body = client.post("/api/jobs/1/apply", json={}).json()
    assert body["status"] == "ok"
    assert called["args"] == (1, "2")
    assert client.get("/api/applications").json()["total"] == 1
    # 投递后可以按「已投递」筛出来
    assert client.get("/api/jobs", params={"applied": True}).json()["total"] == 1


def test_apply_rate_limit_maps_to_429(client, seeded, monkeypatch):
    class RateLimitedClient:
        def apply_job(self, job_id, job_kind):
            raise LiepinRateLimited("429001")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(AppContext, "client", lambda _self: RateLimitedClient())
    response = client.post("/api/jobs/1/apply", json={})
    assert response.status_code == 429


def test_apply_unknown_job_is_400(client, monkeypatch):
    """库里没有的职位直接 400，不该先去建客户端（那样报的是「缺 token」，驴唇不对马嘴）。"""
    monkeypatch.setattr(AppContext, "client", lambda _self: pytest.fail("不该建客户端"))
    response = client.post("/api/jobs/999/apply", json={})
    assert response.status_code == 400
    assert "不在数据库" in response.json()["detail"]


def test_report_task_lifecycle(client, seeded, insights_dir):
    created = client.post("/api/tasks", json={"kind": "report"})
    assert created.status_code == 202
    task_id = created.json()["task"]["id"]

    for _ in range(50):
        task = client.get(f"/api/tasks/{task_id}").json()["task"]
        if task["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.1)

    assert task["status"] == "succeeded", task
    assert task["result"]["total"] == 1
    assert task["logs"]
    assert client.get("/api/tasks").json()["tasks"][0]["id"] == task_id


def test_report_task_fails_without_jd(client):
    created = client.post("/api/tasks", json={"kind": "report"})
    task_id = created.json()["task"]["id"]
    for _ in range(50):
        task = client.get(f"/api/tasks/{task_id}").json()["task"]
        if task["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert task["status"] == "failed"
    assert "没有可用的 JD" in task["error"]


def test_search_task_requires_token(client, context, monkeypatch):
    monkeypatch.setattr(context.settings, "token", None)
    response = client.post("/api/tasks", json={"kind": "search"})
    assert response.status_code == 400
    assert "TOKEN" in response.json()["detail"]


def test_task_404_and_cancel(client):
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.post("/api/tasks/nope/cancel").status_code == 404


def test_unknown_task_kind_is_422(client):
    assert client.post("/api/tasks", json={"kind": "danceoff"}).status_code == 422


def test_report_endpoint_404_before_generation(client):
    assert client.get("/report").status_code == 404
