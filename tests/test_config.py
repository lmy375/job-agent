"""配置加载：优先级、路径解析、校验错误、关键词展开。

配置分两个文件（全局 config/config.toml + profiles/<名>/profile.toml），
所以「写一份临时配置再加载」的用例要说清楚改的是哪一半。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import PROFILE
from job_agent.config import load_settings
from job_agent.config.loader import find_project_root
from job_agent.errors import ConfigError, MissingTokenError


def load_with_profile(project_root: Path, profile_toml: str, name: str = "tmp"):
    """写一个临时 profile 再加载它。测试 profile 侧的字段用这个。"""
    directory = project_root / "profiles" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "profile.toml").write_text(profile_toml, encoding="utf-8")
    return load_settings(name, project_root / "config" / "config.toml")


def load_with_global(project_root: Path, config_toml: str, name: str = "global.toml"):
    """写一个临时全局配置再加载它。测试全局侧的字段用这个。"""
    path = project_root / "config" / name
    path.write_text(config_toml, encoding="utf-8")
    return load_settings(PROFILE, path)


def test_paths_resolved_against_profile_dir(settings, profile_dir, project_root):
    """profile 侧的相对路径按 profile 目录解析——这是隔离的物理基础。"""
    assert settings.root == project_root
    assert settings.profile_name == PROFILE
    assert settings.profile_dir == profile_dir
    assert settings.storage.database == profile_dir / "data" / "test.db"
    assert settings.profile.resume == profile_dir / "resume.md"
    assert settings.profile.preferences == profile_dir / "preferences.md"
    assert settings.match.rules == profile_dir / "match.toml"
    assert settings.storage.database.is_absolute()


def test_root_side_paths_resolved_against_root(settings, project_root):
    """web / logging 跟 profile 无关，仍然按项目根解析。"""
    assert settings.web.frontend_dist == project_root / "frontend" / "dist"


def test_token_read_from_toml(settings):
    """密钥和别的配置项住同一个文件，没有第二处落盘。"""
    assert settings.require_token() == "test-token"


def test_env_var_beats_toml(project_root, monkeypatch):
    monkeypatch.setenv("JOB_AGENT_LIEPIN__ACCOUNTS__DEFAULT__USER_TOKEN", "from-env")
    settings = load_settings(PROFILE, project_root / "config" / "config.toml")
    assert settings.require_token() == "from-env"


def test_missing_token_raises(project_root, monkeypatch):
    monkeypatch.delenv("JOB_AGENT_LIEPIN__ACCOUNTS__DEFAULT__USER_TOKEN", raising=False)
    settings = load_with_global(project_root, "[liepin]\nrate_limit_per_min = 60\n")
    assert settings.account.user_token is None
    with pytest.raises(MissingTokenError):
        settings.require_token()


def test_blank_secret_is_none(project_root):
    """``user_token = ""`` 视同没配：空字符串漏进请求头比没配更难查。"""
    settings = load_with_global(
        project_root, '[liepin.accounts.default]\nuser_token = "   "\n'
    )
    assert settings.account.user_token is None


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
    with pytest.raises(ConfigError, match="未知配置项"):
        load_with_profile(project_root, "[search]\nsalaryFloor = 1000000\n")


def test_salary_without_kind_is_rejected(project_root):
    with pytest.raises(ConfigError, match="salary_kind"):
        load_with_profile(project_root, "[search]\nsalary_floor = 1000000\n")


def test_bad_track_name_is_rejected(project_root):
    with pytest.raises(ConfigError):
        load_with_profile(
            project_root, '[[search.groups]]\ntrack = "量子计算"\nkeywords = ["x"]\n'
        )


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_settings(config_file=tmp_path / "nope.toml")


def test_env_config_override(project_root, monkeypatch, tmp_path):
    other = tmp_path / "other.toml"
    other.write_text('[liepin]\ntimeout = 7.5\n', encoding="utf-8")
    monkeypatch.setenv("JOB_AGENT_CONFIG", str(other))
    monkeypatch.setenv("JOB_AGENT_HOME", str(project_root))
    settings = load_settings(PROFILE)
    assert settings.liepin.timeout == 7.5


def test_nested_env_overrides(project_root, monkeypatch):
    """任意配置项都能用 JOB_AGENT_<节>__<字段> 覆盖（pydantic-settings 原生行为）。"""
    monkeypatch.setenv("JOB_AGENT_WEB__PORT", "19999")
    monkeypatch.setenv("JOB_AGENT_LOGGING__LEVEL", "debug")
    monkeypatch.setenv("JOB_AGENT_SEARCH__ADDRESS", "上海")
    settings = load_settings(PROFILE, project_root / "config" / "config.toml")
    assert settings.web.port == 19999
    assert settings.logging.level == "DEBUG"
    # profile 侧同样能覆盖：两个文件的段名不重叠，一个变量只落到一边
    assert settings.search.address == "上海"


def test_find_project_root_walks_up(project_root):
    nested = project_root / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == project_root


def test_shipped_templates_are_valid(tmp_path):
    """仓库里的两份模板必须始终可加载——它们是新用户的第一份配置。

    刻意在临时目录里拼一遍（而不是直接加载仓库的 config/config.toml）：
    后者是开发机上的真实配置，测试跑通不代表新克隆的人跑得通。
    """
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir()
    shutil.copyfile(
        repo / "config" / "config.example.toml", tmp_path / "config" / "config.toml"
    )
    shutil.copytree(repo / "config" / "templates", tmp_path / "profiles" / "me")
    settings = load_settings("me", tmp_path / "config" / "config.toml")
    assert settings.search.keywords
    assert settings.liepin.rate_limit_per_min >= 1
    assert settings.profile.account in settings.liepin.accounts


def test_secrets_never_serialize_in_clear(project_root):
    """密钥是 SecretStr：dump 成 JSON 自动打码，靠类型防泄漏而不是靠记得脱敏。"""
    settings = load_with_global(
        project_root,
        '[liepin.accounts.default]\nuser_token = "liepin-secret"\n'
        '[agent.providers.anthropic]\napi = "anthropic"\n'
        'model = "claude-opus-5"\napi_key = "sk-ant-secret"\n'
        '[agent.langsmith]\napi_key = "lsv2-secret"\n',
    )
    dumped = settings.model_dump_json()
    for clear in ("liepin-secret", "sk-ant-secret", "lsv2-secret"):
        assert clear not in dumped
    assert dumped.count("**********") == 3
    # 要用的时候仍然取得到明文
    assert settings.require_token() == "liepin-secret"
    assert settings.agent.langsmith.enabled
