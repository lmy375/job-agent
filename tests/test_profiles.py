"""profile 隔离：定位优先级、目录隔离、段归属、账号选择。

这个文件盯的是一句承诺：**profiles/a 与 profiles/b 互不可见**。
配置、简历、信号表、数据库、产物，一样都不许串。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import CONFIG_TOML, PROFILE, make_job, make_profile
from job_agent.config import load_settings
from job_agent.config.loader import list_profiles, resolve_profile
from job_agent.context import AppContext
from job_agent.errors import ConfigError, ProfileNotFoundError


def config_of(root: Path) -> Path:
    return root / "config" / "config.toml"


def set_default(root: Path, value: str | None) -> None:
    """改写全局配置里的 [profiles].default。"""
    text = CONFIG_TOML.replace(
        'default = "test"', "" if value is None else f'default = "{value}"'
    )
    config_of(root).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- 定位优先级


def test_explicit_profile_wins(project_root, monkeypatch):
    make_profile(project_root, "other")
    monkeypatch.setenv("JOB_AGENT_PROFILE_NAME", "other")
    # --profile 压过环境变量，环境变量压过 [profiles].default
    assert load_settings("test", config_of(project_root)).profile_name == "test"


def test_env_beats_configured_default(project_root, monkeypatch):
    make_profile(project_root, "other")
    monkeypatch.setenv("JOB_AGENT_PROFILE_NAME", "other")
    assert load_settings(config_file=config_of(project_root)).profile_name == "other"


def test_configured_default_is_used(project_root, monkeypatch):
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    assert load_settings(config_file=config_of(project_root)).profile_name == "test"


def test_single_profile_needs_no_default(project_root, monkeypatch):
    """只有一个 profile 时不用设默认——刚建完就能直接跑。"""
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    set_default(project_root, None)
    assert load_settings(config_file=config_of(project_root)).profile_name == PROFILE


def test_ambiguous_profile_refuses_to_guess(project_root, monkeypatch):
    """有多个 profile 又没说用哪个时绝不猜：猜错就是往别人的库里写数据。"""
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    make_profile(project_root, "other")
    set_default(project_root, None)
    with pytest.raises(ProfileNotFoundError) as exc:
        load_settings(config_file=config_of(project_root))
    assert "other" in str(exc.value) and PROFILE in str(exc.value)


def test_no_profile_at_all_points_at_new(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    (tmp_path / "config").mkdir()
    config_of(tmp_path).write_text(CONFIG_TOML.replace('default = "test"', ""), "utf-8")
    with pytest.raises(ProfileNotFoundError, match="job profile new"):
        load_settings(config_file=config_of(tmp_path))


def test_unknown_profile_lists_the_known_ones(project_root):
    with pytest.raises(ProfileNotFoundError) as exc:
        load_settings("nope", config_of(project_root))
    assert PROFILE in str(exc.value)


def test_profile_can_be_given_as_a_directory(project_root, profile_dir):
    """带路径分隔符时当目录用——临时目录与测试的逃生口。"""
    settings = load_settings(str(profile_dir), config_of(project_root))
    assert settings.profile_dir == profile_dir


def test_env_trap_name_is_rejected_with_a_hint(project_root, monkeypatch):
    """JOB_AGENT_PROFILE 会被 pydantic-settings 当成给 [profile] 整段赋 JSON，
    原始报错是一句看不懂的 JSONDecodeError，所以专门拦下来给句人话。
    """
    monkeypatch.setenv("JOB_AGENT_PROFILE", "test")
    with pytest.raises(ConfigError, match="JOB_AGENT_PROFILE_NAME"):
        load_settings(config_file=config_of(project_root))


def test_list_profiles_needs_profile_toml(project_root):
    """光有目录不算 profile：profiles/ 下的 README、残留空目录不该被算进去。"""
    (project_root / "profiles" / "空目录").mkdir()
    assert list_profiles(project_root / "profiles") == [PROFILE]


# ---------------------------------------------------------------- 隔离


def test_two_profiles_get_separate_databases(project_root, monkeypatch):
    """同一个项目根下的两个 profile，写库互不可见。这是整件事的目的。"""
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    make_profile(project_root, "other")

    with AppContext.from_settings(load_settings(PROFILE, config_of(project_root))) as a:
        a.jobs.upsert_many([make_job(1)], keyword="AI Agent")
        assert a.jobs.count() == 1

    with AppContext.from_settings(load_settings("other", config_of(project_root))) as b:
        assert b.jobs.count() == 0
        b.jobs.upsert_many([make_job(2), make_job(3)], keyword="AI Agent")

    with AppContext.from_settings(load_settings(PROFILE, config_of(project_root))) as a:
        assert a.jobs.count() == 1  # 另一个 profile 的写入没漏过来


def test_two_profiles_get_separate_inputs_and_outputs(project_root, monkeypatch):
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    make_profile(project_root, "other")
    a = load_settings(PROFILE, config_of(project_root))
    b = load_settings("other", config_of(project_root))

    for get in (
        lambda s: s.storage.database,
        lambda s: s.profile.resume,
        lambda s: s.profile.preferences,
        lambda s: s.match.rules,
        lambda s: s.match.shortlist_output,
        lambda s: s.report.output,
        lambda s: s.report.insights_dir,
        lambda s: s.agent.checkpoint,
        lambda s: s.agent.plan_output,
    ):
        assert get(a) != get(b)
        assert get(a).is_relative_to(a.profile_dir)
        assert get(b).is_relative_to(b.profile_dir)


def test_global_settings_are_shared(project_root, monkeypatch):
    """跟人无关的东西不该跟着 profile 分叉——那就成了「改了一个忘了另一个」。"""
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    make_profile(project_root, "other")
    a = load_settings(PROFILE, config_of(project_root))
    b = load_settings("other", config_of(project_root))
    assert a.liepin.rate_limit_per_min == b.liepin.rate_limit_per_min
    assert a.agent.providers == b.agent.providers
    assert a.web.frontend_dist == b.web.frontend_dist


# ---------------------------------------------------------------- 段归属


def test_profile_section_in_global_file_says_where_it_belongs(project_root):
    config_of(project_root).write_text(
        CONFIG_TOML + '\n[search]\naddress = "上海"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(PROFILE, config_of(project_root))
    assert "[search] 段属于" in str(exc.value)
    assert "profile.toml" in str(exc.value)


def test_global_section_in_profile_file_says_where_it_belongs(project_root, profile_dir):
    path = profile_dir / "profile.toml"
    path.write_text(path.read_text(encoding="utf-8") + "\n[web]\nport = 1234\n", "utf-8")
    with pytest.raises(ConfigError) as exc:
        load_settings(PROFILE, config_of(project_root))
    assert "[web] 段属于" in str(exc.value)
    assert "config/config.toml" in str(exc.value)


# ---------------------------------------------------------------- 账号


def test_profile_picks_its_own_account(project_root):
    """一个 profile 可能是「另一个人」——换人换的是 [profile].account 这一行。"""
    config_of(project_root).write_text(
        CONFIG_TOML + '\n[liepin.accounts.partner]\nuser_token = "partner-token"\n',
        encoding="utf-8",
    )
    partner = make_profile(project_root, "partner")
    text = (partner / "profile.toml").read_text(encoding="utf-8")
    (partner / "profile.toml").write_text(
        text.replace('account = "default"', 'account = "partner"'), encoding="utf-8"
    )

    assert load_settings(PROFILE, config_of(project_root)).require_token() == "test-token"
    assert load_settings("partner", config_of(project_root)).require_token() == "partner-token"


def test_unknown_account_is_rejected(project_root, profile_dir):
    path = profile_dir / "profile.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'account = "default"', 'account = "不存在的人"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(PROFILE, config_of(project_root))
    assert "不存在的人" in str(exc.value)
    assert "default" in str(exc.value)  # 顺手报出已定义的账号


def test_missing_profile_toml_falls_back_to_defaults(project_root, profile_dir):
    """profile.toml 缺了不该炸在加载期——缺什么由 config validate 逐条列。"""
    (profile_dir / "profile.toml").unlink()
    settings = load_settings(PROFILE, config_of(project_root))
    assert settings.profile_file is None
    assert settings.storage.database == profile_dir / "data" / "jobs.db"


def test_resolve_profile_returns_name_and_dir(project_root, profile_dir, monkeypatch):
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    settings = load_settings(PROFILE, config_of(project_root))
    name, directory = resolve_profile(None, _global_half(project_root), project_root / "profiles")
    assert (name, directory) == (PROFILE, profile_dir)
    assert settings.profile_dir == directory


def _global_half(root: Path):
    from job_agent.config import GlobalSettings
    from job_agent.config.loader import _read_toml

    raw = _read_toml(config_of(root))
    raw["root"] = root
    raw["config_file"] = config_of(root)
    return GlobalSettings(**raw)
