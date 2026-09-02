#!/usr/bin/env python
"""按赛道 / 角色打印职位名，用来肉眼核对分类正则。

**改完 ROLE_RULES 一定要跑这个。** 历史上抓到过两次误匹配，都是这么发现的：

- ``APT`` 没加词边界 → 5 个「Caption 标注岗」被算成攻防岗
- ``Web3`` 没排除 ``Web 3D`` → 渲染岗被算成 Web3 岗

赛道样本越小，单条误匹配的破坏力越大（安全赛道只有一百多条，5 条误匹配就是 4%）。

    uv run python scripts/audit_classification.py
    uv run python scripts/audit_classification.py --track 安全 --limit 0
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from job_agent.context import AppContext
from job_agent.core.analysis import AnalysisRow, load_rows
from job_agent.tracks import ALL_TRACKS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=ALL_TRACKS, help="只看某条赛道")
    parser.add_argument("--role", help="只看某个角色（子串匹配）")
    parser.add_argument("--limit", type=int, default=12, help="每个角色最多打印几条，0 为全部")
    parser.add_argument("--show-salary", action="store_true", help="同时打印薪资")
    parser.add_argument(
        "--profile", "-p", default=None, help="用哪个 profile（默认取 [profiles].default）"
    )
    args = parser.parse_args()

    context = AppContext.create(profile=args.profile)
    rows = load_rows(context.db, context.settings)

    grouped: dict[tuple[str, str], list[AnalysisRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.track, row.role)].append(row)

    for track in ALL_TRACKS:
        if args.track and track != args.track:
            continue
        roles = {k: v for k, v in grouped.items() if k[0] == track}
        if not roles:
            continue
        total = sum(len(v) for v in roles.values())
        print(f"\n{'=' * 72}\n{track}（{total} 条）\n{'=' * 72}")
        for (_, role), items in sorted(roles.items(), key=lambda kv: -len(kv[1])):
            if args.role and args.role not in role:
                continue
            print(f"\n  ▸ {role}（{len(items)} 条）")
            shown = items if args.limit == 0 else items[: args.limit]
            for row in sorted(shown, key=lambda r: -(r.salaryHigh or 0)):
                salary = f"  {row.salary:>16}" if args.show_salary else ""
                print(f"      {row.jobName[:52]:<54}{salary}  [{row.keyword}]")
            if args.limit and len(items) > args.limit:
                print(f"      …… 还有 {len(items) - args.limit} 条（--limit 0 看全部）")

    context.close()


if __name__ == "__main__":
    main()
