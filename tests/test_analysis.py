"""分析层：JD 去重、赛道聚合、分位数。"""

from __future__ import annotations

import pytest

from conftest import make_job
from job_agent.core.analysis import analyze, jd_key, load_rows, quantile, skill_hits

AI_JD = "岗位职责：\n负责大模型 Agent 平台\n任职要求：\n熟悉 Python、LLM、RAG、智能体与模型训练"


def seed(context, jobs_and_details):
    for job, description in jobs_and_details:
        context.jobs.upsert_many([job], keyword=job.jobName and "AI Agent")
        context.details.upsert(
            {"jobId": job.jobId, "description": description, "status": "ok"}
        )


def test_load_rows_skips_failed_and_short_jd(context, settings):
    context.jobs.upsert_many([make_job(1), make_job(2), make_job(3)], keyword="AI Agent")
    context.details.upsert({"jobId": 1, "description": AI_JD, "status": "ok"})
    context.details.upsert({"jobId": 2, "description": "太短", "status": "ok"})
    context.details.upsert({"jobId": 3, "description": AI_JD, "status": "no_jd"})

    rows = load_rows(context.db, settings)
    assert [row["jobId"] for row in rows] == [1]


def test_dedupe_keeps_highest_salary_and_counts_dupes(context, settings):
    """同一份 JD 被多家猎头挂出：正文一字不差，标价各挂各的，保留最高的那条。"""
    seed(
        context,
        [
            (make_job(1, salary="40-60k·15薪"), AI_JD),
            (make_job(2, salary="80-100k·15薪"), AI_JD),
            (make_job(3, salary="50-70k·15薪"), AI_JD),
        ],
    )
    rows = load_rows(context.db, settings)
    assert len(rows) == 1
    assert rows[0]["jobId"] == 2
    assert rows[0]["dupes"] == 3


def test_dedupe_ignores_whitespace_differences(context, settings):
    seed(context, [(make_job(1), AI_JD), (make_job(2), AI_JD.replace("\n", "\n  "))])
    assert len(load_rows(context.db, settings)) == 1


def test_no_dedupe_keeps_everything(context, settings):
    seed(context, [(make_job(1), AI_JD), (make_job(2), AI_JD)])
    assert len(load_rows(context.db, settings, dedupe=False)) == 2


def test_jd_key_strips_whitespace():
    assert jd_key("a b\nc") == jd_key("ab c")


def test_analyze_aggregates_by_track(context, settings):
    seed(
        context,
        [
            (make_job(1, jobName="AI Agent 工程师", salary="80-100k·15薪"), AI_JD),
            (make_job(2, jobName="大模型算法专家", salary="60-70k·15薪"), AI_JD + " 变体"),
        ],
    )
    data = analyze(context.db, settings)
    assert data["total"] == 2
    assert data["trackCounts"]["AI"] == 2

    info = data["tracks"]["AI"]
    assert info["count"] == 2
    assert info["salaryMedianHigh"] == pytest.approx(127.5)
    assert info["meets100"] == 2
    # 技能命中率：两条 JD 都提到 Python
    python = {name: pct for name, _n, pct in info["skills"]["语言"]}
    assert python["Python"] == 100.0


def test_skill_hits_avoids_false_positives():
    """词典里几个刻意收窄过的正则，放宽就会命中率虚高。"""
    assert "Go" not in skill_hits("我们 go to market 很快").get("语言", set())
    assert "Go" in skill_hits("熟悉 Go 语言开发").get("语言", set())
    # 「对齐」在中文 JD 里常指对齐业务预期，不能算 AI 安全
    assert "AI 安全 / 对齐" not in skill_hits("需要与业务方对齐预期").get("安全技术", set())
    # 只写「合规」会把命中率虚高到 30%+，所以词典限定成了具体搭配
    assert "合规 / KYC / AML" not in skill_hits("遵守公司合规制度").get("区块链技术", set())
    assert "合规 / KYC / AML" in skill_hits("熟悉 KYC 与反洗钱流程").get("区块链技术", set())


def test_quantile():
    assert quantile([1.0], 0.9) == 1.0
    assert quantile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert quantile([1.0, 2.0], 0.5) == 1.5
    with pytest.raises(ValueError):
        quantile([], 0.5)
