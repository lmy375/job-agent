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

from pydantic import BaseModel

from job_agent.context import AppContext
from job_agent.core.analysis import load_rows
from job_agent.core.storage import JobQuery
from job_agent.core.storage.repositories import MAX_PAGE_SIZE

#: 注意：``--with-jd`` 走的是分析行（AnalysisRow），它把这几列叫 salaryLow /
#: salaryHigh / keyword / url，字段名对不上，所以那几列会导成空——
#: 这是从 dict 时代就有的行为，迁移到 model 时按原样保留了。
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
    parser.add_argument(
        "--profile", "-p", default=None, help="用哪个 profile（默认取 [profiles].default）"
    )
    args = parser.parse_args()

    context = AppContext.create(profile=args.profile)

    rows: list[BaseModel]
    if args.with_jd:
        rows = list(load_rows(context.db, context.settings))
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
        # skills 是统计阶段才填的中间量，不属于导出内容
        dumped = [row.model_dump(mode="json", exclude={"skills"}) for row in rows]
        args.output.write_text(
            json.dumps(dumped, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        fields = list(CSV_FIELDS) + (["track", "role"] if args.with_jd else [])
        with open(args.output, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: getattr(row, k, "") for k in fields})

    print(f"已导出 {len(rows)} 条到 {args.output}")
    context.close()


if __name__ == "__main__":
    main()
