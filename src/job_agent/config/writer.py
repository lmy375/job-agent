"""把改动写回配置文件（两个 ``*.toml`` + profile 目录下的几份 md）。

Web 管理台能改**所有**配置项，但**配置仍然只有文件这一处落盘**：
页面上按保存就是改这个文件，改完重新 ``load_settings()`` 一遍。
所以不存在「网页上改了但下次 CLI 跑的是另一套」——CLI、Web、agent 三条路
读的永远是同一份 TOML。

两种写法，覆盖面不同：

- :func:`write_section` 按段整段重写，段名与模型的对应关系靠
  :func:`config_sections` **遍历模型得出**，不手工维护——往 ``GlobalSettings`` /
  ``ProfileSettings`` 上加一个段，页面立刻能改它，不必在三个地方各补一遍；
- :func:`write_raw` 收整份文件原文（「高级」页的文本编辑器），
  落盘前先 parse + 按模型校验，坏的内容进不了文件。

``[search]`` 与 ``[score]`` 另有手写的渲染（``write_search`` / ``write_score``），
因为它们要保住通用渲染保不住的东西：注释掉的候选关键词、信号表的说明。

刻意不引 TOML 写库（tomlkit 之类）：写回会把整个文件的注释与排版重排一遍，
而 profile.toml 里那些注释是用户唯一的说明书。这里只做**定点替换**：

- :func:`write_keywords` 只动 ``[search]`` 里 ``keywords = [...]`` 那几行
  （数组里注释掉的候选词原样留着——那是「库里存量数据是怎么来的」的线索）；
- :func:`write_score` 整段重写 ``[score]``（含 ``[score.require]`` 与全部
  ``[[score.signals]]``）：段内注释保不住，但 ``[score]`` **之上**那一大块
  说明注释不在替换范围里，不受影响；
- :func:`write_section` 对任意一段做同样的事（整段重写、段外不动）。

其余每一个字节原样保留。同一个思路见 ``cli/commands/profile_cmd.py``
的 ``_write_default``。

**改结构化的段要拿文件里那份原始值，不要拿 ``Settings``**：后者的路径字段
在 loader 里已经解析成绝对路径了，照它写回去会把 ``data/jobs.db`` 这种
相对路径换成某台机器上的绝对路径。:func:`read_section` 就是干这个的。

:func:`write_prompt` 写的是另一类文件：profile 目录下的几份 md
（简历、求职偏好、LLM 打分两个维度的提示词覆盖）。它们没有「段」可言，
整份替换即可；提示词**内容为空就删文件**，回到 ``src`` 里的内置默认——
存一份空提示词会让模型收到一段没有方法论的 system，比没有覆盖更糟。

正则一律渲染成 **TOML 字面量字符串（单引号）**：双引号里 ``\\b`` 是「退格符」
转义，会静默变成匹配不上任何东西的正则（见 ``config/models.py`` 的
``_check_pattern``）。值里本身带单引号时才退回双引号，并转义反斜杠。
"""

from __future__ import annotations

import functools
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from job_agent.config.models import (
    GlobalSettings,
    ProfileSettings,
    ScoreConfig,
    SearchConfig,
    Signal,
)
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
    body = lines[first + 1 : last - 1]
    patched = _patch_keywords(body, keywords) if _is_block_array(lines, first, last) else None
    if patched is not None:
        block = [lines[first], *patched, lines[last - 1]]
    else:
        # 顺序真的变了（或者数组写法认不出来）：只能整份重排。
        # 注释掉的候选词留着，但会被归到数组末尾
        block = _render_keywords(keywords, _comment_lines(body))
    return _write_lines(profile_file, [*lines[:first], *block, *lines[last:]])


def _is_block_array(lines: list[str], first: int, last: int) -> bool:
    """数组是不是「一行一个词」的块写法：首行到 ``[`` 为止，末行只有 ``]``。

    ``keywords = ["a", "b"]`` 这种一行写完的不算——按行定点替换对不上，
    而且它本来也没有分组注释可保。
    """
    if last - first < 2:
        return False
    head, _ = _split_comment(lines[first])
    tail, _ = _split_comment(lines[last - 1])
    return head.rstrip().endswith("[") and tail.strip() == "]"


def _patch_keywords(body: list[str], keywords: Sequence[str]) -> list[str] | None:
    """按词定点改数组：留下的词原样不动，删掉的删行，新词接在最后一个词后面。

    返回 ``None`` 表示做不到，调用方退回整份重排。两种情况：一行写了多个词
    （认不出哪个是哪个），或者留下来的词**顺序变了**——顺序就是优先级，
    那种时候只能重排，代价是数组里的分组注释会被归到末尾。

    在意这件事是因为那些注释是**分组说明**（「优先方向」「宽词兜底」），
    一旦被冲到数组底部，它说的是哪几个词就再也看不出来了。而加词删词是
    这个页面上最高频的动作，每次都重排一遍等于很快就把说明全洗掉。
    """
    entries: list[tuple[int, str]] = []
    for index, line in enumerate(body):
        code, _ = _split_comment(line)
        if not code.strip():
            continue
        try:
            parsed = tomllib.loads(f"x = [{code}]")["x"]
        except tomllib.TOMLDecodeError:
            return None
        if len(parsed) != 1 or not isinstance(parsed[0], str):
            return None
        entries.append((index, parsed[0]))

    wanted = list(keywords)
    survivors = [word for _, word in entries if word in set(wanted)]
    existing = {word for _, word in entries}
    if survivors != [word for word in wanted if word in existing]:
        return None

    keep_at = {index for index, word in entries if word in set(wanted)}
    value_lines = {index for index, _ in entries}
    last_kept = max(keep_at, default=-1)
    out: list[str] = []
    for index, line in enumerate(body):
        if index in value_lines and index not in keep_at:
            continue  # 这个词被删了
        out.append(line)
        if index == last_kept:
            out += [f"  {_toml_str(word)},\n" for word in wanted if word not in existing]
    if last_kept < 0:
        # 一个旧词都没留下：新词接在所有注释之后
        out += [f"  {_toml_str(word)},\n" for word in wanted]
    return out


def write_score(profile_file: Path, score: ScoreConfig) -> Path:
    """改写 ``[score]``（含 ``[score.require]`` 与全部 ``[[score.signals]]``）。

    **按条定点替换，不整段重写。** 信号表是这个仓库里注释最密的一段——
    「这个词为什么是负的」「这条为什么砍到 -14」全写在每条信号旁边，
    而配置页上最常按的就是这里的保存。整段重写一次就把那些理由全抹了，
    下次再调权重的人只能看见一堆没有出处的数字。

    信号按 ``name`` 对齐：名字还在就只改变了的那几行（它上面那段说明原样留着），
    名字没了就删掉整块，新名字追加到最后一块之后。改名等于删一条加一条，
    那条的注释跟着没——这是按名字对齐必然的代价，比整段全丢小得多。
    """
    lines = _read_lines(profile_file)
    if not _section_spans(lines, "score"):
        return _write_lines(profile_file, [*lines, *_separator(lines), *_render_score(score)])

    payload = score.model_dump()
    payload.pop("signals", None)
    desired = _flatten_tables("score", payload)
    current = _flatten_tables("score", _section_payload(profile_file, "score", drop="signals"))
    # drop_missing=False：``[[score.signals]]`` 不在 desired 里，但它不是「被删了」，
    # 而是由下面那步自己管
    lines = _patch_section(lines, "score", desired, current, drop_missing=False)
    return _write_lines(profile_file, _patch_signals(lines, score.signals))


def _section_payload(config_file: Path, section: str, drop: str) -> dict[str, Any]:
    """文件里这一段现在解析出来的值，去掉 ``drop`` 那个键。"""
    payload = read_section(config_file, section).model_dump()
    payload.pop(drop, None)
    return payload


def _patch_signals(lines: list[str], signals: Sequence[Signal]) -> list[str]:
    """按 ``name`` 对齐地改写 ``[[score.signals]]`` 各块。"""
    blocks = _signal_blocks(lines)
    wanted = {signal.name: signal for signal in signals}
    seen: set[str] = set()
    out: list[str] = []
    cursor = 0
    tail = 0

    for start, end, parsed in blocks:
        out += lines[cursor:start]
        cursor = end
        name = str(parsed.get("name", ""))
        signal = wanted.get(name)
        if signal is None:
            # 这条被删了，整块不要（块**上面**那段说明是写给它的，跟着走）。
            # 但块末尾那些紧贴下一个表头的注释是写给下一段的，得留下
            out += lines[_trim_tail(lines, start, end) : end]
            tail = len(out)
            continue
        seen.add(name)
        body_end = _trim_tail(lines, start, end)
        values = {"weight": _toml_num(signal.weight), "pattern": _toml_str(signal.pattern)}
        kept = [lines[start]]
        written: set[str] = set()
        index = start + 1
        while index < body_end:
            span = _assignment_span(lines, index, body_end)
            if span is None:
                kept.append(lines[index])
                index += 1
                continue
            key, stop = span
            if key in values and _toml_scalar(parsed.get(key)) != values[key]:
                kept.append(_replace_value(lines[index], values[key]))
                kept += lines[index + 1 : stop]
            else:
                kept += lines[index:stop]
            written.add(key)
            index = stop
        kept += [f"{key} = {value}\n" for key, value in values.items() if key not in written]
        out += kept
        out += lines[body_end:end]
        tail = len(out)

    out += lines[cursor:]
    added = [signal for signal in signals if signal.name not in seen]
    if added:
        block: list[str] = []
        for signal in added:
            block += [
                "\n[[score.signals]]\n",
                f"name = {_toml_str(signal.name)}\n",
                f"weight = {_toml_num(signal.weight)}\n",
                f"pattern = {_toml_str(signal.pattern)}\n",
            ]
        at = tail
        if not at:
            # 一条都没留下：放在 [score] 名下最后一张表之后，
            # 而不是文件末尾——追到 [search] 后面虽然也能解析，但没人看得懂
            spans = _section_spans(out, "score")
            at = spans[-1][1] if spans else len(out)
        out = [*out[:at], *block, *out[at:]]
    return out


def _signal_blocks(lines: list[str]) -> list[tuple[int, int, dict[str, Any]]]:
    """每个 ``[[score.signals]]`` 块的行区间与解析出来的值，按文件顺序。

    块体本身就是合法 TOML，交给 ``tomllib`` 解析——自己认 ``name = '...'``
    那一行等于再写一遍 TOML 的字符串规则，引号、转义、多行迟早对不上。
    """
    blocks: list[tuple[int, int, dict[str, Any]]] = []
    start: int | None = None
    for index, line in enumerate([*lines, "[\x00]\n"]):
        name = _header_name(line)
        if name is None:
            continue
        if start is not None:
            body = "".join(lines[start + 1 : _trim_tail(lines, start, index)])
            try:
                blocks.append((start, index, tomllib.loads(body)))
            except tomllib.TOMLDecodeError:
                blocks.append((start, index, {}))
            start = None
        if line.strip().startswith("[[") and name == "score.signals":
            start = index
    return blocks


def _toml_scalar(value: Any) -> str | None:
    """文件里现在那个值渲染成 TOML 的样子，用来和新值比「变没变」。"""
    return None if value is None else _toml_value(value)


def write_prompt(path: Path, content: str) -> Path | None:
    """写一份 LLM 打分提示词的覆盖文件；``content`` 去空白后为空就**删掉它**。

    返回写入的路径，删除时返回 ``None``——调用方据此就能说清「现在用的是
    自定义还是内置默认」，不必再 stat 一次。
    """
    text = content.strip()
    if not text:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise ConfigError(f"删除提示词文件失败（{path}）：{exc}") from exc
        return None
    return _atomic_write(path, text + "\n")


# ------------------------------------------------------------------ 段与文件


class ConfigScope(StrEnum):
    """一个段住哪个文件。两个文件的段名完全不重叠，所以段名能唯一定位到文件。"""

    GLOBAL = "global"
    PROFILE = "profile"


class SectionTarget(BaseModel):
    """一个可写的配置段：叫什么、住哪个文件、按哪个模型校验。"""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    scope: ConfigScope
    model: type[BaseModel]


@functools.cache
def config_sections() -> dict[str, SectionTarget]:
    """所有可写的段：段名 → 住哪个文件、按哪个模型校验。

    **遍历模型得出，不手工维护一张表**：往 :class:`GlobalSettings` 或
    :class:`ProfileSettings` 上加一个段，Web 的「高级」页立刻能改它，
    不需要在这里、在路由里、在前端各补一遍——手工表一定会有人漏。

    非段的字段（``root`` / ``config_file``，由 loader 注入）不在里面：
    判据是「这个字段的类型是不是一个配置模型」。
    """
    out: dict[str, SectionTarget] = {}
    for scope, settings_model in (
        (ConfigScope.GLOBAL, GlobalSettings),
        (ConfigScope.PROFILE, ProfileSettings),
    ):
        for name, field in settings_model.model_fields.items():
            annotation = field.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                out[name] = SectionTarget(name=name, scope=scope, model=annotation)
    return out


def section_target(section: str) -> SectionTarget:
    """按段名查它住哪儿，查不到就报错并列出所有段名。"""
    sections = config_sections()
    target = sections.get(section)
    if target is None:
        known = "、".join(sorted(sections))
        raise ConfigError(f"没有这个配置段：{section}\n  可写的段：{known}")
    return target


def read_section(config_file: Path, section: str) -> BaseModel:
    """从**文件**里读一段，按它的模型校验（缺的字段走默认值）。

    刻意读文件而不是读 :class:`~job_agent.config.Settings`：后者的路径字段
    已经被 loader 解析成绝对路径，拿它写回去会把 ``data/jobs.db``
    换成某台机器上的绝对路径，profile 目录就不能整份拷给别人了。
    """
    target = section_target(section)
    raw = read_toml(config_file)
    payload = raw.get(section, {})
    if not isinstance(payload, Mapping):
        raise ConfigError(f"[{section}] 不是一个表（{config_file}）")
    try:
        return target.model.model_validate(dict(payload))
    except ValidationError as exc:
        raise ConfigError(f"[{section}] 校验不过（{config_file}）：{exc}") from exc


def write_section(config_file: Path, section: str, data: BaseModel | Mapping[str, Any]) -> Path:
    """整段重写 ``[section]``（连同它的子表），段外一个字节不动。

    **按键定点替换**（见 :func:`_patch_section`）：只动值，段内注释、空行、
    字段顺序一个字节不动。段还不存在时才整段渲染一份追加进去。

    ``[search]`` 与 ``[score]`` 有各自的写法：前者要保住数组里注释掉的候选词，
    后者是数组表（``[[score.signals]]``），按键对不齐，只能整段重写。
    """
    lines = _read_lines(config_file)
    payload = data.model_dump() if isinstance(data, BaseModel) else dict(data)
    try:
        desired = _flatten_tables(section, payload)
        # 这个文件现在解析出来的那份，用来判断每个键到底变没变
        current = _flatten_tables(section, read_section(config_file, section).model_dump())
    except _ArrayTableError:
        desired = {}
        current = {}
    if desired and _section_spans(lines, section):
        return _write_lines(config_file, _patch_section(lines, section, desired, current))
    # 段还不存在（或含数组表）：整段渲染一份放进去
    block = render_section(section, data)
    return _write_lines(config_file, _replace_section(lines, section, block))


def write_search(profile_file: Path, search: SearchConfig) -> Path:
    """改写 ``[search]``：标量按键定点替换，``keywords`` 数组单独写。

    两件事分开做，是因为它们要保住的东西不一样：段内每个字段旁边那句说明
    靠按键替换保住，数组里**注释掉的候选词**靠 :func:`write_keywords` 保住
    （那些是「库里存量数据是怎么来的」的唯一线索）。
    """
    payload = search.model_dump()
    keywords = payload.pop("keywords", [])
    lines = _read_lines(profile_file)
    if not _section_spans(lines, "search"):
        block = [*_render_table("search", payload), *_render_keywords(keywords, [])]
        _write_lines(profile_file, [*lines, *_separator(lines), *block])
        return profile_file

    desired = _flatten_tables("search", payload)
    current = _flatten_tables("search", _section_payload(profile_file, "search", drop="keywords"))
    _write_lines(profile_file, _patch_section(lines, "search", desired, current))
    return write_keywords(profile_file, keywords)


def write_raw(config_file: Path, scope: ConfigScope, text: str, root: Path | None = None) -> Path:
    """整份替换一个配置文件（「高级」页的文本编辑器）。

    **先校验再落盘**：parse 不过或字段不合法就直接抛，文件一个字节不动。
    否则一次手滑就能把配置写成读不出来的样子，而下一次读它的可能是
    明天无人值守跑的 ``job agent``。

    校验走的就是平时加载配置的那两个模型，所以「页面上保存成功」
    等价于「下次 CLI 起得来」。
    """
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"不是合法 TOML：{exc}") from exc

    try:
        if scope is ConfigScope.GLOBAL:
            GlobalSettings(root=root or config_file.parent.parent, **payload)
        else:
            ProfileSettings(**payload)
    except ValidationError as exc:
        raise ConfigError(f"配置校验不过：{exc}") from exc

    return _atomic_write(config_file, text if text.endswith("\n") else text + "\n")


def read_toml(path: Path) -> dict[str, Any]:
    """读一份 TOML；文件不存在当空表（profile.toml 缺失是合法状态）。"""
    if not path.is_file():
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 TOML（{path}）：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"配置文件读取失败（{path}）：{exc}") from exc


def read_text(path: Path) -> str:
    """读一份文本文件；不存在返回空串。"""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"文件读取失败（{path}）：{exc}") from exc

# ------------------------------------------------------------------ 文件读写


def _read_lines(profile_file: Path) -> list[str]:
    if not profile_file.is_file():
        return []
    try:
        return profile_file.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        raise ConfigError(f"配置文件读取失败（{profile_file}）：{exc}") from exc


def _write_lines(profile_file: Path, lines: list[str]) -> Path:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return _atomic_write(profile_file, "".join(lines))


def _atomic_write(path: Path, text: str) -> Path:
    """整份原子替换：同目录临时文件 + rename。

    直接覆盖的话，写到一半出错（磁盘满、进程被杀）会留下一个残缺的
    profile.toml——那意味着简历还在、信号表没了，而且看不出来。
    """
    temp = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise ConfigError(f"配置文件写入失败（{path}）：{exc}") from exc
    return path


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
    """``[section]`` 的**第一段**占的行区间；没有就 None。

    段可能不连续（见 :func:`_section_spans`），要整段重写请用
    :func:`_replace_section`，不要拿这个区间直接切。
    """
    spans = _section_spans(lines, section)
    return spans[0] if spans else None


def _section_spans(lines: list[str], section: str) -> list[tuple[int, int]]:
    """``[section]`` 连同它的子表占的所有行区间 ``[start, end)``，按出现顺序。

    **刻意返回一个列表**：子表不保证跟父表挨着。仓库自带的
    ``config.example.toml`` 里 ``[agent.langsmith]`` 就排在 ``[llm_score]``
    后面，只认第一段会把它漏在原地，整段重写之后同一个表声明两次，
    文件直接变成读不出来的 TOML。

    每段末尾**不吃掉**紧贴下一个表头的注释与空行——那些注释是写给下一段的，
    连着替换掉等于顺手删了别人的说明。
    """
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate([*lines, "[\x00]\n"]):
        name = _header_name(line)
        if name is None:
            continue
        belongs = name == section or name.startswith(f"{section}.")
        if belongs:
            if start is None:
                start = index
            continue
        if start is not None:
            spans.append((start, _trim_tail(lines, start, index)))
            start = None
    return spans


def _trim_tail(lines: list[str], start: int, end: int) -> int:
    """把区间末尾的空行与注释行让给下一段。"""
    while end > start + 1:
        tail = lines[end - 1].strip()
        if not tail or tail.startswith("#"):
            end -= 1
            continue
        break
    return end


def _replace_section(lines: list[str], section: str, block: list[str]) -> list[str]:
    """删掉 ``[section]`` 的每一段，把 ``block`` 放回**第一段**原来的位置。

    一段都没有就追加到文件末尾。
    """
    spans = _section_spans(lines, section)
    if not spans:
        return [*lines, *_separator(lines), *block]
    out: list[str] = []
    cursor = 0
    for index, (start, end) in enumerate(spans):
        out += lines[cursor:start]
        if index == 0:
            out += block
        cursor = end
    out += lines[cursor:]
    return out


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


class _ArrayTableError(Exception):
    """段里有数组表（``[[x]]``），按键改不动它，退回整段重写。"""


def _flatten_tables(path: str, payload: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """把一段摊平成 ``表名 → {键: 渲染好的值}``，``None`` 一律丢掉（= 这项没配）。

    数组表抛 :class:`_ArrayTableError`：它的「第几项」没有稳定身份，
    按键定点替换无从对齐，只有 ``[score]`` 有这种结构，它自己有写法。
    """
    out: dict[str, dict[str, str]] = {}
    scalars: dict[str, str] = {}
    subs: list[tuple[str, Mapping[str, Any]]] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            subs.append((f"{path}.{key}", value))
            continue
        if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
            raise _ArrayTableError(path)
        scalars[key] = _toml_value(value)
    out[path] = scalars
    for sub_path, sub in subs:
        out.update(_flatten_tables(sub_path, sub))
    return out


def _patch_section(
    lines: list[str],
    section: str,
    desired: dict[str, dict[str, str]],
    current: dict[str, dict[str, str]],
    drop_missing: bool = True,
) -> list[str]:
    """按键就地改 ``[section]``：**只动真正变了的那几行**，别的一个字节不碰。

    整段重写（:func:`_replace_section`）会把段内注释一并抹掉，而
    ``config.example.toml`` 里每个字段旁边那句说明是用户唯一的手册——
    在页面上点一次保存就掉三分之一，是典型的「改了但看不出来」。

    比的是**模型层的值**（``current`` 是这个文件现在解析出来的那份），
    不是文本。所以 ``timeout = 30.0`` 不会因为渲染成 ``30`` 就被改写，
    ``"profiles"`` 不会因为渲染偏好单引号就被换掉，字段旁边手工对齐的空格也留着。

    值变了就替换（行尾注释留着），变成 ``None`` 就删掉那一行，
    文件里还没有的键补在表末尾，整张表没了就删整张表。

    ``drop_missing=False`` 时不认识的表原样留着——``[[score.signals]]``
    由 :func:`_patch_signals` 自己管，不该被当成「被删了」。
    """
    regions = _table_regions(lines, section)
    out: list[str] = []
    cursor = 0
    insert_at: int | None = None

    for table, (start, end) in regions.items():
        out += lines[cursor:start]
        cursor = end
        if table not in desired:
            if drop_missing:
                insert_at = len(out)  # 整张表被删了（比如删掉一个猎聘账号）
            else:
                # 调用方自己管这张表（``[[score.signals]]``），原样留着
                out += lines[start:end]
                insert_at = len(out)
            continue
        want = desired[table]
        have = current.get(table, {})
        body_end = _trim_tail(lines, start, end)
        kept: list[str] = [lines[start]]
        written: set[str] = set()
        index = start + 1
        while index < body_end:
            span = _assignment_span(lines, index, body_end)
            if span is None:
                kept.append(lines[index])
                index += 1
                continue
            key, stop = span
            if key in want:
                written.add(key)
                if want[key] == have.get(key):
                    kept += lines[index:stop]  # 值没变，连引号与对齐都不动
                else:
                    kept.append(_replace_value(lines[index], want[key]))
                    kept += lines[index + 1 : stop]
            elif key not in have:
                kept += lines[index:stop]  # 模型不认识的键：留着，不替人删配置
            index = stop
        # 文件里还没写、而且值确实和现在解析出来的不一样的键，补在表末尾。
        # 「和现在一样」的不补——那是默认值，写进去只会让文件长出一堆噪音
        kept += [
            f"{key} = {value}\n"
            for key, value in want.items()
            if key not in written and value != have.get(key)
        ]
        out += kept
        out += lines[body_end:end]
        insert_at = len(out) - (end - body_end)

    out += lines[cursor:]
    # 文件里还没有的表（比如新加一个模型接入点），补在这一段最后一张表之后。
    # 空壳父表（``[liepin.accounts]``）不补：子表头已经隐含了它
    missing = [table for table in desired if table not in regions and desired[table]]
    if missing:
        block: list[str] = []
        for table in missing:
            block += ["\n", f"[{table}]\n"]
            block += [f"{key} = {value}\n" for key, value in desired[table].items()]
        at = len(out) if insert_at is None else insert_at
        out = [*out[:at], *block, *out[at:]]
    return out


def _table_regions(lines: list[str], section: str) -> dict[str, tuple[int, int]]:
    """``[section]`` 名下每张表占的行区间，按文件里的出现顺序。

    表可能不连续（``[agent.langsmith]`` 排在 ``[llm_score]`` 之后），
    所以这里按表逐张记，不假设它们挨着。
    """
    regions: dict[str, tuple[int, int]] = {}
    current: str | None = None
    start = 0
    for index, line in enumerate([*lines, "[\x00]\n"]):
        name = _header_name(line)
        if name is None:
            continue
        if current is not None:
            regions[current] = (start, index)
        current = name if name == section or name.startswith(f"{section}.") else None
        start = index
    return regions


def _assignment_span(lines: list[str], index: int, end: int) -> tuple[str, int] | None:
    """这一行是不是个赋值；是就返回 ``(键, 结束行)``（数组可跨多行）。"""
    code, _ = _split_comment(lines[index])
    match = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*=", code)
    if match is None:
        return None
    key = match.group(1)
    depth = _bracket_delta(lines[index])
    stop = index + 1
    while depth > 0 and stop < end:
        depth += _bracket_delta(lines[stop])
        stop += 1
    return key, stop


def _replace_value(line: str, value: str) -> str:
    """把一行赋值的值换掉；缩进、键名、行尾注释与它所在的列都原样留着。

    对齐也要保：这些文件是手写手维护的，几十行注释在同一列上排成一竖排，
    改一个值就让其中一行错开，下次有人会顺手把整段重排一遍。
    """
    code, comment = _split_comment(line)
    key, _, _ = code.partition("=")
    head = f"{key.rstrip()} = {value}"
    if not comment:
        return f"{head}\n"
    # 注释原来在第几列就还放第几列；新值太长挤不下就退回两个空格
    padding = max(len(code) - len(head), 2)
    return f"{head}{' ' * padding}{comment}\n"


def _split_comment(line: str) -> tuple[str, str]:
    """把一行拆成「代码」与「行尾注释」。字符串里的 ``#`` 不算注释。"""
    quote = ""
    escaped = False
    for index, char in enumerate(line):
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
            return line[:index], line[index:].rstrip("\n")
    return line.rstrip("\n"), ""

# ------------------------------------------------------------------ 渲染


def _toml_str(value: str) -> str:
    """渲染 TOML 字符串，**优先单引号字面量**（见模块文档）。"""
    if "'" not in value and not _CONTROL_RE.search(value):
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False)


def _toml_num(value: float) -> str:
    """整数值渲染成整数形（``weight = 10`` 比 ``10.0`` 好读；TOML 整数照样读成 float）。"""
    return str(int(value)) if float(value).is_integer() else repr(float(value))

def render_section(section: str, data: BaseModel | Mapping[str, Any]) -> list[str]:
    """把一段渲染成 TOML 行（含它的子表）。

    ``None`` 一律**不写**：TOML 没有 null，「文件里没这一行」就是它表达
    「这项没配」的唯一方式。所以可空字段的默认值必须也是 ``None``——
    默认值一旦非空，页面上清空它、保存、重新加载，会被默认值悄悄顶回来。
    """
    payload = data.model_dump() if isinstance(data, BaseModel) else dict(data)
    return _render_table(section, payload)


def _render_table(path: str, payload: Mapping[str, Any]) -> list[str]:
    """``[path]`` 一段：标量在前、子表在后（TOML 要求子表之后不能再出现父表的键）。"""
    scalars: list[str] = []
    tables: list[list[str]] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            tables.append(_render_table(f"{path}.{key}", value))
            continue
        if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
            tables += [
                [f"[[{path}.{key}]]\n", *_render_table_body(item)]
                for item in value
            ]
            continue
        scalars.append(f"{key} = {_toml_value(value)}\n")
    # 只有子表、自己一个键都没有时不写表头：``[liepin.accounts]`` 这种空壳
    # 是纯噪音（子表头 ``[liepin.accounts.default]`` 已经隐含了它）。
    # 但「一个子表都没有」时要写——那是一个货真价实的空表。
    out = [] if tables and not scalars else [f"[{path}]\n", *scalars]
    for index, table in enumerate(tables):
        out += ["\n", *table] if out or index else [*table]
    return out


def _render_table_body(payload: Mapping[str, Any]) -> list[str]:
    """数组表的一项：只渲染标量（信号表那种结构里不会有更深的嵌套）。"""
    return [
        f"{key} = {_toml_value(value)}\n" for key, value in payload.items() if value is not None
    ]


def _toml_value(value: Any) -> str:
    """一个标量（或标量数组）渲染成 TOML 字面量。

    ``SecretStr`` 在这里取明文：写的是配置文件本身，打码写进去等于把 token 弄丢。
    """
    if isinstance(value, SecretStr):
        return _toml_str(value.get_secret_value())
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _toml_num(value)
    if isinstance(value, Path):
        return _toml_str(str(value))
    if isinstance(value, str):
        return _toml_str(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ConfigError(f"不知道怎么把这个值写进 TOML：{value!r}")


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
