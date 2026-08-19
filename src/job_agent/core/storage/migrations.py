"""轻量迁移。

只有一个 SQLite 文件、只有一个使用者，上 Alembic 的收益抵不过复杂度；
但「加列 + 回填」这件事必须自动化，否则老库升级后会直接查不出来。
迁移按「检查现状 → 补齐差异」写，天然幂等。
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from job_agent.core.salary import parse_salary
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 表 -> [(列名, SQLite 类型)]，缺列则 ALTER TABLE 补上
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "jobs": [("salaryLowWan", "FLOAT"), ("salaryHighWan", "FLOAT")],
}


def run_migrations(engine: Engine) -> list[str]:
    """执行所有待办迁移，返回做过的事情（便于日志与测试断言）。"""
    done: list[str] = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    for table, columns in _ADDED_COLUMNS.items():
        if table not in tables:
            continue  # create_all 建的新库天然带这些列
        existing = {c["name"] for c in inspector.get_columns(table)}
        for name, sql_type in columns:
            if name in existing:
                continue
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}'))
            done.append(f"{table}.{name} 已新增")
            logger.info("迁移：%s 表新增列 %s", table, name)

    if "jobs" in tables:
        filled = _backfill_salary(engine)
        if filled:
            done.append(f"回填 {filled} 条薪资区间")
            logger.info("迁移：回填 %d 条职位的年薪区间", filled)

    return done


def _backfill_salary(engine: Engine) -> int:
    """给还没算过年薪区间的历史职位补上。

    只处理 salaryHighWan IS NULL 的行，所以重跑不会重复劳动；
    解析不出来的（薪资写「面议」）会被反复扫到，但这类行极少，代价可以忽略。
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                'SELECT "jobId", "salary" FROM "jobs" '
                'WHERE "salaryHighWan" IS NULL AND "salary" IS NOT NULL AND "salary" != \'\''
            )
        ).all()
        updates = []
        for job_id, salary in rows:
            band = parse_salary(salary)
            if band is None:
                continue
            updates.append({"jid": job_id, "low": band.low, "high": band.high})
        if updates:
            conn.execute(
                text(
                    'UPDATE "jobs" SET "salaryLowWan" = :low, "salaryHighWan" = :high '
                    'WHERE "jobId" = :jid'
                ),
                updates,
            )
    return len(updates)
