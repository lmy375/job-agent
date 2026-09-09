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


def test_jobs_expose_score_and_sort_by_it(client, seeded):
    """列表要带上落库的分数与排名，并且能按分数排——前端排序就靠这两个字段。"""
    from job_agent.core.matching import refresh

    refresh(seeded.db, seeded.settings)
    body = client.get("/api/jobs", params={"order": "score"}).json()
    top = body["jobs"][0]
    assert top["score"] is not None
    assert top["scoreRank"] == 1
    # 没抓 JD 的那条打不了分，必须排在最后而不是被丢掉
    assert body["jobs"][-1]["score"] is None
    assert len(body["jobs"]) == body["total"] == 2

    only_scored = client.get("/api/jobs", params={"scored": True}).json()
    assert only_scored["total"] == 1


def test_stats_reports_score_freshness(client, seeded):
    from job_agent.core.matching import refresh

    before = client.get("/api/stats").json()["score"]
    assert before["scored"] == 0 and before["missing"] == 1

    refresh(seeded.db, seeded.settings)
    after = client.get("/api/stats").json()["score"]
    assert after["scored"] == 1 and after["missing"] == 0 and after["stale"] is False


def test_jobs_list_and_filters(client, seeded):
    body = client.get("/api/jobs").json()
    assert body["total"] == 2
    # 不分页：默认上限给满，两条全在响应里
    assert len(body["jobs"]) == 2
    assert "offset" not in body

    assert client.get("/api/jobs", params={"q": "安全"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"min_salary": 100}).json()["total"] == 1
    assert client.get("/api/jobs", params={"has_detail": True}).json()["total"] == 1

    ordered = client.get("/api/jobs", params={"order": "salary", "limit": 1}).json()
    assert ordered["jobs"][0]["jobId"] == 1


def test_jobs_truncation_is_visible(client, seeded):
    """截断了必须能看出来：total 大于返回条数，前端才有机会说出来。"""
    body = client.get("/api/jobs", params={"limit": 1}).json()
    assert body["total"] == 2
    assert len(body["jobs"]) == 1


def test_jobs_offset_no_longer_does_anything(client, seeded):
    """分页删掉了。offset 被 FastAPI 当未知参数忽略（不是报错），结果和不传一样。"""
    with_offset = client.get("/api/jobs", params={"offset": 1}).json()
    plain = client.get("/api/jobs").json()
    assert [j["jobId"] for j in with_offset["jobs"]] == [j["jobId"] for j in plain["jobs"]]


def test_invalid_query_param_is_422(client):
    assert client.get("/api/jobs", params={"limit": 10**7}).status_code == 422
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


def test_jobs_filter_by_job_type(client, context):
    """HR 岗位 / 猎头岗位得能分开看：同一个岗被几家猎头挂出是常态，标价还各不相同。"""
    context.jobs.upsert_many(
        [
            make_job(1, jobType="2", jobName="AI Agent 工程师"),
            make_job(2, jobType="1", jobName="AI Agent 工程师（猎头）"),
            make_job(3, jobType="1", jobName="大模型工程师"),
        ],
        keyword="AI Agent",
    )
    assert client.get("/api/jobs").json()["total"] == 3
    hr = client.get("/api/jobs", params={"job_type": "2"}).json()
    assert [j["jobId"] for j in hr["jobs"]] == [1]
    hunters = client.get("/api/jobs", params={"job_type": "1"}).json()
    assert sorted(j["jobId"] for j in hunters["jobs"]) == [2, 3]
    # 取值只有 1 / 2，别的当场 422 而不是静默不过滤
    assert client.get("/api/jobs", params={"job_type": "9"}).status_code == 422


def test_rescore_endpoint_matches_job_score(client, seeded):
    """页面上的「重新打分」= 命令行的 job score：同一个 refresh，同一批分数。"""
    before = client.get("/api/stats").json()["score"]
    assert before["scored"] == 0

    body = client.post("/api/scores/refresh").json()
    assert body["scored"] == 1
    assert body["unique"] == 1
    assert body["fingerprint"] == seeded.settings.score.fingerprint
    assert body["status"]["stale"] is False

    after = client.get("/api/stats").json()["score"]
    assert after["scored"] == 1 and after["missing"] == 0 and after["stale"] is False
    assert client.get("/api/jobs", params={"scored": True}).json()["total"] == 1


def test_rescore_without_signals_is_400(client, seeded, monkeypatch):
    """没有信号表时所有岗位都是 0 分，排序没有意义——拒掉而不是写一库 0。"""
    monkeypatch.setattr(seeded.settings.score, "signals", [])
    response = client.post("/api/scores/refresh")
    assert response.status_code == 400
    assert "score.signals" in response.json()["detail"]
    assert client.get("/api/stats").json()["score"]["scored"] == 0


def test_rescore_without_jd_is_400(client, context):
    """库里没有带 JD 的职位就打不了分，别报「成功打了 0 条」。"""
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    response = client.post("/api/scores/refresh")
    assert response.status_code == 400
    assert "JD" in response.json()["detail"]


def test_update_keywords_writes_the_profile_file(client, context, profile_dir):
    """页面上改关键词 = 改 profile.toml：生效的永远是文件里那份。"""
    body = client.put(
        "/api/config/keywords",
        json={"keywords": ["  Claude Code ", "AI 工程", "AI 工程", ""]},
    ).json()

    # 归一走 SearchConfig：去空白、丢空串、去重且保序
    assert body["settings"]["search"]["keywords"] == ["Claude Code", "AI 工程"]
    text = (profile_dir / "profile.toml").read_text(encoding="utf-8")
    assert "'Claude Code'" in text and "安全专家" not in text
    # 内存里的 settings 也换成了新的，不用重启服务
    assert context.settings.search.keywords == ["Claude Code", "AI 工程"]
    # 别的段没被写坏
    assert context.settings.storage.database.name == "test.db"


def test_update_score_makes_stored_scores_stale(client, seeded, profile_dir):
    """改打分逻辑不顺手重算：什么时候动全库排名得由人说，但过期必须看得出来。"""
    client.post("/api/scores/refresh")
    assert client.get("/api/stats").json()["score"]["stale"] is False

    payload = {
        "salary_floor_wan": 150.0,
        "title_multiplier": 3.0,
        "require": {"pattern": r"(?a:\bagent\b)|智能体", "penalty": -25.0},
        "signals": [{"name": "Agent", "weight": 12, "pattern": r"(?a:\bagent\b)|智能体"}],
    }
    body = client.put("/api/config/score", json=payload).json()
    assert body["settings"]["score"]["title_multiplier"] == 3.0
    assert body["settings"]["score"]["signals"][0]["weight"] == 12.0
    assert seeded.settings.score.salary_floor_wan == 150.0

    stale = client.get("/api/stats").json()["score"]
    assert stale["stale"] is True and stale["scored"] == 1

    # 再打一次就不过期了，而且用的是新权重（Agent 命中标题：12 × 3）
    client.post("/api/scores/refresh")
    assert client.get("/api/stats").json()["score"]["stale"] is False
    top = client.get("/api/jobs", params={"scored": True}).json()["jobs"][0]
    assert top["score"] == 36.0

    text = (profile_dir / "profile.toml").read_text(encoding="utf-8")
    assert "title_multiplier = 3" in text
    assert r"pattern = '(?a:\bagent\b)|智能体'" in text


def test_update_score_rejects_broken_regex(client, seeded, profile_dir):
    """正则编译不过就 422，并且**不落盘**——坏配置写进去下次连服务都起不来。"""
    before = (profile_dir / "profile.toml").read_text(encoding="utf-8")
    response = client.put(
        "/api/config/score",
        json={"signals": [{"name": "坏正则", "weight": 5, "pattern": "(未闭合"}]},
    )
    assert response.status_code == 422
    # 报错要指到具体哪条信号的哪个字段（前端把 loc 拼出来给人看），
    # 而不是笼统一句「请求失败」——几十条信号里找那个写错的正则全靠它
    problem = response.json()["detail"][0]
    assert problem["loc"] == ["body", "signals", 0, "pattern"]
    assert "不是合法正则" in problem["msg"]
    assert (profile_dir / "profile.toml").read_text(encoding="utf-8") == before
    assert seeded.settings.score.signals[0].name == "Agent"


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


# ---------------------------------------------------------------- LLM 打分


def test_llm_score_task_requires_api_key(client, seeded):
    """提交前就挡掉「跑不动」的情况：排进队列再失败，人得等一轮轮询才知道。"""
    response = client.post(
        "/api/tasks", json={"kind": "llm_score", "params": {"job_ids": [1]}}
    )
    assert response.status_code == 400
    assert "api_key" in response.json()["detail"]


def test_llm_score_task_requires_job_ids(client, seeded, monkeypatch):
    """按条计费，「不传就全打」这种默认在任何入口都不该存在。"""
    monkeypatch.setattr(
        seeded.settings.llm_score_active, "api_key", _secret("sk-test")
    )
    response = client.post("/api/tasks", json={"kind": "llm_score", "params": {}})
    assert response.status_code == 400
    assert "job_ids" in response.json()["detail"]


def test_llm_score_task_runs_and_persists(client, seeded, monkeypatch):
    """整条链路：提交任务 → 后台跑完 → 分数进库 → 列表带出来。"""
    _patch_scorer(monkeypatch)
    monkeypatch.setattr(
        seeded.settings.llm_score_active, "api_key", _secret("sk-test")
    )
    created = client.post(
        "/api/tasks", json={"kind": "llm_score", "params": {"job_ids": [1, 2]}}
    )
    assert created.status_code == 202
    task_id = created.json()["task"]["id"]

    detail = _await_task(client, task_id)
    assert detail["status"] == "succeeded"
    result = detail["result"]
    # 2 号没抓到 JD，判不了，算跳过而不是失败
    assert (result["requested"], result["scored"], result["skipped"]) == (2, 1, 1)

    job = next(j for j in client.get("/api/jobs").json()["jobs"] if j["jobId"] == 1)
    assert (job["llmAppeal"], job["llmFit"]) == (8, 6)
    assert job["llmAppealReasons"] == ["平台够大"]

    only = client.get("/api/jobs", params={"llm_scored": True}).json()
    assert [j["jobId"] for j in only["jobs"]] == [1]


def test_overview_reports_llm_coverage(client, seeded):
    body = client.get("/api/stats").json()["llmScore"]
    assert body == {
        "scorable": 1,
        "scored": 0,
        "current": 0,
        "stale": False,
        "scoredAt": None,
    }


def test_prompts_default_and_override(client, context, profile_dir):
    """内置默认也返回全文——要改就得先看见改什么。"""
    body = client.get("/api/config/prompts").json()
    assert body["appeal"]["isDefault"] is True
    assert "岗位吸引力" in body["appeal"]["content"] or body["appeal"]["content"]
    assert body["modelLabel"] == "anthropic / claude-opus-5"
    before = body["fingerprint"]

    updated = client.put(
        "/api/config/prompts",
        json={"appeal": body["appeal"]["content"], "fit": "只看学历。"},
    ).json()
    # 和内置默认逐字相同的那半不落盘：那不是「自定义」
    assert updated["appeal"]["isDefault"] is True
    assert not (profile_dir / "score_appeal.md").exists()
    assert updated["fit"]["isDefault"] is False
    assert (profile_dir / "score_fit.md").read_text(encoding="utf-8") == "只看学历。\n"
    assert updated["fingerprint"] != before


def test_prompts_empty_restores_default(client, profile_dir):
    """空串 = 删掉覆盖文件，不是「存一份空提示词」。"""
    client.put("/api/config/prompts", json={"appeal": "只看薪资。", "fit": ""})
    assert (profile_dir / "score_appeal.md").exists()

    body = client.put("/api/config/prompts", json={"appeal": "", "fit": ""}).json()
    assert body["appeal"]["isDefault"] is True
    assert not (profile_dir / "score_appeal.md").exists()


def _secret(value: str):
    from pydantic import SecretStr

    return SecretStr(value)


def _patch_scorer(monkeypatch):
    """替掉模型客户端。任务照常进队列、照常报进度，只是不发请求。"""
    from job_agent.core.matching import LlmVerdict, llm_scorer

    class FakeLLM:
        def invoke(self, messages):
            return LlmVerdict(
                appeal_score=8,
                appeal_reasons=["平台够大"],
                fit_score=6,
                fit_reasons=["经验差两年"],
            )

    real = llm_scorer.build_scorer

    def patched(settings, db, repo, on_progress=None, llm=None):
        return real(settings, db, repo, on_progress, llm or FakeLLM())

    monkeypatch.setattr("job_agent.web.routers.tasks.build_scorer", patched)


def _await_task(client, task_id: str, tries: int = 100) -> dict:
    """等后台 worker 跑完。任务在线程池里，提交立刻返回，得轮询。"""
    import time

    for _ in range(tries):
        body = client.get(f"/api/tasks/{task_id}").json()["task"]
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"任务 {task_id} 没在预期时间内结束")
