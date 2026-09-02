"""存储层：去重写入、筛选分页、投递记录、删库重建。"""

from __future__ import annotations

from conftest import make_detail, make_job
from job_agent.core.storage import JobQuery
from job_agent.core.storage.repositories import MAX_ROWS


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
    assert context.jobs.get(1).searchKeyword == "AI Agent"


def test_salary_band_computed_on_write(context):
    context.jobs.upsert_many([make_job(1, salary="60-80k·15薪")], keyword="AI Agent")
    row = context.jobs.get(1)
    assert row.salaryLowWan == 90.0
    assert row.salaryHighWan == 120.0


def test_salary_band_none_when_unparseable(context):
    context.jobs.upsert_many([make_job(1, salary="面议")], keyword="AI Agent")
    assert context.jobs.get(1).salaryHighWan is None


def test_list_filters_and_limit(context):
    context.jobs.upsert_many(
        [
            make_job(1, jobName="AI Agent 工程师", salary="60-80k·15薪"),
            make_job(2, jobName="安全专家", company="安全公司", salary="30-40k"),
            make_job(3, jobName="大模型算法", salary="100-150k·16薪"),
        ],
        keyword="AI Agent",
    )
    assert context.jobs.find(JobQuery(q="安全")).total == 1
    assert context.jobs.find(JobQuery(q="安全")).items[0].jobId == 2
    assert context.jobs.find(JobQuery(min_salary=100)).total == 2

    page = context.jobs.find(JobQuery(order="salary", limit=2))
    assert page.total == 3
    # 不分页，但 limit 仍然是兜底上限：截断时 total 大于返回条数，调用方能看出来
    assert len(page.items) == 2
    assert page.items[0].jobId == 3  # 标价最高

    # 不给 limit 就是全给：默认上限远大于任何本地库的规模
    everything = context.jobs.find(JobQuery(order="salary"))
    assert [j.jobId for j in everything.items] == [3, 1, 2]


def test_unparseable_salary_sorts_last(context):
    context.jobs.upsert_many(
        [make_job(1, salary="面议"), make_job(2, salary="30-40k")], keyword="AI Agent"
    )
    items = context.jobs.find(JobQuery(order="salary")).items
    assert [j.jobId for j in items] == [2, 1]


def test_limit_is_capped():
    """limit 在构造时就夹到合法区间，调用方不需要记得再归一一次。"""
    assert JobQuery(limit=10**6).limit == MAX_ROWS
    assert JobQuery(limit=0).limit == 1
    # 默认给满：不分页，一次全给
    assert JobQuery().limit == MAX_ROWS
    # 空白关键词等于没填，不该变成「搜一个空串」
    assert JobQuery(keyword="  ", q="  ").keyword is None


def test_missing_details_and_detail_upsert(context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    assert len(context.jobs.missing_details()) == 2

    context.details.upsert(make_detail(1, description="x"))
    assert [row.jobId for row in context.jobs.missing_details()] == [2]

    context.details.upsert(make_detail(2, status="no_jd"))
    assert context.jobs.missing_details() == []
    # 失败的可以要求重跑
    assert [row.jobId for row in context.jobs.missing_details(retry_failed=True)] == [2]
    assert context.details.status_counts() == {"ok": 1, "no_jd": 1}


def test_detail_upsert_overwrites(context):
    context.details.upsert(make_detail(1, status="no_jd", description="旧"))
    context.details.upsert(make_detail(1, description="新"))
    detail = context.details.get(1)
    assert detail.description == "新"
    assert detail.status == "ok"


def test_has_detail_filter(context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    context.details.upsert(make_detail(1, description="x"))
    context.details.upsert(make_detail(2, status="no_jd"))
    assert [j.jobId for j in context.jobs.find(JobQuery(has_detail=True)).items] == [1]
    assert [j.jobId for j in context.jobs.find(JobQuery(has_detail=False)).items] == [2]


def test_application_records_and_applied_filter(context):
    context.jobs.upsert_many([make_job(1), make_job(2)], keyword="AI Agent")
    context.applications.record(1, "ok", "应聘成功")
    context.applications.record(2, "failed", "应聘失败: 其它")

    assert context.applications.applied_ids() == {1}
    assert context.applications.status_counts() == {"ok": 1, "failed": 1}
    assert [j.jobId for j in context.jobs.find(JobQuery(applied=True)).items] == [1]
    assert [j.jobId for j in context.jobs.find(JobQuery(applied=False)).items] == [2]
    # 允许同一职位多条记录（每次尝试都留痕）
    context.applications.record(1, "already_applied", "您已投递过该职位")
    assert len(context.applications.recent()) == 3


def test_get_with_detail_bundles_everything(context):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    context.details.upsert(make_detail(1, description="JD 正文"))
    context.applications.record(1, "ok", "应聘成功")
    bundle = context.jobs.get_with_detail(1)
    assert bundle.detail.description == "JD 正文"
    assert len(bundle.applications) == 1
    assert context.jobs.get_with_detail(999) is None


def test_keyword_counts_and_salary_summary(context):
    context.jobs.upsert_many([make_job(1, salary="60-80k·15薪")], keyword="AI Agent")
    context.jobs.upsert_many([make_job(2, salary="30-40k")], keyword="安全专家")
    counts = {row.keyword: row.count for row in context.jobs.keyword_counts()}
    assert counts == {"AI Agent": 1, "安全专家": 1}

    # 门槛由调用方传入——「多少算达标」因人而异，不写死在仓储里
    summary = context.jobs.salary_summary(floor_wan=100)
    assert summary.parsed == 2
    assert summary.floorWan == 100
    assert summary.meetsFloor == 1
    assert summary.meetsFloorPct == 50.0

    # 没给门槛就只报可解析条数与均值，不假装有个达标线
    plain = context.jobs.salary_summary()
    assert plain.parsed == 2
    assert plain.floorWan is None
    assert plain.meetsFloor == 0


def test_reset_drops_and_recreates(context):
    """`job db reset` 的底座：删文件重建，旧数据一条不留，之后照常能写。"""
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    context.details.upsert(make_detail(1, description="JD"))
    context.applications.record(1, "ok", "应聘成功")
    path = context.settings.storage.database
    assert path.is_file()

    removed = context.db.drop()
    assert path in removed
    assert not path.is_file()

    context.db.setup()
    assert context.jobs.count() == 0
    assert context.applications.status_counts() == {}
    context.jobs.upsert_many([make_job(2)], keyword="AI Agent")
    assert context.jobs.count() == 1
