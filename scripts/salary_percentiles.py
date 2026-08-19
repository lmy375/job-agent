#!/usr/bin/env python
"""各赛道薪资分位数。

用来回答「100 万在这条赛道是什么水位」——比中位数更有用，
因为求职时真正关心的是「我的目标价位排在什么分位」。

    uv run python scripts/salary_percentiles.py
    uv run python scripts/salary_percentiles.py --target 150
"""

from __future__ import annotations

import argparse

from job_agent.context import AppContext
from job_agent.core.analysis import analyze, quantile

PERCENTILES = (0.25, 0.5, 0.75, 0.9, 0.95)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=float, default=100.0, help="目标年薪（万元）")
    args = parser.parse_args()

    context = AppContext.create()
    data = analyze(context.db, context.settings)

    header = (
        "赛道".ljust(8)
        + "样本".rjust(6)
        + "".join(f"P{int(p * 100)}".rjust(9) for p in PERCENTILES)
        + f"{args.target:.0f}万的分位".rjust(14)
    )
    print(header)
    print("-" * 80)

    for track, info in sorted(data["tracks"].items(), key=lambda kv: -kv[1]["count"]):
        highs = sorted(row["salaryHigh"] for row in info["jobs"] if row["salaryHigh"])
        if not highs:
            continue
        cells = "".join(f"{quantile(highs, p):.0f}".rjust(9) for p in PERCENTILES)
        # 目标薪资在该赛道处于什么分位：越低越好找
        below = sum(1 for value in highs if value < args.target)
        rank = below / len(highs) * 100
        print(f"{track:<8}{len(highs):>6}{cells}{f'P{rank:.0f}':>14}")

    print(
        "\n口径：取每条职位的**年薪上限**（月薪 × 月数），"
        "已按 JD 正文去重、保留标价最高的那条。"
    )
    context.close()


if __name__ == "__main__":
    main()
