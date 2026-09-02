"""匹配信号表的加载与校验。

**这张表是配置，不是代码。** 它编码的是「这个人想要什么」：
对一个做 AI 应用工程的候选人，「预训练 / 强化学习」是负信号；
对一个做算法的候选人，同一个词是最强的正信号。所以它必须住在
profile 目录下的 ``match.toml``，由 ``/job-init`` 访谈后生成，换人就整份重写。

代码这边只负责三件事：读、校验、编译正则。判断权重高低是用户的事。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from job_agent.errors import ConfigError


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

#: 正则里出现这些控制字符，几乎一定是 TOML 转义踩坑的结果（见 _check_pattern）
_CONTROL_CHARS = {
    "\x08": r"\b（单词边界）",
    "\x0c": r"\f",
    "\t": r"\t",
    "\r": r"\r",
}


def _check_pattern(value: str) -> str:
    """校验一条正则：能编译，且没踩 TOML 转义的坑。

    TOML **基本字符串**（双引号）会处理转义，而 ``\b`` 在 TOML 里是合法的
    「退格符」转义。于是 ``pattern = "\bagent\b"`` 会静默变成
    ``<退格>agent<退格>``——正则编译得过、一条也匹配不上、排名看着正常但全错。
    这是最坏的一种 bug：没有任何报错。所以在这里主动拦下来。

    正确写法两种，模板里统一用第二种：
      · 基本字符串里双写反斜杠：``"\\bagent\\b"``
      · **TOML 字面量字符串（单引号）**：``'\bagent\b'`` —— 不处理转义，推荐
    """
    for char, meant in _CONTROL_CHARS.items():
        if char in value:
            raise ValueError(
                f"正则里出现了控制字符 {char!r}，你大概是想写 {meant}。\n"
                "  TOML 的双引号字符串会处理转义（\\b = 退格符），"
                "改用单引号的字面量字符串即可：pattern = '\\bagent\\b'"
            )
    try:
        re.compile(value, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"不是合法正则：{exc}") from exc
    return value


class Signal(BaseModel):
    """一条信号：命中就给 ``weight`` 分。负权重即「减分项 / 排除信号」。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: float
    pattern: str = Field(min_length=1)

    @field_validator("pattern")
    @classmethod
    def _valid(cls, value: str) -> str:
        return _check_pattern(value)

    @property
    def regex(self) -> re.Pattern[str]:
        """编译后的正则。``functools`` 缓存不了实例属性，这里靠调用方复用对象。"""
        return re.compile(self.pattern, re.IGNORECASE)


class RequireRule(_Model):
    """「完全不对口」的兜底判定。

    职位名与 JD 正文里都找不到 ``pattern``，说明这条岗位连赛道都不对
    （例：想投 AI，结果是个纯 CRUD 后端），直接扣到排序末尾。
    没有这道闸，负信号表得穷举所有不想要的方向，永远列不全。
    """

    pattern: str | None = None
    penalty: float = -20.0

    @field_validator("pattern")
    @classmethod
    def _valid(cls, value: str | None) -> str | None:
        return None if value is None else _check_pattern(value)


class Options(_Model):
    """打分参数。"""

    #: 标题命中的权重倍数。职位名比 JD 正文更能代表岗位本质，所以默认加倍
    title_multiplier: float = Field(default=2.0, ge=0)


class MatchRules(_Model):
    """一份完整的信号表。"""

    options: Options = Field(default_factory=Options)
    require: RequireRule = Field(default_factory=RequireRule)
    signals: list[Signal] = Field(default_factory=list)

    @property
    def require_regex(self) -> re.Pattern[str] | None:
        if self.require.pattern is None:
            return None
        return re.compile(self.require.pattern, re.IGNORECASE)


def load_rules(path: Path) -> MatchRules:
    """读信号表（``settings.match.rules``，即 profile 目录下的 ``match.toml``）。

    缺文件、TOML 语法错、正则写错都抛 :class:`ConfigError`。

    刻意不做「文件不存在就用空表兜底」——空表会让 ``job score`` 输出一份
    全是 0 分的排名，看起来像跑成功了，实际毫无意义。宁可直接报错。
    """
    if not path.is_file():
        raise ConfigError(
            f"匹配信号表不存在：{path}\n"
            "  跑 `job config init` 从模板生成，或让 Claude 跑 `/job-init` 按访谈生成。"
        )
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"匹配信号表不是合法 TOML（{path}）：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"匹配信号表读取失败（{path}）：{exc}") from exc

    try:
        rules = MatchRules.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError 的信息已经足够具体
        raise ConfigError(f"匹配信号表校验失败（{path}）：{exc}") from exc

    if not rules.signals:
        raise ConfigError(
            f"匹配信号表里没有任何 [[signals]]：{path}\n"
            "  至少写几条正信号，否则所有岗位都是 0 分，排序没有意义。"
        )
    return rules
