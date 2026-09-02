"""薪资与经验档位解析。"""

from __future__ import annotations

import pytest

from job_agent.core.salary import parse_salary


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("35-45k·15薪", 52.5, 67.5),
        ("10-18k", 12.0, 21.6),  # 没写月数按 12 薪
        ("60-80k·15薪", 90.0, 120.0),
        ("200-400k·30薪", 600.0, 1200.0),  # 猎头把多个岗位打包挂出的异常标价
        ("1.5-2.5k", 1.8, 3.0),
    ],
)
def test_parse_salary(text, low, high):
    band = parse_salary(text)
    assert band is not None
    assert band.low == pytest.approx(low)
    assert band.high == pytest.approx(high)


@pytest.mark.parametrize("text", ["面议", "", None, "薪资保密", "20k"])
def test_parse_salary_unparseable(text):
    assert parse_salary(text) is None
