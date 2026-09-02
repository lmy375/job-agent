"""把改动写回 ``profiles/<名>/profile.toml``（搜索关键词 + ``[score]`` 打分逻辑）。

Web 管理台的「配置」页能直接改这两样，但**配置仍然只有文件这一处落盘**：
页面上按保存就是改这个文件，改完重新 ``load_settings()`` 一遍。
所以不存在「网页上改了但下次 CLI 跑的是另一套」——CLI、Web、agent 三条路
读的永远是同一份 TOML。

刻意不引 TOML 写库（tomlkit 之类）：写回会把整个文件的注释与排版重排一遍，
而 profile.toml 里那些注释是用户唯一的说明书。这里只做**定点替换**：

- :func:`write_keywords` 只动 ``[search]`` 里 ``keywords = [...]`` 那几行
  （数组里注释掉的候选词原样留着——那是「库里存量数据是怎么来的」的线索）；
- :func:`write_score` 整段重写 ``[score]``（含 ``[score.require]`` 与全部
  ``[[score.signals]]``）：段内注释保不住，但 ``[score]`` **之上**那一大块
  说明注释不在替换范围里，不受影响。

其余每一个字节原样保留。同一个思路见 ``cli/commands/profile_cmd.py``
的 ``_write_default``。

正则一律渲染成 **TOML 字面量字符串（单引号）**：双引号里 ``\\b`` 是「退格符」
转义，会静默变成匹配不上任何东西的正则（见 ``config/models.py`` 的
``_check_pattern``）。值里本身带单引号时才退回双引号，并转义反斜杠。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

from job_agent.config.models import ScoreConfig
from job_agent.errors import ConfigError

#: 控制字符不能出现在字面量字符串里，只能退回双引号形式
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def write_keywords(profile_file: Path, keywords: Sequence[str]) -> Path:
    """改写 ``[search].keywords``。数组顺序 = 优先级，原样写回。

    ``[search]`` 段或 ``keywords`` 键不存在时补上；文件不存在时新建
    （profile.toml 缺失是合法状态，字段全走默认值）。
    """
    lines = _read_lines(profile_file)
    section = _section_span(lines, "search")
    if section is None:
        block = [*_separator(lines), "[search]\n", *_render_keywords(keywords, [])]
        return _write_lines(profile_file, [*lines, *block])

    start, end = section
    array = _array_span(lines, start + 1, end, "keywords")
    if array is None:
        # 段里还没有这个键：补在段末（段与段之间的空行由原文件保持）
        return _write_lines(
            profile_file, [*lines[:end], *_render_keywords(keywords, []), *lines[end:]]
        )

    first, last = array
    kept = _comment_lines(lines[first + 1 : last - 1])
    block = _render_keywords(keywords, kept)
    return _write_lines(profile_file, [*lines[:first], *block, *lines[last:]])


def write_score(profile_file: Path, score: ScoreConfig) -> Path:
    """整段重写 ``[score]``（含 ``[score.require]`` 与全部 ``[[score.signals]]``）。

    整段而不是逐项改：信号是一个**数组**，改一条的位置会牵动其余几十条的行号，
    定点替换的代价远高于把这一段重新渲染一遍。
    """
    lines = _read_lines(profile_file)
    block = _render_score(score)
    section = _section_span(lines, "score")
    if section is None:
        return _write_lines(profile_file, [*lines, *_separator(lines), *block])
    start, end = section
    return _write_lines(profile_file, [*lines[:start], *block, *lines[end:]])


# ------------------------------------------------------------------ 文件读写


def _read_lines(profile_file: Path) -> list[str]:
    if not profile_file.is_file():
        return []
    try:
        return profile_file.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        raise ConfigError(f"配置文件读取失败（{profile_file}）：{exc}") from exc


def _write_lines(profile_file: Path, lines: list[str]) -> Path:
    """整份原子替换：同目录临时文件 + rename。

    直接覆盖的话，写到一半出错（磁盘满、进程被杀）会留下一个残缺的
    profile.toml——那意味着简历还在、信号表没了，而且看不出来。
    """
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    temp = profile_file.with_name(f"{profile_file.name}.tmp")
    try:
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text("".join(lines), encoding="utf-8")
        temp.replace(profile_file)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise ConfigError(f"配置文件写入失败（{profile_file}）：{exc}") from exc
    return profile_file


# ------------------------------------------------------------------ 定位


def _separator(lines: list[str]) -> list[str]:
    """往文件末尾追加一段前的空行。文件本来是空的就不要那行。"""
    return ["\n"] if lines else []


def _header_name(line: str) -> str | None:
    """这一行是表头（``[x]`` / ``[[x.y]]``）就返回点分表名，否则 None。"""
    stripped = line.strip()
    if not stripped.startswith("["):
        return None
    name = stripped.removeprefix("[[").removeprefix("[").split("]", 1)[0].strip()
    return name or None


def _section_span(lines: list[str], section: str) -> tuple[int, int] | None:
    """``[section]`` 连同它的子表占的行区间 ``[start, end)``；没有就 None。

    末尾**不吃掉**紧贴下一个表头的注释与空行——那些注释是写给下一段的，
    连着替换掉等于顺手删了别人的说明。
    """
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        name = _header_name(line)
        if name is None:
            continue
        belongs = name == section or name.startswith(f"{section}.")
        if start is None:
            if belongs:
                start = index
            continue
        if not belongs:
            end = index
            break
    if start is None:
        return None
    while end > start + 1:
        tail = lines[end - 1].strip()
        if not tail or tail.startswith("#"):
            end -= 1
            continue
        break
    return start, end


def _array_span(lines: list[str], start: int, end: int, key: str) -> tuple[int, int] | None:
    """``key = [...]`` 在 ``[start, end)`` 里占的行区间（数组可跨多行）。"""
    assign = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for index in range(start, end):
        if not assign.match(lines[index]):
            continue
        depth = 0
        for cursor in range(index, end):
            depth += _bracket_delta(lines[cursor])
            if depth <= 0:
                return index, cursor + 1
        return index, end  # 数组没闭合（文件本来就坏了），到段末为止
    return None


def _bracket_delta(line: str) -> int:
    """这一行的方括号净增量。字符串里的与注释里的括号不算。"""
    depth = 0
    quote = ""
    escaped = False
    for char in line:
        if quote:
            if escaped:
                escaped = False
            elif quote == '"' and char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "#":
            break
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth


def _comment_lines(lines: list[str]) -> list[str]:
    """挑出纯注释行（去掉行尾换行）。数组里注释掉的候选词靠它活下来。"""
    return [line.strip() for line in lines if line.lstrip().startswith("#")]


# ------------------------------------------------------------------ 渲染


def _toml_str(value: str) -> str:
    """渲染 TOML 字符串，**优先单引号字面量**（见模块文档）。"""
    if "'" not in value and not _CONTROL_RE.search(value):
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False)


def _toml_num(value: float) -> str:
    """整数值渲染成整数形（``weight = 10`` 比 ``10.0`` 好读；TOML 整数照样读成 float）。"""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _render_keywords(keywords: Sequence[str], kept_comments: Sequence[str]) -> list[str]:
    out = ["keywords = [\n"]
    out += [f"  {_toml_str(keyword)},\n" for keyword in keywords]
    out += [f"  {comment}\n" for comment in kept_comments]
    out.append("]\n")
    return out


def _render_score(score: ScoreConfig) -> list[str]:
    out = [
        "[score]\n",
        "# 这一段能在 Web 管理台的「配置」页直接改。保存时**整段重写**，\n",
        "# 所以段内注释不会保留（[score] 之上那些说明不在重写范围里，不受影响）。\n",
    ]
    if score.salary_floor_wan is None:
        out.append("# salary_floor_wan 未设 = 不按薪资过滤（万元/年，税前口径）\n")
    else:
        out.append(f"salary_floor_wan = {_toml_num(score.salary_floor_wan)}\n")
    out.append(f"title_multiplier = {_toml_num(score.title_multiplier)}\n")

    out += [
        "\n[score.require]\n",
        "# 职位名与 JD 正文里都找不到 pattern = 连赛道都不对，扣 penalty 压到排序末尾\n",
    ]
    if score.require.pattern is None:
        out.append("# pattern 未设 = 不做这道兜底\n")
    else:
        out.append(f"pattern = {_toml_str(score.require.pattern)}\n")
    out.append(f"penalty = {_toml_num(score.require.penalty)}\n")

    out.append("\n# 信号表：命中就加 weight，负权重即减分项；顺序不影响分数\n")
    for signal in score.signals:
        out += [
            "\n[[score.signals]]\n",
            f"name = {_toml_str(signal.name)}\n",
            f"weight = {_toml_num(signal.weight)}\n",
            f"pattern = {_toml_str(signal.pattern)}\n",
        ]
    return out
