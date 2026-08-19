#!/usr/bin/env python
"""把早期版本导出的 jobs.csv 导进数据库（按 jobId 去重，已存在的跳过）。

老版 job-agent 用 CSV 存数据，这个脚本保留了迁移路径；
它刻意做成脚本而不是自动迁移——自动导入很容易在换目录时莫名其妙多出一批旧数据。

    uv run python scripts/import_legacy_csv.py data/jobs.csv
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from job_agent.context import AppContext
from job_agent.core.salary import parse_salary
from job_agent.core.storage import JobRecord


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="旧的 jobs.csv")
    args = parser.parse_args()
    if not args.path.is_file():
        raise SystemExit(f"文件不存在：{args.path}")

    context = AppContext.create()
    rows = []
    with open(args.path, encoding="utf-8-sig", newline="") as fh:
        for record in csv.DictReader(fh):
            if not record.get("jobId"):
                continue
            # 老格式里 companyTags 是 `|` 连接的字符串
            tags = record.get("companyTags") or ""
            salary = record.get("salary", "")
            band = parse_salary(salary)
            rows.append(
                {
                    "jobId": int(record["jobId"]),
                    "jobType": record.get("jobType", ""),
                    "jobName": record.get("jobName", ""),
                    "company": record.get("company", ""),
                    "location": record.get("location", ""),
                    "salary": salary,
                    "salaryLowWan": band.low if band else None,
                    "salaryHighWan": band.high if band else None,
                    "education": record.get("education", ""),
                    "workYears": record.get("workYears", ""),
                    "industry": record.get("industry", ""),
                    "companyTags": tags.split("|") if tags else [],
                    "financingStage": record.get("financingStage", ""),
                    "companySize": record.get("companySize", ""),
                    "companyLogo": record.get("companyLogo", ""),
                    "jobDetailUrl": record.get("jobDetailUrl", ""),
                    "searchKeyword": record.get("searchKeyword", ""),
                    "searchTime": _parse_time(record.get("searchTime")),
                }
            )

    if not rows:
        print("CSV 里没有可导入的行。")
        return

    with context.db.session() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord)) or 0
        statement = sqlite_insert(JobRecord).on_conflict_do_nothing(index_elements=["jobId"])
        session.execute(statement, rows)
        session.flush()
        after = session.scalar(select(func.count()).select_from(JobRecord)) or 0

    print(f"读入 {len(rows)} 行，新增 {after - before} 条（其余已存在）。")
    context.close()


def _parse_time(value: str | None) -> datetime:
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.now()


if __name__ == "__main__":
    main()
