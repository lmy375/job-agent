#!/usr/bin/env python
"""终端版赛道统计：角色构成 + 各技能词在该赛道 JD 里的命中率。

    uv run python scripts/track_stats.py
    uv run python scripts/track_stats.py --top 12 --no-dedupe
"""

from __future__ import annotations

import argparse

from job_agent.context import AppContext
from job_agent.core.analysis import analyze


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=8, help="每个技能分类打印前几名")
    parser.add_argument(
        "--no-dedupe", action="store_true", help="不按 JD 正文去重（能看出猎头重复挂出的规模）"
    )
    parser.add_argument(
        "--profile", "-p", default=None, help="用哪个 profile（默认取 [profiles].default）"
    )
    args = parser.parse_args()

    context = AppContext.create(profile=args.profile)
    data = analyze(context.db, context.settings, dedupe=not args.no_dedupe)

    print(f"共 {data.total} 条有效 JD")
    for track, count in data.trackCounts.most_common():
        print(f"  {track}: {count}")

    for track, info in data.tracks.items():
        print(f"\n===== {track}（{info.count}）=====")
        print("  角色:", info.roles[:8])
        print(
            f"  薪资: 中位 {info.salaryMedianLow}–{info.salaryMedianHigh} 万"
            f" · P90 {info.salaryP90High} 万"
            f" · 真正 ≥100 万 {info.meets100}/{info.salaryParsed}"
        )
        for group, items in info.skills.items():
            top = [f"{i.name}({i.pct:.0f}%)" for i in items[: args.top] if i.count]
            if top:
                print(f"  {group}: {', '.join(top)}")

    context.close()


if __name__ == "__main__":
    main()
