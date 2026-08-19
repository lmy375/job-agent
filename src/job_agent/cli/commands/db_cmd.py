"""``job db``：数据库维护。"""

from __future__ import annotations

import typer
from sqlalchemy import text

from job_agent.cli.state import CliState, echo_ok
from job_agent.core.storage.migrations import run_migrations

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("info", help="打印数据库位置、体积与各表行数。")
def info(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    context = state.context()
    path = context.settings.storage.database
    size = path.stat().st_size / 1024 / 1024 if path.is_file() else 0.0

    typer.secho(f"{path}（{size:.1f} MB）", bold=True)
    with context.db.session() as session:
        tables = [
            row[0]
            for row in session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
        ]
        for table in tables:
            count = session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            typer.echo(f"  {table:<16}{count:>8}")


@app.command("migrate", help="补齐缺失的列并回填派生字段（幂等）。")
def migrate(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    context = state.context()
    done = run_migrations(context.db.engine)
    if not done:
        echo_ok("数据库已是最新，无需迁移")
        return
    for item in done:
        typer.echo(f"  · {item}")
    echo_ok(f"完成 {len(done)} 项迁移")


@app.command("vacuum", help="回收空间（VACUUM）。")
def vacuum(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    context = state.context()
    path = context.settings.storage.database
    before = path.stat().st_size if path.is_file() else 0
    with context.db.engine.connect() as conn:
        conn.exec_driver_sql("VACUUM")
    after = path.stat().st_size if path.is_file() else 0
    echo_ok(f"VACUUM 完成：{before / 1024 / 1024:.1f} MB → {after / 1024 / 1024:.1f} MB")
