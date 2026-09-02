#!/usr/bin/env python
"""每个搜索关键词的产出质量。

关注两件事：

1. **有没有撞到 120 条上限**——撞到就说明该方向的真实总量被截断了，
   得换更细的关键词再搜一轮，否则采回来的只是一个随机切片。
2. **去重损耗**——同一份 JD 被多家猎头挂出，某些关键词的重复率特别高。

    uv run python scripts/keyword_coverage.py
"""

from __future__ import annotations

import argparse
from collections import Counter

from job_agent.context import AppContext
from job_agent.core.dataset import load_rows
from job_agent.core.liepin import MAX_PAGE, PAGE_SIZE

HARD_CAP = MAX_PAGE * PAGE_SIZE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", "-p", default=None, help="用哪个 profile（默认取 [profiles].default）"
    )
    args = parser.parse_args()

    context = AppContext.create(profile=args.profile)
    settings = context.settings

    raw_counts = {row.keyword: row.count for row in context.jobs.keyword_counts()}
    deduped = Counter(row.keyword for row in load_rows(context.db))

    print(f"{'关键词':<16}{'入库':>6}{'有效JD':>8}{'占比':>7}  备注")
    print("-" * 68)
    for keyword, count in sorted(raw_counts.items(), key=lambda kv: -kv[1]):
        kept = deduped.get(keyword, 0)
        notes = []
        if count >= HARD_CAP:
            # 单次搜索最多拿 120 条；累计超过 120 说明每轮都在截断处返回、
            # 每轮还都能带回新职位，真实总量必然更多（不是「刚好 120」那种巧合）
            notes.append(f"累计已超单次上限 {HARD_CAP} 条，真实总量更多")
        if count and kept / count < 0.7:
            notes.append("去重损耗大（多为猎头重复挂出）")
        print(
            f"{keyword:<16}{count:>6}{kept:>8}{kept / count * 100 if count else 0:>6.0f}%"
            f"  {'；'.join(notes)}"
        )

    enabled = set(settings.search.keywords)
    idle = sorted(enabled - raw_counts.keys())
    if idle:
        print(f"\n配置里启用、但库里还没有结果的关键词（没搜过或确实没命中）：{'、'.join(idle)}")
    context.close()


if __name__ == "__main__":
    main()
