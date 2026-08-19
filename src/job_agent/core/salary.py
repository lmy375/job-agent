"""薪资文本解析。

猎聘的薪资是展示文案（「35-45k·15薪」），既要在写库时算出可排序的数值，
也要在分析时算分位数，所以放在 core 顶层给两边共用。
"""

from __future__ import annotations

import re
from typing import NamedTuple

#: 「35-45k·15薪」/「10-18k」；月数缺省按 12 薪
_SALARY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)k(?:·(\d+)薪)?", re.I)

DEFAULT_MONTHS = 12.0


class SalaryBand(NamedTuple):
    """年薪区间，单位万元。"""

    low: float
    high: float
    months: float


def parse_salary(salary: str | None) -> SalaryBand | None:
    """把「35-45k·15薪」解析为年薪区间（万元）。解析不了返回 ``None``。

    月薪 k × 月数 / 10 = 万元/年。无月数时按 12 薪。
    """
    if not salary:
        return None
    match = _SALARY_RE.search(salary)
    if not match:
        return None
    low, high = float(match.group(1)), float(match.group(2))
    months = float(match.group(3)) if match.group(3) else DEFAULT_MONTHS
    return SalaryBand(round(low * months / 10, 2), round(high * months / 10, 2), months)
