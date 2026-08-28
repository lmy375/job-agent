"""子命令注册。新增命令只需在这里挂上。"""

from __future__ import annotations

import typer

from job_agent.cli.commands import (
    apply_cmd,
    config_cmd,
    db_cmd,
    detail_cmd,
    match_cmd,
    report_cmd,
    resume_cmd,
    search_cmd,
    shortlist_cmd,
    stats_cmd,
    web_cmd,
)


def register(app: typer.Typer) -> None:
    app.command("search", help="按配置的关键词批量搜索职位并入库。")(search_cmd.search)
    app.command("detail", help="抓取职位详情页，解析 JD 写入数据库。")(detail_cmd.detail)
    app.command("match", help="按 config/match.toml 的信号表给职位打分排序（分诊）。")(
        match_cmd.match
    )
    app.command("shortlist", help="生成候选清单骨架，判断部分留给 /job-match 填。")(
        shortlist_cmd.shortlist
    )
    app.command("apply", help="投递职位（可传多个 jobId）。")(apply_cmd.apply)
    app.command("report", help="根据已抓取的 JD 生成 HTML 市场分析报告。")(report_cmd.report)
    app.command("stats", help="在终端查看库内数据概览。")(stats_cmd.stats)
    app.command("web", help="启动 Web 管理服务（数据浏览 + 采集任务 + 投递）。")(web_cmd.web)
    app.add_typer(config_cmd.app, name="config", help="查看与初始化配置。")
    app.add_typer(resume_cmd.app, name="resume", help="简历文件导入。")
    app.add_typer(db_cmd.app, name="db", help="数据库维护。")
