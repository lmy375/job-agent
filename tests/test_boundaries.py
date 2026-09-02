"""架构规则的守卫：执行路线的依赖边界 + 「结构体一律 pydantic」。

仓库有两条执行路线：``cli/``+``web/``（skill / Claude Code 驱动）与
``agent/``（LangGraph 独立执行）。二者只允许依赖共享内核
（``core/``、``config/``、``context`` 等顶层模块），互相 import 即架构错误。

唯一的豁免是 ``cli/commands/agent_cmd.py``——``job agent`` 这个入口总得有人
把两边接起来。它只许 import ``job_agent.agent.runner``（把选项翻成
``AgentRunOptions`` 就交出去），一行流程逻辑都不写；豁免按**文件名 + 被 import
的模块名**双重钉死，防止它慢慢变成第二条 agent 实现。

另一条硬规则见 CLAUDE.md：结构体一律 pydantic ``BaseModel``，
不许 ``@dataclass`` / ``NamedTuple``——两套写法并存，读代码的人每次都要先
分辨「这个能不能校验、怎么序列化」。

纯 AST 扫描、不真正 import——agent extra 没装时这组测试也必须能跑。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "job_agent"

#: 唯一的跨路线入口：文件 -> 它被允许 import 的模块（精确匹配，不含子模块）
ALLOWED_BRIDGE: dict[str, tuple[str, ...]] = {
    "cli/commands/agent_cmd.py": ("job_agent.agent.runner",),
}

#: 包 -> 不许 import 的前缀
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "cli": ("job_agent.agent",),
    "web": ("job_agent.agent",),
    "agent": ("job_agent.cli", "job_agent.web"),
    # 共享内核不许反向依赖任何一条执行路线
    "core": ("job_agent.cli", "job_agent.web", "job_agent.agent"),
    "config": ("job_agent.cli", "job_agent.web", "job_agent.agent"),
}


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_route_isolation(package: str) -> None:
    banned = FORBIDDEN[package]
    offenders: list[str] = []
    for file in sorted((SRC / package).rglob("*.py")):
        allowed = ALLOWED_BRIDGE.get(file.relative_to(SRC).as_posix(), ())
        bad = {
            imp
            for imp in _imports_of(file)
            if any(imp == b or imp.startswith(b + ".") for b in banned)
            and imp not in allowed
        }
        if bad:
            offenders.append(f"{file.relative_to(SRC.parent)} -> {sorted(bad)}")
    assert not offenders, (
        f"依赖边界被打破：job_agent.{package} 不许 import {list(banned)}。\n"
        "两条执行路线（cli+web / agent）互相独立，可复用的逻辑请下沉到 core/。\n"
        f"唯一的豁免是 {list(ALLOWED_BRIDGE)}，且只能 import 各自允许的那个模块。\n"
        + "\n".join(offenders)
    )


def test_bridge_stays_thin() -> None:
    """豁免文件只许薄薄一层：翻选项、调 run、返回退出码。

    钉住行数是刻意的——它一旦开始长，就说明流程逻辑正在往 cli/ 里渗。
    """
    bridge = SRC / "cli" / "commands" / "agent_cmd.py"
    body = [
        line for line in bridge.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(body) < 80, (
        f"{bridge.name} 有 {len(body)} 行有效代码，太厚了。"
        "它只该把命令行选项翻成 AgentRunOptions 再交给 agent/runner.py，"
        "流程逻辑一律留在 agent/ 里。"
    )


#: 结构体只许用 pydantic：这几个名字出现即违规
BANNED_STRUCT_DECORATORS = ("dataclass", "dataclasses.dataclass")
BANNED_STRUCT_BASES = ("NamedTuple", "typing.NamedTuple")


def _name_of(node: ast.expr) -> str:
    """把 ``dataclass`` / ``dataclasses.dataclass`` / ``dataclass(slots=True)``
    都还原成可比较的点分名字。"""
    if isinstance(node, ast.Call):
        return _name_of(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_name_of(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def test_no_dataclass_or_namedtuple() -> None:
    """结构体一律 pydantic BaseModel（CLAUDE.md 硬规则）。"""
    offenders: list[str] = []
    for file in sorted(SRC.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bad = [
                _name_of(d) for d in node.decorator_list
                if _name_of(d) in BANNED_STRUCT_DECORATORS
            ]
            bad += [
                _name_of(b) for b in node.bases if _name_of(b) in BANNED_STRUCT_BASES
            ]
            if bad:
                offenders.append(f"{file.relative_to(SRC.parent)}:{node.name} -> {sorted(bad)}")
    assert not offenders, (
        "结构体一律用 pydantic BaseModel，不要 @dataclass / NamedTuple。\n"
        "需要装非 pydantic 类型（连接、线程原语）时用 "
        "model_config = ConfigDict(arbitrary_types_allowed=True)。\n"
        + "\n".join(offenders)
    )


def test_config_files_have_no_overlapping_sections() -> None:
    """两个配置文件的段名不许重叠——这是 profile 隔离的核心不变量。

    重叠了就意味着同一个配置项能写在两处，下场一定是「改了一个忘了另一个」；
    环境变量覆盖也会失去唯一解（``JOB_AGENT_<段>__<字段>`` 该落到哪一边）。
    这条靠测试钉住，而不是靠记得。
    """
    from job_agent.config import GlobalSettings, ProfileSettings, Settings

    # root / config_file 是 loader 注入的，不是 TOML 里的段
    injected = {"root", "config_file"}
    global_sections = set(GlobalSettings.model_fields) - injected
    profile_sections = set(ProfileSettings.model_fields)

    overlap = global_sections & profile_sections
    assert not overlap, (
        f"这些段同时出现在全局配置与 profile 配置里：{sorted(overlap)}。"
        "同一个段只能属于一个文件——要么整段搬到一边，要么拆成两个不同名的段。"
    )

    # 组装体必须正好是两个半边的并集，不多不少：
    # 少了就是某个段加了却没接上，多了就是有字段绕过了「它属于哪个文件」这个问题
    composed = set(Settings.model_fields) - injected - {
        "profile_name", "profile_dir", "profile_file"
    }
    assert composed == global_sections | profile_sections
