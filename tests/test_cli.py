"""CLI：参数解析、退出码、确认提示。不发网络请求。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import make_job
from job_agent.cli import app
from job_agent.context import AppContext
from job_agent.core.liepin.errors import LiepinRateLimited
from job_agent.core.liepin.models import ApplyJobResult

runner = CliRunner()

AI_JD = "岗位职责：\n负责大模型 Agent 平台\n任职要求：\n熟悉 Python、LLM、RAG 与智能体"


@pytest.fixture
def config_path(project_root: Path) -> Path:
    return project_root / "config" / "config.toml"


def run(config_path: Path, *args: str):
    return runner.invoke(app, ["--config", str(config_path), *args])


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "job-agent" in result.stdout


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("search", "detail", "apply", "report", "stats", "web", "config", "db"):
        assert command in result.stdout


def test_config_show_and_path(config_path):
    result = run(config_path, "config", "show")
    assert result.exit_code == 0
    assert "测试用户" in result.stdout

    result = run(config_path, "config", "path")
    assert "test.db" in result.stdout


def test_config_show_json(config_path):
    import json

    result = run(config_path, "config", "show", "--json")
    assert json.loads(result.stdout)["profile"]["name"] == "测试用户"


def test_config_validate_fails_without_token(project_root, config_path, monkeypatch):
    monkeypatch.delenv("LIEPIN_USER_TOKEN", raising=False)
    (project_root / "config" / ".env").unlink()
    result = run(config_path, "config", "validate")
    assert result.exit_code == 2
    assert "LIEPIN_USER_TOKEN" in result.stdout


def test_config_init_copies_all_templates(tmp_path, monkeypatch):
    """init 要把仓库里的每份模板都落地，缺一个用户就会卡在那一步。"""
    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    repo_root = Path(__file__).resolve().parents[1]
    for name in (
        "config.example.toml",
        ".env.example",
        "resume.example.md",
        "preferences.example.md",
    ):
        (root / "config" / name).write_text(
            (repo_root / "config" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    shutil.copytree(repo_root / "config" / "insights.example", root / "config" / "insights.example")

    monkeypatch.setenv("JOB_AGENT_HOME", str(root))
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    for name in ("config.toml", ".env", "resume.md", "preferences.md"):
        assert (root / "config" / name).is_file(), name
    assert (root / "config" / "insights" / "ai.html").is_file()

    # 再跑一次不会覆盖已有内容
    (root / "config" / "resume.md").write_text("我自己写的", encoding="utf-8")
    result = runner.invoke(app, ["config", "init"])
    assert "已存在" in result.stdout
    assert (root / "config" / "resume.md").read_text(encoding="utf-8") == "我自己写的"


def test_config_validate_reports_missing_profile_files(project_root, config_path):
    (project_root / "config" / "resume.md").unlink()
    (project_root / "config" / "preferences.md").unlink()
    result = run(config_path, "config", "validate")
    assert result.exit_code == 2
    assert "简历文件不存在" in result.stdout
    assert "求职偏好文件不存在" in result.stdout


def test_stats_on_empty_db(config_path):
    result = run(config_path, "stats")
    assert result.exit_code == 0
    assert "职位总数" in result.stdout


def test_search_dry_run_does_not_hit_network(config_path, monkeypatch):
    monkeypatch.setattr(AppContext, "client", lambda _self: pytest.fail("dry-run 不该建客户端"))
    result = run(config_path, "search", "--dry-run")
    assert result.exit_code == 0
    assert "AI Agent（AI）" in result.stdout


def test_db_info_and_migrate(config_path):
    assert run(config_path, "db", "info").exit_code == 0
    result = run(config_path, "db", "migrate")
    assert "无需迁移" in result.stdout


def test_report_without_data_exits_nonzero(config_path):
    result = run(config_path, "report")
    assert result.exit_code == 1
    assert "没有可用的 JD" in result.stdout


def test_report_generates_file(config_path, context, insights_dir, tmp_path):
    context.jobs.upsert_many([make_job(1, salary="80-100k·15薪")], keyword="AI Agent")
    context.details.upsert({"jobId": 1, "description": AI_JD, "status": "ok"})
    output = tmp_path / "r.html"
    result = run(config_path, "report", "-o", str(output))
    assert result.exit_code == 0
    assert output.is_file()


def test_apply_requires_confirmation(config_path, context, monkeypatch):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    monkeypatch.setattr(AppContext, "client", lambda _self: pytest.fail("拒绝确认后不该投递"))
    result = runner.invoke(app, ["--config", str(config_path), "apply", "1"], input="n\n")
    assert result.exit_code == 1  # typer.confirm(abort=True)


def test_apply_with_yes_flag(config_path, context, monkeypatch):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")

    class FakeClient:
        def apply_job(self, job_id, job_kind):
            return ApplyJobResult(ok=True, message="应聘成功")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(AppContext, "client", lambda _self: FakeClient())
    result = run(config_path, "apply", "1", "--yes")
    assert result.exit_code == 0
    assert "应聘成功" in result.stdout
    assert context.applications.applied_ids() == {1}


def test_apply_rate_limit_exit_code(config_path, context, monkeypatch):
    """限流有专属退出码，脚本里能据此判断「今天别再投了」。"""
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")

    class RateLimited:
        def apply_job(self, job_id, job_kind):
            raise LiepinRateLimited("429001")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(AppContext, "client", lambda _self: RateLimited())
    result = run(config_path, "apply", "1", "--yes")
    assert result.exit_code == 6


def test_apply_rejects_bad_job_kind(config_path):
    result = run(config_path, "apply", "1", "--job-kind", "9", "--yes")
    assert result.exit_code != 0


def test_bad_config_path_exits_with_code_2():
    result = runner.invoke(app, ["--config", "/nope/nope.toml", "stats"])
    assert result.exit_code == 2
