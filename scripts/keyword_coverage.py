#!/usr/bin/env python
"""每个搜索关键词的产出质量。

关注三件事：

1. **有没有撞到 120 条上限**——撞到就说明该方向的真实总量被截断了，
   得换更细的关键词再搜一轮，否则统计会系统性偏少。
2. **去重损耗**——同一份 JD 被多家猎头挂出，某些关键词的重复率特别高。
3. **赛道有没有配好**——库里出现过、但配置里没有归类的关键词会掉进「其他」，
   悄悄把赛道分布带偏（这个坑真实踩过）。

    uv run python scripts/keyword_coverage.py
"""

from __future__ import annotations

from collections import Counter

from job_agent.context import AppContext
from job_agent.core.analysis import load_rows
from job_agent.core.liepin import MAX_PAGE, PAGE_SIZE

HARD_CAP = MAX_PAGE * PAGE_SIZE


def main() -> None:
    context = AppContext.create()
    settings = context.settings

    raw_counts = {row["keyword"]: row["count"] for row in context.jobs.keyword_counts()}
    deduped = Counter(row["keyword"] for row in load_rows(context.db, settings))

    print(f"{'关键词':<16}{'入库':>6}{'有效JD':>8}{'占比':>7}  赛道      备注")
    print("-" * 78)
    unmapped: list[str] = []
    for keyword, count in sorted(raw_counts.items(), key=lambda kv: -kv[1]):
        track = settings.search.track_for_keyword(keyword)
        if track is None:
            unmapped.append(keyword)
        kept = deduped.get(keyword, 0)
        notes = []
        if count >= HARD_CAP:
            # 单次搜索最多拿 120 条；累计超过 120 说明每轮都在截断处返回、
            # 每轮还都能带回新职位，真实总量必然更多（不是「刚好 120」那种巧合）
            notes.append(f"累计已超单次上限 {HARD_CAP} 条，真实总量更多")
        if count and kept / count < 0.7:
            notes.append("去重损耗大（多为猎头重复挂出）")
        if track is None:
            notes.append("⚠️ 配置里没归类 → 会掉进「其他」")
        print(
            f"{keyword:<16}{count:>6}{kept:>8}{kept / count * 100 if count else 0:>6.0f}%"
            f"  {track or '未归类':<8}  {'；'.join(notes)}"
        )

    enabled = set(settings.search.keywords)
    idle = sorted(enabled - raw_counts.keys())
    if idle:
        print(f"\n配置里启用、但库里还没有结果的关键词（没搜过或确实没命中）：{'、'.join(idle)}")
    if unmapped:
        print(
            "\n建议把这些关键词补进 config/config.toml 的 [[search.groups]]"
            "（可以 enabled = false，只用于分类兜底）：\n  " + "、".join(unmapped)
        )
    context.close()


if __name__ == "__main__":
    main()
