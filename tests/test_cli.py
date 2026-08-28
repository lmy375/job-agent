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


# ---------------------------------------------------------------- match / shortlist


def seed_agent_job(context, job_id: int = 1, salary: str = "80-100k·20薪") -> None:
    """一条会被信号表打高分的岗位：上限 192-240 万，过得了 135 万门槛。"""
    context.jobs.upsert_many(
        [make_job(job_id, jobName="Agent 平台工程师", salary=salary)], keyword="AI Agent"
    )
    context.details.upsert({"jobId": job_id, "description": AI_JD, "status": "ok"})


def test_help_lists_new_commands():
    result = runner.invoke(app, ["--help"])
    for command in ("match", "shortlist", "resume"):
        assert command in result.stdout


def test_match_without_data_exits_nonzero(config_path):
    result = run(config_path, "match")
    assert result.exit_code == 1
    assert "没有可排序的职位" in result.stdout


def test_match_lists_jobs(config_path, context):
    seed_agent_job(context)
    result = run(config_path, "match")
    assert result.exit_code == 0
    assert "Agent 平台工程师" in result.stdout
    # 提醒必须在：分数只做分诊
    assert "分诊" in result.stdout


def test_match_why_shows_reasons(config_path, context):
    seed_agent_job(context)
    result = run(config_path, "match", "--why")
    assert result.exit_code == 0
    assert "Agent" in result.stdout
    assert "Python" in result.stdout


def test_match_json_is_parseable(config_path, context):
    import json

    seed_agent_job(context)
    result = run(config_path, "match", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data[0]["jobId"] == 1
    assert "Agent" in " ".join(data[0]["hits"])


def test_match_floor_filters(config_path, context):
    seed_agent_job(context, salary="20-30k·12薪")  # 上限 36 万
    result = run(config_path, "match", "--floor", "135")
    assert result.exit_code == 1
    assert "门槛太高" in result.stdout


def test_match_missing_rules_file(config_path, project_root, context):
    seed_agent_job(context)
    (project_root / "config" / "match.toml").unlink()
    result = run(config_path, "match")
    assert result.exit_code == 2
    assert "匹配信号表不存在" in result.stderr


def test_shortlist_writes_file(config_path, context, tmp_path):
    seed_agent_job(context)
    target = tmp_path / "out" / "shortlist.md"
    result = run(config_path, "shortlist", "-o", str(target))
    assert result.exit_code == 0
    assert target.is_file()
    body = target.read_text(encoding="utf-8")
    assert "Agent 平台工程师" in body
    assert "<待 /job-match 填写>" in body


def test_shortlist_without_data_exits_nonzero(config_path):
    result = run(config_path, "shortlist")
    assert result.exit_code == 1


def test_config_validate_reports_bad_match_rules(config_path, project_root):
    """信号表里的正则写错，validate 就该报出来，而不是等 job match 炸。"""
    (project_root / "config" / "match.toml").write_text(
        '[[signals]]\nname="x"\nweight=1\npattern="([unclosed"\n', encoding="utf-8"
    )
    result = run(config_path, "config", "validate")
    assert result.exit_code == 2
    assert "校验失败" in result.stdout


def test_config_path_includes_match(config_path):
    result = run(config_path, "config", "path")
    assert "match" in result.stdout
    assert "shortlist" in result.stdout


# ---------------------------------------------------------------- resume import


def test_resume_import_to_stdout(config_path, tmp_path):
    source = tmp_path / "resume.md"
    source.write_text("# 简历\n\n" + "负责 Agent 平台，带 5 人团队。" * 5, encoding="utf-8")
    result = run(config_path, "resume", "import", str(source))
    assert result.exit_code == 0
    assert "Agent 平台" in result.stdout


def test_resume_import_to_file(config_path, tmp_path):
    source = tmp_path / "resume.md"
    source.write_text("负责 Agent 平台，带 5 人团队。" * 5, encoding="utf-8")
    target = tmp_path / "out.txt"
    result = run(config_path, "resume", "import", str(source), "-o", str(target))
    assert result.exit_code == 0
    assert "Agent 平台" in target.read_text(encoding="utf-8")


def test_resume_import_refuses_to_clobber_resume_md(config_path, project_root, tmp_path):
    """抽出来的是无结构文本，直接盖掉整理好的简历会丢排版和信息。"""
    source = tmp_path / "resume.md"
    source.write_text("负责 Agent 平台。" * 10, encoding="utf-8")
    target = project_root / "config" / "resume.md"
    before = target.read_text(encoding="utf-8")

    result = run(config_path, "resume", "import", str(source), "-o", str(target))
    assert result.exit_code == 1
    assert target.read_text(encoding="utf-8") == before


def test_resume_import_bad_file(config_path, tmp_path):
    result = run(config_path, "resume", "import", str(tmp_path / "nope.pdf"))
    assert result.exit_code == 5
    assert "文件不存在" in result.stderr
