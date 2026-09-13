"""profile 这件事的内核：目录的增删查，以及里面那两份档案的读取。

一个 profile 是一个**自包含的目录**：简历、求职偏好、``profile.toml``、
数据库、产物全在里面。所以「复制一个 profile」就是复制文件夹，
「删掉一个」就是删文件夹——刻意不提供删除入口，那一下会连着简历和
几百条采集记录一起没，交给用户自己动手更诚实。

住在共享内核里而不是某一条入口下，是因为 CLI（``job profile``）与 Web
（配置页的 profile 切换）要做的是同一件事：两边各写一遍，下场是
「命令行切了、网页上没切」。

档案那半边（:func:`load_profile`）**只读文件，不解析内容**：里面写什么、
怎么组织是用户自己的事——程序一解析就等于给它定了格式，
「换个人只改 profile」这条承诺就守不住了。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from job_agent.config import (
    PROFILE_NAME,
    GlobalSettings,
    ProfilesConfig,
    Settings,
    default_config_path,
    list_profiles,
    load_settings,
    profiles_root,
    read_toml,
    templates_dir,
    write_section,
)
from job_agent.core.storage import ApplicationRepository, Database, JobRepository
from job_agent.errors import ConfigError, StorageError

#: profile 名同时是目录名，收紧到这个字符集：路径穿越、空格、大小写歧义一次挡掉
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ProfileSummary(BaseModel):
    """列表里的一行：这个 profile 是谁、填到哪一步了、攒了多少数据。

    计数是 ``None`` 而不是 0：库还没建过与库里真的一条都没有，
    要让人分得出来——前者是「还没跑过采集」，后者是「跑了但没采到」。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    directory: Path
    isDefault: bool = False
    #: 当前这个服务正在用的那个
    isCurrent: bool = False
    jobs: int | None = None
    applied: int | None = None
    hasResume: bool = False
    hasPreferences: bool = False
    #: ``[score]`` 里写了几条信号；配置读不出来就是 None
    signals: int | None = None


def summarize_profiles(
    settings: GlobalSettings, current: str | None = None
) -> list[ProfileSummary]:
    """列出所有 profile 及各自的进度。

    **不建库、不抛异常**：某个 profile 的配置写坏了，恰恰是你最想在列表里
    看见它的时候，所以读不出来的项留 ``None``，不让一个坏 profile 把整张表带崩。
    """
    directory = profiles_root(settings.root, settings)
    return [
        _summarize(settings.root, directory / name, name, settings.profiles.default, current)
        for name in list_profiles(directory)
    ]


def _summarize(
    root: Path, directory: Path, name: str, default: str | None, current: str | None
) -> ProfileSummary:
    jobs, applied = _counts(root, directory)
    return ProfileSummary(
        name=name,
        directory=directory,
        isDefault=name == default,
        isCurrent=name == current,
        jobs=jobs,
        applied=applied,
        hasResume=(directory / "resume.md").is_file(),
        hasPreferences=(directory / "preferences.md").is_file(),
        signals=_signal_count(directory),
    )


def _signal_count(directory: Path) -> int | None:
    profile_file = directory / PROFILE_NAME
    if not profile_file.is_file():
        return None
    try:
        return len(read_toml(profile_file).get("score", {}).get("signals", []))
    except ConfigError:
        return None


def _counts(root: Path, directory: Path) -> tuple[int | None, int | None]:
    """从 profile 自己的库里读行数。库还没建就是 ``None``，**不去建它**。

    库的位置走 ``load_settings``（``--profile`` 支持直接传目录）而不是拼
    ``data/jobs.db``：profile 改过 ``[storage].database`` 时这里也要跟着对。
    刻意不走 ``AppContext``：那会顺手 ``create_all`` 建出一堆空库来，
    看一眼列表不该有副作用。
    """
    try:
        database = load_settings(profile=str(directory), root=root).storage.database
    except ConfigError:  # 某个 profile 的配置坏了，不该让整张表挂掉
        return None, None
    if not database.is_file():
        return None, None
    db = Database(database)
    try:
        return JobRepository(db).count(), sum(ApplicationRepository(db).status_counts().values())
    except StorageError:
        return None, None
    finally:
        db.dispose()


def create_profile(settings: GlobalSettings, name: str, force: bool = False) -> Path:
    """从 ``config/templates/`` 拷一份出来。返回新 profile 的目录。

    模板目录的文件名就是目标文件名，**整份 copytree 过去**——不维护
    「模板 → 目标」对照表，往模板里加一个文件不用回来改代码。
    """
    if not PROFILE_NAME_RE.match(name):
        raise ConfigError(f"profile 名只能用字母、数字、- 和 _，且以字母或数字开头：{name}")

    templates = templates_dir(settings.root)
    if not templates.is_dir():
        raise ConfigError(f"缺少 profile 模板目录：{templates}")

    target = profiles_root(settings.root, settings) / name
    if target.exists() and not force:
        raise ConfigError(f"profile 已存在：{target}（要往里补缺失的文件加 --force）")

    try:
        shutil.copytree(templates, target, dirs_exist_ok=True)
        (target / "data").mkdir(exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"创建 profile 失败（{target}）：{exc}") from exc
    return target


def set_default_profile(settings: GlobalSettings, name: str) -> Path:
    """把 ``[profiles].default`` 改成 ``name``，返回写了哪个文件。

    只动那一行（模板里它是注释掉的，就地取消注释）——``config/config.toml``
    里的注释是用户唯一的说明书，见 :mod:`job_agent.config.writer`。
    """
    directory = profiles_root(settings.root, settings)
    if name not in list_profiles(directory):
        known = "、".join(list_profiles(directory)) or "（一个都没有）"
        raise ConfigError(f"profile 不存在：{directory / name}\n  已有的：{known}")

    config_file = settings.config_file or default_config_path(settings.root)
    updated = ProfilesConfig(**{**settings.profiles.model_dump(), "default": name})
    return write_section(config_file, "profiles", updated)


def load_profile(settings: Settings) -> tuple[str, str]:
    """读简历与求职偏好原文。缺文件直接报错——没有档案的判断毫无意义。"""
    texts: list[str] = []
    for label, path in (
        ("简历", settings.profile.resume),
        ("求职偏好", settings.profile.preferences),
    ):
        if not path.is_file():
            raise ConfigError(
                f"{label}文件不存在：{path}\n  先在 Claude Code 里跑 `/job-init` 生成，"
                "或手工按 config/templates/ 下的模板填写。"
            )
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ConfigError(f"{label}文件是空的：{path}")
        texts.append(content)
    return texts[0], texts[1]
