"""配置加载：定位项目根 → 定位 profile → 读两份 TOML → 校验 → 解析路径。

配置有两处落盘，**段名完全不重叠**：

- ``config/config.toml``——全局，管「怎么连」（猎聘账号密钥、限速、模型接入点、
  Web 端口、日志）。所有 profile 共享一份。
- ``profiles/<name>/profile.toml``——管「找什么」（简历、偏好、搜索条件、
  打分门槛与匹配信号表）。一个 profile = 一个用户或一种求职场景，
  输入、配置、产物、数据库全在这个目录里，互不可见。

分层规则全部交给 pydantic-settings，这里不写任何解析逻辑：
环境变量（``JOB_AGENT_<节>__<字段>``）> TOML。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_settings import SettingsError

from job_agent.config.models import GlobalSettings, ProfileSettings, Settings
from job_agent.errors import ConfigError, ProfileNotFoundError

#: 指定项目根目录（含 config/ 的那一层）
ENV_HOME = "JOB_AGENT_HOME"
#: 直接指定全局配置文件路径
ENV_CONFIG = "JOB_AGENT_CONFIG"
#: 指定用哪个 profile。刻意不叫 JOB_AGENT_PROFILE：那个名字会被
#: pydantic-settings 当成「给 [profile] 整段赋一个 JSON 值」，
#: 报出来是一句看不懂的 JSONDecodeError
ENV_PROFILE = "JOB_AGENT_PROFILE_NAME"
#: 上面那个陷阱的名字，专门用来拦下来给句人话
ENV_PROFILE_TRAP = "JOB_AGENT_PROFILE"

CONFIG_DIR_NAME = "config"
CONFIG_NAME = "config.toml"
EXAMPLE_NAME = "config.example.toml"
TEMPLATES_DIR_NAME = "templates"
PROFILE_NAME = "profile.toml"

#: 相对**项目根**解析的路径字段（跟 profile 无关的东西）
_ROOT_PATH_FIELDS: tuple[tuple[str, str], ...] = (
    ("web", "frontend_dist"),
    ("logging", "file"),
)

#: 相对**当前 profile 目录**解析的路径字段。
#: ``agent`` 的两个字段写在全局文件里，但它们是每次运行的产物，
#: 必须跟着 profile 走——否则几个 profile 会互相覆盖投递计划。
_PROFILE_PATH_FIELDS: tuple[tuple[str, str], ...] = (
    ("profile", "resume"),
    ("profile", "preferences"),
    ("profile", "score_appeal_prompt"),
    ("profile", "score_fit_prompt"),
    ("storage", "database"),
    ("agent", "checkpoint"),
    ("agent", "plan_output"),
)

#: 段名 → 它属于哪个文件。放错文件是这次拆分之后最容易犯的错，
#: 报错时要直接说清「它该在哪」，而不是笼统的「未知配置项」
_GLOBAL_SECTIONS = frozenset(GlobalSettings.model_fields) - {"root", "config_file"}
_PROFILE_SECTIONS = frozenset(ProfileSettings.model_fields)

#: 报错时「另一个文件」是什么：(它的段名集合, 怎么称呼它)
_BELONGS_TO_PROFILE = (_PROFILE_SECTIONS, "profile 文件 profiles/<名字>/profile.toml")
_BELONGS_TO_GLOBAL = (_GLOBAL_SECTIONS, "全局文件 config/config.toml")


def find_project_root(start: Path | None = None) -> Path:
    """定位项目根：``JOB_AGENT_HOME`` → 从 ``start`` 逐级向上找 ``config/`` → 包自身所在仓库。

    以「向上查找」为主是为了让 ``job`` 命令在子目录里也能跑对，
    这和 git / npm 的行为一致。
    """
    env_home = os.environ.get(ENV_HOME)
    if env_home:
        root = Path(env_home).expanduser().resolve()
        if not root.is_dir():
            raise ConfigError(f"{ENV_HOME} 指向的目录不存在：{root}")
        return root

    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_DIR_NAME).is_dir():
            return candidate

    # 从源码目录运行且 cwd 在项目外时的兜底：src/job_agent/config/loader.py -> 仓库根
    repo_root = Path(__file__).resolve().parents[3]
    if (repo_root / CONFIG_DIR_NAME).is_dir():
        return repo_root
    return here


def default_config_path(root: Path) -> Path:
    """全局配置文件应有的位置（无论是否存在）。"""
    return root / CONFIG_DIR_NAME / CONFIG_NAME


def example_config_path(root: Path) -> Path:
    return root / CONFIG_DIR_NAME / EXAMPLE_NAME


def templates_dir(root: Path) -> Path:
    """新建 profile 用的模板目录。整份拷过去就是一个新 profile。"""
    return root / CONFIG_DIR_NAME / TEMPLATES_DIR_NAME


def find_config_file(root: Path) -> Path | None:
    """按优先级找全局配置文件：``JOB_AGENT_CONFIG`` → config.toml → config.example.toml。

    允许回落到模板是刻意的：新克隆下来不做任何初始化也能跑起来看效果。
    """
    env_config = os.environ.get(ENV_CONFIG)
    if env_config:
        path = Path(env_config).expanduser()
        if not path.is_file():
            raise ConfigError(f"{ENV_CONFIG} 指向的配置文件不存在：{path}")
        return path.resolve()
    for candidate in (default_config_path(root), example_config_path(root)):
        if candidate.is_file():
            return candidate
    return None


def profiles_root(root: Path, settings: GlobalSettings) -> Path:
    """profile 们的存放目录（``[profiles].dir``，默认 ``<root>/profiles``）。"""
    configured = settings.profiles.dir
    return configured.resolve() if configured.is_absolute() else (root / configured).resolve()


def list_profiles(profiles_dir: Path) -> list[str]:
    """已存在的 profile 名（= 目录名），按字母序。

    判据是目录里有 ``profile.toml``：这样 ``profiles/`` 下放个 README
    或者残留的空目录都不会被当成 profile。
    """
    if not profiles_dir.is_dir():
        return []
    return sorted(
        entry.name for entry in profiles_dir.iterdir() if (entry / PROFILE_NAME).is_file()
    )


def resolve_profile(
    profile: str | None, settings: GlobalSettings, profiles_dir: Path
) -> tuple[str, Path]:
    """定位当前 profile：``--profile`` → ``JOB_AGENT_PROFILE`` → ``[profiles].default``
    → 只有一个 profile 时就是它 → 报错。

    「只有一个就用它」是给单 profile 的常见情况兜底：刚 ``job profile new`` 完
    还没设 default 也能直接跑。有两个及以上时绝不猜，必须显式指定。
    """
    explicit = profile or os.environ.get(ENV_PROFILE) or None
    if explicit:
        # 带路径分隔符的当成目录用（测试与临时目录的逃生口），否则当名字
        if os.sep in explicit or "/" in explicit:
            path = Path(explicit).expanduser().resolve()
            if not path.is_dir():
                raise ProfileNotFoundError(f"profile 目录不存在：{path}")
            return path.name, path
        path = profiles_dir / explicit
        if not path.is_dir():
            raise ProfileNotFoundError(_missing_profile_message(explicit, profiles_dir))
        return explicit, path

    configured = settings.profiles.default
    if configured:
        path = profiles_dir / configured
        if not path.is_dir():
            raise ProfileNotFoundError(
                _missing_profile_message(
                    configured, profiles_dir, source=f"[profiles].default（{settings.config_file}）"
                )
            )
        return configured, path

    existing = list_profiles(profiles_dir)
    if len(existing) == 1:
        return existing[0], profiles_dir / existing[0]
    if not existing:
        raise ProfileNotFoundError(
            f"还没有任何 profile（{profiles_dir}）。\n"
            "  跑 `job profile new <名字>` 建一个——一个 profile 就是一个人 / 一种求职场景，"
            "简历、关键词、数据库都在它自己的目录里。"
        )
    raise ProfileNotFoundError(
        f"有 {len(existing)} 个 profile，但没说用哪个：{'、'.join(existing)}\n"
        "  加 `--profile <名字>`，或跑 `job profile use <名字>` 设成默认。"
    )


def _missing_profile_message(name: str, profiles_dir: Path, source: str = "") -> str:
    where = f"（来自 {source}）" if source else ""
    existing = list_profiles(profiles_dir)
    known = "、".join(existing) if existing else "（一个都没有）"
    return (
        f"profile 不存在：{name}{where}\n"
        f"  目录：{profiles_dir / name}\n"
        f"  已有的 profile：{known}\n"
        f"  新建：job profile new {name}"
    )


def load_settings(
    profile: str | None = None,
    config_file: Path | None = None,
    root: Path | None = None,
) -> Settings:
    """加载配置。

    :param profile: 用哪个 profile（对应 ``--profile``），默认按上面的优先级定位
    :param config_file: 显式指定全局配置文件（对应 ``--config``）
    :param root: 显式指定项目根，默认自动查找
    """
    if config_file is not None:
        config_file = Path(config_file).expanduser()
        if not config_file.is_file():
            raise ConfigError(f"配置文件不存在：{config_file}")
        config_file = config_file.resolve()
        # 显式给了 config/xxx.toml 时，项目根取它的上两层
        if root is None and config_file.parent.name == CONFIG_DIR_NAME:
            root = config_file.parent.parent

    resolved_root = (root or find_project_root()).resolve()
    if config_file is None:
        config_file = find_config_file(resolved_root)

    if os.environ.get(ENV_PROFILE_TRAP) is not None:
        raise ConfigError(
            f"{ENV_PROFILE_TRAP} 不是有效的环境变量（它会被当成给 [profile] 整段赋值）。"
            f"选 profile 请用 {ENV_PROFILE}，或命令行的 --profile。"
        )

    raw: dict[str, Any] = _read_toml(config_file) if config_file is not None else {}
    raw["root"] = resolved_root
    raw["config_file"] = config_file
    try:
        # 走 BaseSettings 的构造（而不是 model_validate），环境变量覆盖才会生效
        global_settings = GlobalSettings(**raw)
    except SettingsError as exc:
        raise ConfigError(f"环境变量解析失败：{exc}") from exc
    except ValidationError as exc:
        raise ConfigError(
            _format_validation_error(exc, config_file, *_BELONGS_TO_PROFILE)
        ) from exc

    profiles_dir = profiles_root(resolved_root, global_settings)
    profile_name, profile_dir = resolve_profile(profile, global_settings, profiles_dir)

    # profile.toml 缺失不报错：目录在就够了，字段全走默认值。
    # 缺什么由 `job config validate` 逐条列出来，这里不抢它的活
    candidate = profile_dir / PROFILE_NAME
    profile_file = candidate if candidate.is_file() else None
    profile_raw = _read_toml(candidate) if profile_file else {}
    try:
        profile_settings = ProfileSettings(**profile_raw)
    except SettingsError as exc:
        raise ConfigError(f"环境变量解析失败：{exc}") from exc
    except ValidationError as exc:
        raise ConfigError(
            _format_validation_error(exc, profile_file, *_BELONGS_TO_GLOBAL)
        ) from exc

    try:
        settings = Settings(
            root=resolved_root,
            config_file=config_file,
            profile_name=profile_name,
            profile_dir=profile_dir,
            profile_file=profile_file,
            profiles=global_settings.profiles,
            liepin=global_settings.liepin,
            detail=global_settings.detail,
            agent=global_settings.agent,
            llm_score=global_settings.llm_score,
            web=global_settings.web,
            logging=global_settings.logging,
            profile=profile_settings.profile,
            search=profile_settings.search,
            storage=profile_settings.storage,
            score=profile_settings.score,
        )
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc, config_file, frozenset(), "")) from exc

    return _resolve_paths(settings, resolved_root, profile_dir)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 TOML（{path}）：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"配置文件读取失败（{path}）：{exc}") from exc


def _resolve_paths(settings: Settings, root: Path, profile_dir: Path) -> Settings:
    """把配置里的相对路径解析成绝对路径：profile 侧相对 profile 目录，其余相对项目根。

    在加载时一次性解析掉，这样后续代码永远不需要关心「当前工作目录是哪」——
    Web 服务与后台线程里的 cwd 未必是项目根。
    """
    for base, fields in ((root, _ROOT_PATH_FIELDS), (profile_dir, _PROFILE_PATH_FIELDS)):
        for section, field in fields:
            node = getattr(settings, section)
            value: Path | None = getattr(node, field)
            if value is None:
                continue
            resolved = value if value.is_absolute() else base / value
            setattr(node, field, resolved.resolve())
    return settings


def _format_validation_error(
    exc: ValidationError,
    config_file: Path | None,
    other_sections: frozenset[str],
    other_file: str,
) -> str:
    """把 pydantic 的报错翻译成人话。

    ``other_sections`` / ``other_file`` 说的是「另一个配置文件」：段放错文件时
    直接指出它该在哪，而不是让人对着「未知配置项」猜——拆成两个文件之后，
    这是最容易犯、也最难自己看出来的错。
    """
    where = f"（{config_file}）" if config_file else ""
    lines = [f"配置校验失败{where}："]
    for err in exc.errors():
        parts = [str(p) for p in err["loc"] if p not in ("root", "config_file")]
        loc = ".".join(parts)
        msg = err["msg"]
        if err["type"] == "extra_forbidden":
            if parts and parts[0] in other_sections:
                msg = f"[{parts[0]}] 段属于{other_file}，不该写在这里"
            else:
                msg = "未知配置项（请对照 config/config.example.toml 检查拼写）"
        lines.append(f"  - {loc or '<顶层>'}: {msg}")
    return "\n".join(lines)
