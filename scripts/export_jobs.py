#!/usr/bin/env python
"""导出职位数据（CSV / JSON），丢给 Excel 或别的工具用。

    uv run python scripts/export_jobs.py --format csv -o data/jobs.csv
    uv run python scripts/export_jobs.py --format json --with-jd -o data/jobs.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from job_agent.context import AppContext
from job_agent.core.analysis import load_rows
from job_agent.core.storage import JobQuery
from job_agent.core.storage.repositories import MAX_PAGE_SIZE

CSV_FIELDS = (
    "jobId",
    "jobName",
    "company",
    "location",
    "salary",
    "salaryLowWan",
    "salaryHighWan",
    "education",
    "workYears",
    "industry",
    "financingStage",
    "companySize",
    "searchKeyword",
    "searchTime",
    "jobDetailUrl",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--with-jd",
        action="store_true",
        help="带上赛道 / 角色 / JD 全文（只导出已抓到 JD 的，且已按正文去重）",
    )
    args = parser.parse_args()

    context = AppContext.create()

    if args.with_jd:
        rows = load_rows(context.db, context.settings)
    else:
        rows = []
        offset = 0
        while True:  # 分页取全量，别一次把整库读进内存
            page = context.jobs.find(JobQuery(limit=MAX_PAGE_SIZE, offset=offset))
            rows.extend(page.items)
            offset += MAX_PAGE_SIZE
            if offset >= page.total:
                break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        args.output.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    else:
        fields = list(CSV_FIELDS) + (["track", "role"] if args.with_jd else [])
        with open(args.output, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})

    print(f"已导出 {len(rows)} 条到 {args.output}")
    context.close()


if __name__ == "__main__":
    main()
