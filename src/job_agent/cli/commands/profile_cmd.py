"""``job profile``：管理 profile——一个用户或一种求职场景。

一个 profile 是一个自包含的目录：简历、求职偏好、profile.toml（搜索关键词 +
``[score]`` 匹配信号表）、
数据库、产物全在里面。所以「复制一个 profile」就是复制文件夹，
「删掉一个 profile」就是删文件夹——这里刻意不提供 ``rm``：
那一下会连着简历和几百条采集记录一起没，交给用户自己动手更诚实。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.config import (
    GlobalSettings,
    default_config_path,
    find_config_file,
    find_project_root,
    list_profiles,
    load_settings,
    profiles_root,
    templates_dir,
)
from job_agent.config.loader import _read_toml
from job_agent.core.storage import ApplicationRepository, Database, JobRepository
from job_agent.errors import ConfigError, StorageError

app = typer.Typer(add_completion=False, no_args_is_help=True)

#: profile 名同时是目录名，收紧到这个字符集：路径穿越、空格、大小写歧义一次挡掉
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _global_settings(root: Path) -> GlobalSettings:
    """只读全局那一半——``job profile new`` 得在还没有任何 profile 时就能跑，
    所以不能走 ``load_settings``（它会因为定位不到 profile 而报错）。
    """
    config_file = find_config_file(root)
    raw = _read_toml(config_file) if config_file else {}
    raw["root"] = root
    raw["config_file"] = config_file
    return GlobalSettings(**raw)


@app.command("list", help="列出所有 profile。")
def list_cmd() -> None:
    root = find_project_root()
    settings = _global_settings(root)
    profiles_dir = profiles_root(root, settings)
    names = list_profiles(profiles_dir)
    if not names:
        echo_warn(f"还没有任何 profile（{profiles_dir}）")
        typer.echo("跑 `job profile new <名字>` 建一个。")
        return

    typer.echo(f"{profiles_dir}\n")
    header = f"{'':<2}{'名字':<16}{'职位':>8}{'已投':>6}  简历  偏好  信号"
    typer.secho(header, bold=True)
    for name in names:
        mark = "→" if name == settings.profiles.default else " "
        directory = profiles_dir / name
        jobs, applied = _counts(root, directory)
        typer.echo(
            f"{mark} {name:<16}{jobs:>8}{applied:>6}"
            f"  {_flag(directory / 'resume.md')}    {_flag(directory / 'preferences.md')}"
            f"   {_signals(directory):>3}"
        )
    if settings.profiles.default is None and len(names) > 1:
        typer.echo(
            "\n没有设默认 profile：每条命令都得带 --profile，"
            "或跑 `job profile use <名字>`。"
        )


def _flag(path: Path) -> str:
    return "✓" if path.is_file() else "×"


def _signals(directory: Path) -> str:
    """这个 profile 的 ``[score]`` 里写了几条信号。

    读文件而不是走 ``load_settings``：列表要能把配置坏掉的 profile 也列出来
    （那正是你想看见它的时候），所以解析失败只显示 ``×``，不抛。
    """
    profile_file = directory / "profile.toml"
    if not profile_file.is_file():
        return "×"
    try:
        signals = _read_toml(profile_file).get("score", {}).get("signals", [])
    except ConfigError:
        return "×"
    return str(len(signals)) if signals else "×"


def _counts(root: Path, directory: Path) -> tuple[str, str]:
    """从 profile 自己的库里读行数。库还没建就显示 ``-``，不去建它。

    库的位置走 ``load_settings``（``--profile`` 支持直接传目录）而不是拼
    ``data/jobs.db``：profile 改过 ``[storage].database`` 时这里也要跟着对。
    刻意不走 ``AppContext``：那会顺手 ``create_all`` 建出一堆空库来，
    ``job profile list`` 只是看一眼，不该有副作用。
    """
    try:
        database = load_settings(profile=str(directory), root=root).storage.database
    except ConfigError:  # 某个 profile 的配置坏了，不该让整个 list 挂掉
        return "?", "?"
    if not database.is_file():
        return "-", "-"
    db = Database(database)
    try:
        jobs = JobRepository(db).count()
        applied = sum(ApplicationRepository(db).status_counts().values())
        return str(jobs), str(applied)
    except StorageError:
        return "?", "?"
    finally:
        db.dispose()


@app.command("new", help="新建一个 profile（从 config/templates/ 拷模板）。")
def new(
    name: Annotated[str, typer.Argument(help="profile 名字，同时是目录名。")],
    force: Annotated[bool, typer.Option("--force", help="目录已存在时也往里补文件。")] = False,
) -> None:
    if not _NAME_RE.match(name):
        raise ConfigError(f"profile 名只能用字母、数字、- 和 _，且以字母或数字开头：{name}")

    root = find_project_root()
    settings = _global_settings(root)
    templates = templates_dir(root)
    if not templates.is_dir():
        raise ConfigError(f"缺少 profile 模板目录：{templates}")

    target = profiles_root(root, settings) / name
    if target.exists() and not force:
        raise ConfigError(f"profile 已存在：{target}（要往里补缺失的文件加 --force）")

    # 模板目录的文件名就是目标文件名，整份拷过去即可——不维护「模板 → 目标」对照表
    shutil.copytree(templates, target, dirs_exist_ok=True)
    (target / "data").mkdir(exist_ok=True)
    echo_ok(f"已创建 profile：{target}")

    if settings.profiles.default is None and _write_default(root, name):
        echo_ok(f'已设为默认 profile（[profiles].default = "{name}"）')

    typer.echo(
        f"\n下一步：让 Claude 跑 `/job-init` 带你把简历、求职偏好与关键词填完"
        f"（会写进 {target}），或自己照文件里的注释改；"
        f"填好后 `job -p {name} config validate` 自检。\n"
        "猎聘 token 与模型 key 不在这里——它们跟人无关，住全局 config/config.toml。"
    )


@app.command("use", help="把某个 profile 设为默认（不带 --profile 时用它）。")
def use(name: Annotated[str, typer.Argument(help="profile 名字。")]) -> None:
    root = find_project_root()
    settings = _global_settings(root)
    profiles_dir = profiles_root(root, settings)
    if name not in list_profiles(profiles_dir):
        raise ConfigError(
            f"profile 不存在：{profiles_dir / name}\n"
            f"  已有的：{'、'.join(list_profiles(profiles_dir)) or '（一个都没有）'}"
        )
    if not _write_default(root, name):
        raise ConfigError(
            f"没能改写 {default_config_path(root)}：请手动加上\n\n"
            f'  [profiles]\n  default = "{name}"'
        )
    echo_ok(f"默认 profile 已设为 {name}")


def _write_default(root: Path, name: str) -> bool:
    """定点改写全局配置里 ``[profiles].default`` 那一行。

    刻意不引 TOML 写库：写回会把整个文件的注释与排版重排一遍，而
    ``config/config.toml`` 里那些注释是用户唯一的说明书。只动一行，其余原样。
    """
    path = default_config_path(root)
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            if in_section:  # 走出 [profiles] 段还没找到 default，就在段末补一行
                lines.insert(i, f'default = "{name}"\n')
                path.write_text("".join(lines), encoding="utf-8")
                return True
            in_section = stripped == "[profiles]"
            continue
        if in_section and re.match(r"^#?\s*default\s*=", stripped):
            lines[i] = f'default = "{name}"\n'
            path.write_text("".join(lines), encoding="utf-8")
            return True
    if in_section:  # [profiles] 是最后一段
        lines.append(f'default = "{name}"\n')
    else:
        lines.append(f'\n[profiles]\ndefault = "{name}"\n')
    path.write_text("".join(lines), encoding="utf-8")
    return True


@app.command("path", help="打印当前（或指定）profile 的目录。")
def path_cmd(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    typer.echo(state.context().settings.profile_dir)
