"""存储层：去重写入、筛选分页、投递记录、老库迁移。"""

from __future__ import annotations

import sqlite3

from conftest import make_job
from job_agent.core.storage import Database, JobQuery, JobRepository


def test_upsert_dedupes_by_job_id(context):
    jobs = [make_job(1), make_job(2)]
    assert context.jobs.upsert_many(jobs, keyword="AI Agent") == 2
    # 同一批再写一次不应新增
    assert context.jobs.upsert_many(jobs, keyword="大模型") == 0
    assert context.jobs.count() == 2


def test_first_keyword_wins(context):
    """searchKeyword 必须保持「最先命中它的方向」，否则分类兜底会失真。"""
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    context.jobs.upsert_many([make_job(1)], keyword="安全专家")
    assert context.jobs.get(1)["searchKeyword"] == "AI Agent"


def test_salary_band_computed_on_write(context):
    context.jobs.upsert_many([make_job(1, salary="60-80k·15薪")], keyword="AI Agent")
    row = context.jobs.get(1)
    assert row["salaryLowWan"] == 90.0
    assert row["salaryHighWan"] == 120.0


def test_salary_band_none_when_unparseable(context):
    context.jobs.upsert_many([make_job(1, salary="面议")], keyword="AI Agent")
    assert context.jobs.get(1)["salaryHighWan"] is None


def test_list_filters_and_pagination(context):
    context.jobs.upsert_many(
        [
            make_job(1, jobName="AI Agent 工程师", salary="60-80k·15薪"),
            make_job(2, jobName="安全专家", company="安全公司", salary="30-40k"),
            make_job(3, jobName="大模型算法", salary="100-150k·16薪"),
        ],
        keyword="AI Agent",
    )
    assert context.jobs.find(JobQuery(q="安全")).total == 1
    assert context.jobs.find(JobQuery(q="安全")).items[0]["jobId"] == 2
    assert context.jobs.find(JobQuery(min_salary=100)).total == 2

    page = context.jobs.find(JobQuery(order="salary", limit=2))
    assert page.total == 3
    assert len(page.items) == 2
    assert page.items[0]["jobId"] == 3  # 标价最高

    second = context.jobs.find(JobQuery(order="salary", limit=2, offset=2))
    assert [j["jobId"] for j in second.items] == [2]


def test_unparseable_salary_sorts_last(context):
    context.jobs.upsert_many(
        [make_job(1, salary="面议"), make_job(2, salary="30-40k")], keyword="AI Agent"
    )
    items = context.jobs.find(JobQuery(order="salary")).items
    assert [j["jobId"] for j in items] == [2, 1]


def test_limit_is_capped(context):
    query = JobQuery(limit=10**6).normalized()
    assert query.limit <= 2000


def test_missing_details_and_detail_upsert(context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    assert len(context.jobs.missing_details()) == 2

    context.details.upsert({"jobId": 1, "description": "x", "status": "ok"})
    assert [jid for jid, _ in context.jobs.missing_details()] == [2]

    context.details.upsert({"jobId": 2, "description": "", "status": "no_jd"})
    assert context.jobs.missing_details() == []
    # 失败的可以要求重跑
    assert [jid for jid, _ in context.jobs.missing_details(retry_failed=True)] == [2]
    assert context.details.status_counts() == {"ok": 1, "no_jd": 1}


def test_detail_upsert_overwrites(context):
    context.details.upsert({"jobId": 1, "description": "旧", "status": "no_jd"})
    context.details.upsert({"jobId": 1, "description": "新", "status": "ok"})
    detail = context.details.get(1)
    assert detail["description"] == "新"
    assert detail["status"] == "ok"


def test_has_detail_filter(context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    context.details.upsert({"jobId": 1, "description": "x", "status": "ok"})
    context.details.upsert({"jobId": 2, "description": "", "status": "no_jd"})
    assert [j["jobId"] for j in context.jobs.find(JobQuery(has_detail=True)).items] == [1]
    assert [j["jobId"] for j in context.jobs.find(JobQuery(has_detail=False)).items] == [2]


def test_application_records_and_applied_filter(context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    context.applications.record(1, "ok", "应聘成功")
    context.applications.record(2, "failed", "应聘失败: 其它")

    assert context.applications.applied_ids() == {1}
    assert context.applications.status_counts() == {"ok": 1, "failed": 1}
    assert [j["jobId"] for j in context.jobs.find(JobQuery(applied=True)).items] == [1]
    assert [j["jobId"] for j in context.jobs.find(JobQuery(applied=False)).items] == [2]
    # 允许同一职位多条记录（每次尝试都留痕）
    context.applications.record(1, "already_applied", "您已投递过该职位")
    assert len(context.applications.recent()) == 3


def test_get_with_detail_bundles_everything(context):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    context.details.upsert({"jobId": 1, "description": "JD 正文", "status": "ok"})
    context.applications.record(1, "ok", "应聘成功")
    bundle = context.jobs.get_with_detail(1)
    assert bundle["detail"]["description"] == "JD 正文"
    assert len(bundle["applications"]) == 1
    assert context.jobs.get_with_detail(999) is None


def test_keyword_counts_and_salary_summary(context):
    context.jobs.upsert_many([make_job(1, salary="60-80k·15薪")], keyword="AI Agent")
    context.jobs.upsert_many([make_job(2, salary="30-40k")], keyword="安全专家")
    counts = {row["keyword"]: row["count"] for row in context.jobs.keyword_counts()}
    assert counts == {"AI Agent": 1, "安全专家": 1}

    summary = context.jobs.salary_summary()
    assert summary["parsed"] == 2
    assert summary["meets100"] == 1
    assert summary["meets100Pct"] == 50.0


def test_migration_adds_columns_and_backfills(tmp_path):
    """老库（没有薪资列）升级后必须自动补列并回填，否则「按薪资排序」全是空。"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    # 老版本的 jobs 表：字段和现在一样，只缺 salaryLowWan / salaryHighWan
    conn.execute(
        'CREATE TABLE jobs ('
        '"jobId" INTEGER PRIMARY KEY, "jobType" VARCHAR, "jobName" VARCHAR, "company" VARCHAR, '
        '"location" VARCHAR, "salary" VARCHAR, "education" VARCHAR, "workYears" VARCHAR, '
        '"industry" VARCHAR, "companyTags" JSON, "financingStage" VARCHAR, '
        '"companySize" VARCHAR, "companyLogo" VARCHAR, "jobDetailUrl" VARCHAR, '
        '"searchKeyword" VARCHAR, "searchTime" DATETIME)'
    )
    conn.executemany(
        'INSERT INTO jobs ("jobId", "salary", "searchKeyword", "companyTags") VALUES (?, ?, ?, ?)',
        [(1, "60-80k·15薪", "AI Agent", "[]"), (2, "面议", "AI Agent", "[]")],
    )
    conn.commit()
    conn.close()

    db = Database(path).setup()
    rows = JobRepository(db).find(JobQuery(order="salary"))
    assert rows.items[0]["salaryHighWan"] == 120.0
    assert rows.items[1]["salaryHighWan"] is None
    db.dispose()

    # 幂等：再跑一次不该报错也不该重复回填
    Database(path).setup().dispose()
