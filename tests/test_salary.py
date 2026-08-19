"""薪资与经验档位解析。"""

from __future__ import annotations

import pytest

from job_agent.core.analysis import norm_years
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("经验不限", "经验不限"),
        ("", "经验不限"),
        ("应届毕业生", "经验不限"),  # 抽不出数字，归入不限
        ("1-3年", "1-3 年"),
        ("2年以上", "1-3 年"),
        ("3-5年", "3-5 年"),
        ("7年以上", "5-10 年"),
        ("10年以上", "10 年以上"),
        ("2-8年", "1-3 年"),  # 按起始年限归档
    ],
)
def test_norm_years(text, expected):
    assert norm_years(text) == expected
