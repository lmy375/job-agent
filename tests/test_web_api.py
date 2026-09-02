"""Web API：路由、筛选、错误码映射、后台任务生命周期。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from conftest import make_detail, make_job
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
    context.details.upsert(make_detail(1, description=AI_JD))
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


def test_keywords_are_plain_counts(client, seeded):
    """只数条数，不带赛道——分类是分析，不在这个仓库里。"""
    keywords = client.get("/api/keywords").json()["keywords"]
    assert keywords[0]["keyword"] == "AI Agent"
    assert "track" not in keywords[0]


def test_stats_is_inventory_only(client, seeded):
    stats = client.get("/api/stats").json()
    assert stats["jobs"] == 2
    assert stats["details"] == {"ok": 1}
    assert stats["pendingDetails"] == 1

    # 赛道 / 技能分布这类市场分析已经不提供了
    assert client.get("/api/stats/tracks").status_code == 404


def test_config_masks_secrets(client):
    """接口把整棵配置树返回给前端，密钥必须是打码后的（SecretStr 自动完成）。"""
    body = client.get("/api/config").json()
    assert body["settings"]["liepin"]["accounts"]["default"]["user_token"] == "**********"
    assert "test-token" not in json.dumps(body)
    assert body["paths"]["database"].endswith("test.db")


def test_config_reports_current_profile(client):
    """一次只服务一个 profile，界面得能看出来在看谁的数据。"""
    body = client.get("/api/config").json()
    assert body["paths"]["profile"] == "test"
    for key in ("database", "resume", "profileDir"):
        assert "profiles/test" in body["paths"][key], key


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


def test_report_task_kind_is_gone(client):
    """报告任务已删除：只剩采集类任务。"""
    assert client.post("/api/tasks", json={"kind": "report"}).status_code == 422


def test_search_task_requires_token(client, context, monkeypatch):
    monkeypatch.setattr(context.settings.account, "user_token", None)
    response = client.post("/api/tasks", json={"kind": "search"})
    assert response.status_code == 400
    assert "user_token" in response.json()["detail"]


def test_task_404_and_cancel(client):
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.post("/api/tasks/nope/cancel").status_code == 404


def test_unknown_task_kind_is_422(client):
    assert client.post("/api/tasks", json={"kind": "danceoff"}).status_code == 422


def test_report_endpoint_is_gone(client):
    assert client.get("/report").status_code == 404
