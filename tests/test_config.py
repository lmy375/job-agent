"""配置加载：优先级、路径解析、校验错误、关键词展开。"""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.config import load_settings
from job_agent.config.loader import find_project_root
from job_agent.errors import ConfigError, MissingTokenError


def test_paths_resolved_against_root(settings, project_root):
    assert settings.root == project_root
    assert settings.storage.database == project_root / "data" / "test.db"
    assert settings.profile.resume == project_root / "config" / "resume.md"
    assert settings.storage.database.is_absolute()


def test_token_read_from_env_file(settings):
    assert settings.token == "test-token"
    assert settings.require_token() == "test-token"


def test_env_var_beats_env_file(project_root, monkeypatch):
    monkeypatch.setenv("LIEPIN_USER_TOKEN", "from-env")
    settings = load_settings(project_root / "config" / "config.toml")
    assert settings.token == "from-env"


def test_missing_token_raises(project_root, monkeypatch):
    monkeypatch.delenv("LIEPIN_USER_TOKEN", raising=False)
    (project_root / "config" / ".env").unlink()
    settings = load_settings(project_root / "config" / "config.toml")
    assert settings.token is None
    with pytest.raises(MissingTokenError):
        settings.require_token()


def test_keywords_flattened_in_priority_order(settings):
    # 禁用的组不参与搜索
    assert settings.search.keywords == ["AI Agent", "大模型", "安全专家"]


def test_track_lookup_includes_disabled_groups(settings):
    """禁用的组仍要能查到赛道：库里存量数据的 searchKeyword 可能来自已关掉的组。"""
    assert settings.search.track_for_keyword("AI Agent") == "AI"
    assert settings.search.track_for_keyword("区块链") == "Web3"
    assert settings.search.track_for_keyword("ai agent") == "AI"  # 大小写不敏感
    assert settings.search.track_for_keyword("不存在的词") is None


def test_unknown_key_is_rejected(project_root):
    """配置项拼错必须报错——静默忽略是配置系统最容易埋的坑。"""
    path = project_root / "config" / "bad.toml"
    path.write_text("[search]\nsalaryFloor = 1000000\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="未知配置项"):
        load_settings(path)


def test_salary_without_kind_is_rejected(project_root):
    path = project_root / "config" / "bad2.toml"
    path.write_text("[search]\nsalary_floor = 1000000\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="salary_kind"):
        load_settings(path)


def test_bad_track_name_is_rejected(project_root):
    path = project_root / "config" / "bad3.toml"
    path.write_text(
        '[[search.groups]]\ntrack = "量子计算"\nkeywords = ["x"]\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_settings(path)


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_settings(tmp_path / "nope.toml")


def test_env_config_override(project_root, monkeypatch, tmp_path):
    other = tmp_path / "other.toml"
    other.write_text('[profile]\nname = "另一个人"\n', encoding="utf-8")
    monkeypatch.setenv("JOB_AGENT_CONFIG", str(other))
    monkeypatch.setenv("JOB_AGENT_HOME", str(project_root))
    settings = load_settings()
    assert settings.profile.name == "另一个人"


def test_scalar_env_overrides(project_root, monkeypatch):
    monkeypatch.setenv("JOB_AGENT_WEB_PORT", "19999")
    monkeypatch.setenv("JOB_AGENT_LOG_LEVEL", "debug")
    settings = load_settings(project_root / "config" / "config.toml")
    assert settings.web.port == 19999
    assert settings.logging.level == "DEBUG"


def test_find_project_root_walks_up(project_root):
    nested = project_root / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == project_root


def test_example_config_is_valid():
    """仓库里的模板必须始终可加载——它是新用户的第一份配置。"""
    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root / "config" / "config.example.toml")
    assert settings.search.keywords
    assert settings.liepin.rate_limit_per_min >= 1


def test_redacted_hides_token(settings):
    assert settings.redacted()["token"] == "已配置"
