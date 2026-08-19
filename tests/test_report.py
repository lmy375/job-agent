"""报告渲染：素材加载、占位符替换、缺素材时的降级。"""

from __future__ import annotations

from conftest import make_job
from job_agent.core.analysis import analyze
from job_agent.core.report import build, load_insights
from job_agent.core.report.insights import MATCH_TABLE_PLACEHOLDER

AI_JD = "岗位职责：\n负责大模型 Agent 平台建设\n任职要求：\n熟悉 Python、LLM、RAG 与智能体"


def seed(context):
    for index in range(1, 4):
        context.jobs.upsert_many(
            [make_job(index, jobName=f"AI Agent 工程师{index}", salary="80-100k·15薪")],
            keyword="AI Agent",
        )
        context.details.upsert(
            {"jobId": index, "description": f"{AI_JD} 变体{index}", "status": "ok"}
        )


def test_load_insights_template(insights_dir):
    """仓库里的 insights 模板必须始终可加载——报告的文字部分全靠它。"""
    insights = load_insights(insights_dir)
    assert insights.warnings == []
    assert set(insights.tracks) == {"AI", "Web3", "安全", "后端"}
    assert insights.match_rows
    assert MATCH_TABLE_PLACEHOLDER in insights.advice


def test_missing_insights_dir_degrades_gracefully(tmp_path):
    insights = load_insights(tmp_path / "nope")
    assert insights.warnings
    assert insights.tracks == {}


def test_partial_insights_reports_warnings(tmp_path):
    (tmp_path / "ai.html").write_text("<p>只有 AI</p>", encoding="utf-8")
    insights = load_insights(tmp_path)
    assert insights.tracks["AI"] == "<p>只有 AI</p>"
    assert any("advice.html" in w for w in insights.warnings)


def test_invalid_match_level_is_skipped(tmp_path):
    (tmp_path / "match-matrix.toml").write_text(
        '[[row]]\ncapability = "x"\nlevel = "unknown"\ndemand = "d"\nresume = "r"\n',
        encoding="utf-8",
    )
    insights = load_insights(tmp_path)
    assert insights.match_rows == []
    assert any("level" in w for w in insights.warnings)


def test_build_report(context, settings, insights_dir):
    seed(context)
    data = analyze(context.db, settings)
    path = build(data, settings, insights=load_insights(insights_dir))

    assert path == settings.report.output
    html = path.read_text(encoding="utf-8")
    assert MATCH_TABLE_PLACEHOLDER not in html  # 占位符必须被替换掉
    assert "北京" in html and "年薪 100 万+" in html
    assert "测试用户" in html  # 用配置里的名字，不写死
    assert "<style>" in html and "</html>" in html
    assert 'id="track-AI"' in html


def test_build_report_without_insights(context, settings):
    seed(context)
    data = analyze(context.db, settings)
    path = build(data, settings)
    html = path.read_text(encoding="utf-8")
    # 定量部分照样出，只是页首多一行素材提示
    assert 'id="overview"' in html
    assert "素材提示" in html


def test_report_output_can_be_overridden(context, settings, tmp_path, insights_dir):
    seed(context)
    data = analyze(context.db, settings)
    target = tmp_path / "sub" / "custom.html"
    path = build(data, settings, output=target, insights=load_insights(insights_dir))
    assert path == target
    assert target.is_file()
