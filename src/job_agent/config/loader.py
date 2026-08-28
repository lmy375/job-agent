"""配置加载：定位项目根 → 读 TOML → 叠加环境变量 → 解析路径 → 校验。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from job_agent.config.models import Settings
from job_agent.errors import ConfigError

#: 指定项目根目录（含 config/ 的那一层）
ENV_HOME = "JOB_AGENT_HOME"
#: 直接指定配置文件路径
ENV_CONFIG = "JOB_AGENT_CONFIG"

CONFIG_DIR_NAME = "config"
CONFIG_NAME = "config.toml"
EXAMPLE_NAME = "config.example.toml"
ENV_FILE_NAME = ".env"

#: 简单标量的环境变量覆盖：环境变量名 -> 配置路径
_SCALAR_OVERRIDES: dict[str, tuple[str, ...]] = {
    "JOB_AGENT_DB": ("storage", "database"),
    "JOB_AGENT_LOG_LEVEL": ("logging", "level"),
    "JOB_AGENT_WEB_HOST": ("web", "host"),
    "JOB_AGENT_WEB_PORT": ("web", "port"),
    "LIEPIN_BASE_URL": ("liepin", "base_url"),
    "LIEPIN_TIMEOUT": ("liepin", "timeout"),
}

#: 需要相对项目根解析的路径字段
_PATH_FIELDS: tuple[tuple[str, str], ...] = (
    ("profile", "resume"),
    ("profile", "preferences"),
    ("storage", "database"),
    ("match", "rules"),
    ("match", "shortlist_output"),
    ("report", "output"),
    ("report", "insights_dir"),
    ("web", "frontend_dist"),
    ("logging", "file"),
)


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
    """用户配置文件应有的位置（无论是否存在）。"""
    return root / CONFIG_DIR_NAME / CONFIG_NAME


def example_config_path(root: Path) -> Path:
    return root / CONFIG_DIR_NAME / EXAMPLE_NAME


def env_file_path(root: Path) -> Path:
    return root / CONFIG_DIR_NAME / ENV_FILE_NAME


def find_config_file(root: Path) -> Path | None:
    """按优先级找配置文件：``JOB_AGENT_CONFIG`` → config.toml → config.example.toml。

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


def load_settings(config_file: Path | None = None, root: Path | None = None) -> Settings:
    """加载配置。

    :param config_file: 显式指定配置文件（对应 ``--config``）
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

    raw: dict[str, Any] = {}
    if config_file is not None:
        raw = _read_toml(config_file)

    _apply_env_overrides(raw)
    raw["root"] = resolved_root
    raw["config_file"] = config_file
    raw["token"] = _load_token(resolved_root)

    try:
        settings = Settings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc, config_file)) from exc

    return _resolve_paths(settings, resolved_root)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 TOML（{path}）：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"配置文件读取失败（{path}）：{exc}") from exc


def _load_token(root: Path) -> str | None:
    """token 取值顺序：环境变量 > config/.env。

    环境变量优先，便于 CI / 临时切换账号时不改文件。
    """
    from_env = (os.environ.get("LIEPIN_USER_TOKEN") or "").strip()
    if from_env:
        return from_env
    return _read_env_file(env_file_path(root)).get("LIEPIN_USER_TOKEN")


def _read_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析：``KEY=VALUE``，忽略空行与 ``#`` 注释，去掉包裹的引号。

    刻意不引入 python-dotenv：需要的语义就这么点，而多一个依赖就多一处行为差异。
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


def _apply_env_overrides(raw: dict[str, Any]) -> None:
    for env_name, (section, field) in _SCALAR_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value is None or not value.strip():
            continue
        raw.setdefault(section, {})[field] = value.strip()


def _resolve_paths(settings: Settings, root: Path) -> Settings:
    """把配置里的相对路径按项目根解析成绝对路径。

    在加载时一次性解析掉，这样后续代码永远不需要关心「当前工作目录是哪」——
    Web 服务与后台线程里的 cwd 未必是项目根。
    """
    for section, field in _PATH_FIELDS:
        node = getattr(settings, section)
        value: Path | None = getattr(node, field)
        if value is None:
            continue
        if not value.is_absolute():
            setattr(node, field, (root / value).resolve())
        else:
            setattr(node, field, value.resolve())
    return settings


def _format_validation_error(exc: ValidationError, config_file: Path | None) -> str:
    where = f"（{config_file}）" if config_file else ""
    lines = [f"配置校验失败{where}："]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"] if p not in ("root", "config_file"))
        msg = err["msg"]
        if err["type"] == "extra_forbidden":
            msg = "未知配置项（请对照 config/config.example.toml 检查拼写）"
        lines.append(f"  - {loc or '<顶层>'}: {msg}")
    return "\n".join(lines)
