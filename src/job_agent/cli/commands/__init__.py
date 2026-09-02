"""子命令注册。新增命令只需在这里挂上。"""

from __future__ import annotations

import typer

from job_agent.cli.commands import (
    agent_cmd,
    apply_cmd,
    config_cmd,
    db_cmd,
    profile_cmd,
    reset_cmd,
    resume_cmd,
    score_cmd,
    search_cmd,
    stats_cmd,
    web_cmd,
)
from job_agent.cli.help import h


def register(app: typer.Typer) -> None:
    app.command(
        "search", help="按配置的关键词批量搜索职位入库，并接着抓详情页解析 JD。"
    )(search_cmd.search)
    app.command(
        "score",
        help=h("按 profile.toml 的 [score] 信号表打分排序（分诊）；-o 写出候选清单骨架。"),
    )(score_cmd.score)
    app.command("apply", help="投递职位（可传多个 jobId）。")(apply_cmd.apply)
    app.command(
        "agent",
        help="LangGraph 路线：无人值守跑完 采集 → 分诊 → 审读 → 投递计划。",
    )(agent_cmd.agent)
    app.command("stats", help="在终端查看库内数据概览。")(stats_cmd.stats)
    app.command("web", help="启动 Web 管理服务（数据浏览 + 采集任务 + 投递）。")(web_cmd.web)
    app.command("reset", help="删掉数据库并重建空库（不做迁移，重采即可）。")(reset_cmd.reset)
    app.add_typer(
        profile_cmd.app, name="profile", help="管理 profile（一个人 / 一种求职场景）。"
    )
    app.add_typer(config_cmd.app, name="config", help="查看与初始化配置。")
    app.add_typer(resume_cmd.app, name="resume", help="简历文件导入。")
    app.add_typer(db_cmd.app, name="db", help="数据库维护。")
