"""详情页解析。"""

from __future__ import annotations

from conftest import ld_json_page
from job_agent.core.jd_parser import parse_detail, split_jd


def test_parse_ld_json():
    detail = parse_detail(ld_json_page())
    assert detail is not None
    assert detail["title"] == "AI Agent 工程师"
    assert detail["companyName"] == "某公司"
    assert detail["industry"] == "计算机软件"
    assert detail["experienceRequirements"] == "5-10年"
    assert detail["streetAddress"] == "海淀区"
    assert "Agent 平台建设" in detail["responsibilities"]
    assert "Python" in detail["requirements"]


def test_parse_tolerates_raw_newlines_in_json():
    """JD 字符串里含裸换行，标准 JSON 不允许，必须 strict=False 才解析得出来。"""
    html = (
        '<script type="application/ld+json">'
        '{"@type":"JobPosting","title":"x","description":"第一行\n第二行"}'
        "</script>"
    )
    detail = parse_detail(html)
    assert detail is not None
    assert "第二行" in detail["description"]


def test_parse_skips_non_jobposting_blocks():
    html = (
        '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>'
        + ld_json_page(title="真正的职位")
    )
    detail = parse_detail(html)
    assert detail is not None
    assert detail["title"] == "真正的职位"


def test_fallback_to_job_intro_node():
    html = '<dd data-selector="job-intro-content"><p>岗位职责：写代码</p></dd>'
    detail = parse_detail(html)
    assert detail is not None
    assert detail["description"] == "岗位职责：写代码"
    assert detail["title"] == ""


def test_parse_returns_none_when_page_has_nothing():
    assert parse_detail("<html><body>职位已下线</body></html>") is None


def test_split_jd_picks_earliest_requirement_heading():
    text = "岗位职责：\n做事\n任职要求：\n会做\n技能要求：\n还要会别的"
    responsibilities, requirements = split_jd(text)
    assert responsibilities == "做事"
    assert requirements.startswith("任职要求")


def test_split_jd_without_heading():
    assert split_jd("就是一段没有小标题的描述") == ("", "")
