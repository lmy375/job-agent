"""CLI：参数解析、退出码、确认提示。不发网络请求。"""

from __future__ import annotations

import json
import shutil
from contextlib import nullcontext
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import PROFILE, make_detail, make_job
from job_agent.cli import app
from job_agent.context import AppContext
from job_agent.core.liepin.errors import LiepinRateLimited
from job_agent.core.liepin.models import ApplyJobResult
from job_agent.core.services import DetailService, SearchService
from job_agent.core.services.detail import DetailSummary
from job_agent.core.services.search import SearchSummary
from job_agent.core.storage import Database, JobRepository

runner = CliRunner()

AI_JD = "岗位职责：\n负责大模型 Agent 平台\n任职要求：\n熟悉 Python、LLM、RAG 与智能体"


@pytest.fixture
def config_path(project_root: Path) -> Path:
    return project_root / "config" / "config.toml"


def run(config_path: Path, *args: str, input: str | None = None):
    return runner.invoke(
        app, ["--profile", PROFILE, "--config", str(config_path), *args], input=input
    )


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "job-agent" in result.stdout


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("search", "score", "apply", "agent", "stats", "web", "config", "db"):
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
    monkeypatch.delenv("JOB_AGENT_LIEPIN__USER_TOKEN", raising=False)
    text = config_path.read_text(encoding="utf-8").replace('user_token = "test-token"', "")
    config_path.write_text(text, encoding="utf-8")
    result = run(config_path, "config", "validate")
    assert result.exit_code == 2
    assert "user_token" in result.stdout


@pytest.fixture
def fresh_root(tmp_path, monkeypatch) -> Path:
    """一个只有仓库模板、还没初始化过的项目根——模拟新克隆。"""
    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    repo_root = Path(__file__).resolve().parents[1]
    shutil.copyfile(
        repo_root / "config" / "config.example.toml", root / "config" / "config.example.toml"
    )
    shutil.copytree(repo_root / "config" / "templates", root / "config" / "templates")
    monkeypatch.setenv("JOB_AGENT_HOME", str(root))
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    return root


def test_config_init_creates_global_config(fresh_root):
    """init 只管全局配置：profile 的骨架归 `job profile new`。"""
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    assert (fresh_root / "config" / "config.toml").is_file()
    assert "job profile new" in result.stdout

    # 再跑一次不会覆盖已有内容
    (fresh_root / "config" / "config.toml").write_text("# 我自己写的", encoding="utf-8")
    result = runner.invoke(app, ["config", "init"])
    assert "已存在" in result.stdout
    assert (fresh_root / "config" / "config.toml").read_text(encoding="utf-8") == "# 我自己写的"


def test_profile_new_copies_templates_and_sets_default(fresh_root):
    """新建 profile = 把 config/templates/ 整份拷过去，第一个还顺手设成默认。"""
    assert runner.invoke(app, ["config", "init"]).exit_code == 0
    result = runner.invoke(app, ["profile", "new", "me"])
    assert result.exit_code == 0
    for name in ("profile.toml", "resume.md", "preferences.md"):
        assert (fresh_root / "profiles" / "me" / name).is_file(), name
    assert (fresh_root / "profiles" / "me" / "data").is_dir()
    # 第一个 profile 自动成为默认，不带 --profile 也能跑
    assert 'default = "me"' in (fresh_root / "config" / "config.toml").read_text(encoding="utf-8")
    assert "me" in runner.invoke(app, ["config", "path"]).stdout

    # 已存在时不覆盖
    assert runner.invoke(app, ["profile", "new", "me"]).exit_code == 2


def test_profile_new_rejects_bad_names(fresh_root):
    """名字就是目录名：路径穿越这类输入要在建目录之前挡掉。"""
    assert runner.invoke(app, ["config", "init"]).exit_code == 0
    for bad in ("../evil", "with space", ".hidden"):
        assert runner.invoke(app, ["profile", "new", bad]).exit_code == 2


def test_profiles_are_isolated(fresh_root):
    """两个 profile 各写各的库：这是整个设计要保证的那件事。"""
    assert runner.invoke(app, ["config", "init"]).exit_code == 0
    assert runner.invoke(app, ["profile", "new", "a"]).exit_code == 0
    assert runner.invoke(app, ["profile", "new", "b"]).exit_code == 0

    paths = {}
    for name in ("a", "b"):
        result = runner.invoke(app, ["--profile", name, "config", "path", "--json"])
        assert result.exit_code == 0, result.stdout
        paths[name] = json.loads(result.stdout)

    assert paths["a"]["database"] != paths["b"]["database"]
    for key in ("database", "resume", "preferences"):
        assert "profiles/a" in paths["a"][key], key
        assert "profiles/b" in paths["b"][key], key


def test_config_validate_reports_missing_profile_files(profile_dir, config_path):
    (profile_dir / "resume.md").unlink()
    (profile_dir / "preferences.md").unlink()
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
    assert "AI Agent" in result.stdout


@pytest.fixture
def fake_collect(monkeypatch):
    """把两个服务的 run 换成假的，只记录「detail 有没有被调到」。"""
    calls: list[str] = []

    def fake_search_run(_self, **_kwargs):
        calls.append("search")
        return SearchSummary(results=[])

    def fake_detail_run(_self, **_kwargs):
        calls.append("detail")
        return DetailSummary()

    monkeypatch.setattr(AppContext, "client", lambda _self: nullcontext(object()))
    monkeypatch.setattr(SearchService, "run", fake_search_run)
    monkeypatch.setattr(DetailService, "run", fake_detail_run)
    monkeypatch.setattr(DetailService, "close", lambda _self: None)
    return calls


def test_search_fetches_details_afterwards(config_path, fake_collect):
    """两条命令合并的核心承诺：搜完自动接着抓 JD。"""
    assert run(config_path, "search").exit_code == 0
    assert fake_collect == ["search", "detail"]


def test_search_no_detail_stops_after_search(config_path, fake_collect):
    assert run(config_path, "search", "--no-detail").exit_code == 0
    assert fake_collect == ["search"]


def test_db_info(config_path):
    assert run(config_path, "db", "info").exit_code == 0


def test_reset_needs_confirmation(config_path, context):
    """删库不可撤销（投递记录只存在本地），默认必须确认一次。"""
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    context.applications.record(1, "ok", "应聘成功")

    declined = run(config_path, "reset", input="n\n")
    assert declined.exit_code != 0
    assert context.settings.storage.database.is_file()
    assert "投递记录删掉就找不回来了" in declined.stdout


def test_reset_rebuilds_empty_db(config_path, context):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    result = run(config_path, "reset", "--yes")
    assert result.exit_code == 0
    assert "已重建空库" in result.stdout

    # 重新开一个连接来看：老连接握的是被删掉的 inode，看到的还是旧数据
    fresh = Database(context.settings.storage.database).setup()
    assert JobRepository(fresh).count() == 0
    fresh.dispose()


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


# ---------------------------------------------------------------- score


def seed_agent_job(context, job_id: int = 1, salary: str = "80-100k·20薪") -> None:
    """一条会被信号表打高分的岗位：上限 192-240 万，过得了 135 万门槛。"""
    context.jobs.upsert_many(
        [make_job(job_id, jobName="Agent 平台工程师", salary=salary)], keyword="AI Agent"
    )
    context.details.upsert(make_detail(job_id, description=AI_JD))


def test_help_lists_new_commands():
    result = runner.invoke(app, ["--help"])
    for command in ("score", "resume", "profile"):
        assert command in result.stdout


def test_score_without_data_exits_nonzero(config_path):
    result = run(config_path, "score")
    assert result.exit_code == 1
    assert "没有可排序的职位" in result.stdout


def test_score_lists_jobs(config_path, context):
    seed_agent_job(context)
    result = run(config_path, "score")
    assert result.exit_code == 0
    assert "Agent 平台工程师" in result.stdout
    # 提醒必须在：分数只做分诊
    assert "分诊" in result.stdout


def test_score_why_shows_reasons(config_path, context):
    seed_agent_job(context)
    result = run(config_path, "score", "--why")
    assert result.exit_code == 0
    assert "Agent" in result.stdout
    assert "Python" in result.stdout


def test_score_json_is_parseable(config_path, context):
    import json

    seed_agent_job(context)
    result = run(config_path, "score", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data[0]["jobId"] == 1
    assert "Agent" in " ".join(data[0]["hits"])


def test_score_floor_filters(config_path, context):
    seed_agent_job(context, salary="20-30k·12薪")  # 上限 36 万
    result = run(config_path, "score", "--floor", "135")
    assert result.exit_code == 1
    assert "门槛太高" in result.stdout


def test_score_without_signals_exits_with_config_error(config_path, profile_dir, context):
    """[score] 段里没有信号 = 全 0 分的排名，看着像成功——必须拦。"""
    seed_agent_job(context)
    body = (profile_dir / "profile.toml").read_text(encoding="utf-8")
    (profile_dir / "profile.toml").write_text(
        body[: body.index("[score]")] + "[score]\n", encoding="utf-8"
    )
    result = run(config_path, "score")
    assert result.exit_code == 2
    assert "[[score.signals]]" in result.stdout


def test_score_output_writes_shortlist(config_path, context, tmp_path):
    seed_agent_job(context)
    target = tmp_path / "out" / "shortlist.md"
    result = run(config_path, "score", "-o", str(target))
    assert result.exit_code == 0
    assert target.is_file()
    body = target.read_text(encoding="utf-8")
    assert "Agent 平台工程师" in body
    assert "<待 /job-match 填写>" in body


def test_score_output_relative_lands_in_profile(config_path, profile_dir, context):
    """-o 的相对路径按 profile 目录解析：产物跟着 profile 走，两个 profile 不互相覆盖。"""
    seed_agent_job(context)
    assert run(config_path, "score", "-o", "data/shortlist.md").exit_code == 0
    assert (profile_dir / "data" / "shortlist.md").is_file()


def test_score_output_with_json_writes_json(config_path, context, tmp_path):
    """-o 决定「写文件」，--json 决定「什么格式」——两个维度正交。"""
    import json

    seed_agent_job(context)
    target = tmp_path / "out.json"
    assert run(config_path, "score", "--json", "-o", str(target)).exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))[0]["jobId"] == 1


def test_score_output_without_data_exits_nonzero(config_path, tmp_path):
    result = run(config_path, "score", "-o", str(tmp_path / "x.md"))
    assert result.exit_code == 1


def test_config_validate_reports_missing_signals(config_path, profile_dir):
    """信号表空着，validate 就该报出来，而不是等 job score 排出一堆 0 分。"""
    body = (profile_dir / "profile.toml").read_text(encoding="utf-8")
    (profile_dir / "profile.toml").write_text(
        body[: body.index("[score]")], encoding="utf-8"
    )
    result = run(config_path, "config", "validate")
    assert result.exit_code == 2
    assert "[[score.signals]]" in result.stdout


def test_config_path_lists_profile_inputs(config_path):
    result = run(config_path, "config", "path")
    assert "resume" in result.stdout
    assert "database" in result.stdout


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


def test_resume_import_refuses_to_clobber_resume_md(config_path, profile_dir, tmp_path):
    """抽出来的是无结构文本，直接盖掉整理好的简历会丢排版和信息。"""
    source = tmp_path / "resume.md"
    source.write_text("负责 Agent 平台。" * 10, encoding="utf-8")
    target = profile_dir / "resume.md"
    before = target.read_text(encoding="utf-8")

    result = run(config_path, "resume", "import", str(source), "-o", str(target))
    assert result.exit_code == 1
    assert target.read_text(encoding="utf-8") == before


def test_resume_import_bad_file(config_path, tmp_path):
    result = run(config_path, "resume", "import", str(tmp_path / "nope.pdf"))
    assert result.exit_code == 5
    assert "文件不存在" in result.stderr
