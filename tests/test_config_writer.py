"""把改动写回 profile.toml：定点替换，别的字节一个都不许动。

Web 管理台能直接改搜索关键词与 ``[score]``，但配置仍然只有文件这一处落盘。
所以这组用例盯的是**写回的破坏性**——profile.toml 里的注释是用户唯一的说明书，
一次保存把它们重排掉，人下次就不知道每个字段是干什么的了。

拿仓库里真实的 ``config/templates/profile.toml`` 当输入（而不是随手拼一份）：
它是新用户的第一份配置，注释最多、结构最全，坏也是先在它身上坏。
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from job_agent.config import (
    ProfileSettings,
    ScoreConfig,
    load_settings,
    write_keywords,
    write_prompt,
    write_score,
)
from job_agent.config.models import RequireRule, Signal

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "config" / "templates" / "profile.toml"


def template_copy(tmp_path: Path) -> Path:
    target = tmp_path / "profile.toml"
    shutil.copyfile(TEMPLATE, target)
    return target


def around_keywords(text: str) -> tuple[str, str]:
    """``keywords = [...]`` 之前与之后的全文。写回只许动数组本身，这两半必须逐字节相同。"""
    head, rest = text.split("keywords = [", 1)
    _array, tail = rest.split("]\n", 1)
    return head, tail


def parse(path: Path) -> ProfileSettings:
    """读回来必须仍然是**合法且等价**的配置——写出去的东西自己得读得回来。"""
    return ProfileSettings(**tomllib.loads(path.read_text(encoding="utf-8")))


def test_write_keywords_only_touches_the_array(tmp_path):
    path = template_copy(tmp_path)
    before = path.read_text(encoding="utf-8")

    write_keywords(path, ["AI Agent", "Claude Code", "AI 工程"])

    parsed = parse(path)
    # 顺序即优先级：给进去什么顺序就写回什么顺序，不排序
    assert parsed.search.keywords == ["AI Agent", "Claude Code", "AI 工程"]
    assert parsed.search.address == "北京"
    assert parsed.storage.database == Path("data/jobs.db")
    assert len(parsed.score.signals) == len(parse(TEMPLATE).score.signals)

    # 数组之外**逐字节**相同：注释、[profile]、[storage]、整个 [score] 全在原位
    assert around_keywords(path.read_text(encoding="utf-8")) == around_keywords(before)


def test_write_keywords_keeps_commented_out_candidates(tmp_path):
    """数组里注释掉的候选词要留着——它们是「库里存量数据是怎么来的」的线索。"""
    path = template_copy(tmp_path)
    write_keywords(path, ["大模型"])
    text = path.read_text(encoding="utf-8")
    assert '# "区块链", "智能合约", "Web3", "Solidity",' in text
    assert '# "后端架构师", "后端技术专家", "技术专家",' in text
    assert parse(path).search.keywords == ["大模型"]


def test_write_score_keeps_the_doc_block_above_it(tmp_path):
    """``[score]`` 整段重写，但段**之上**那一大块说明注释不在替换范围里。"""
    path = template_copy(tmp_path)
    original = parse(path).score

    write_score(
        path,
        ScoreConfig(
            salary_floor_wan=135.0,
            title_multiplier=1.5,
            require=original.require,
            signals=[Signal(name="AI Agent", weight=10, pattern=r"(?a:\bagent\b)|智能体")],
        ),
    )

    text = path.read_text(encoding="utf-8")
    assert "# [score] 是**匹配信号表**：整段都是「你想要什么」，不是通用规则。" in text
    assert "# 不知道该怎么填？在 Claude Code 里跑 `/job-init`" in text
    # 别的段一个字没动
    assert '[profile]\n# 求职者信息' in text
    assert 'database = "data/jobs.db"' in text

    parsed = parse(path)
    assert parsed.score.salary_floor_wan == 135.0
    assert parsed.score.title_multiplier == 1.5
    assert [s.name for s in parsed.score.signals] == ["AI Agent"]
    assert parsed.search.keywords == parse(TEMPLATE).search.keywords


def test_patterns_round_trip_as_literal_strings(tmp_path):
    r"""正则必须写成单引号字面量：双引号里 ``\b`` 是退格符转义。

    写错了不会报错——正则编译得过、一条也匹配不上、排名看着正常但全错，
    所以这条用例盯的是**写出来的形状**，不只是「读回来相等」。
    """
    path = template_copy(tmp_path)
    pattern = r"(?a:\bagent\b)|智能体\s*平台"
    write_score(
        path,
        ScoreConfig(
            require=RequireRule(pattern=pattern, penalty=-20.0),
            signals=[Signal(name="Agent", weight=10, pattern=pattern)],
        ),
    )

    text = path.read_text(encoding="utf-8")
    assert f"pattern = '{pattern}'" in text
    assert "\\\\b" not in text  # 没被当成基本字符串去转义
    parsed = parse(path)
    assert parsed.score.signals[0].pattern == pattern
    assert parsed.score.require.pattern == pattern


def test_values_with_single_quotes_fall_back_to_basic_strings(tmp_path):
    """字面量字符串装不下单引号，这时才退回双引号并转义反斜杠。"""
    path = template_copy(tmp_path)
    write_score(
        path,
        ScoreConfig(signals=[Signal(name="带'引号'的名字", weight=-3, pattern=r"a'b\d")]),
    )
    signal = parse(path).score.signals[0]
    assert signal.name == "带'引号'的名字"
    assert signal.pattern == r"a'b\d"


def test_missing_file_and_sections_are_created(tmp_path):
    """profile.toml 缺失是合法状态（字段全走默认值），保存要能把它建出来。"""
    path = tmp_path / "profile.toml"
    write_keywords(path, ["大模型"])
    write_score(path, ScoreConfig(signals=[Signal(name="Agent", weight=8, pattern="agent")]))

    parsed = parse(path)
    assert parsed.search.keywords == ["大模型"]
    assert [s.name for s in parsed.score.signals] == ["Agent"]
    assert not list(tmp_path.glob("*.tmp"))  # 原子写：临时文件不留在原地


def test_written_profile_still_loads_end_to_end(project_root, profile_dir):
    """写回之后 ``load_settings`` 读到的就是新值——生效的永远是文件里那份。"""
    path = profile_dir / "profile.toml"
    write_keywords(path, ["Claude Code", "AI 工程"])
    write_score(
        path,
        ScoreConfig(
            salary_floor_wan=150.0,
            signals=[Signal(name="MCP", weight=9, pattern=r"(?a:\bmcp\b)")],
        ),
    )

    settings = load_settings("test", project_root / "config" / "config.toml")
    assert settings.search.keywords == ["Claude Code", "AI 工程"]
    assert settings.score.salary_floor_wan == 150.0
    assert [s.name for s in settings.score.signals] == ["MCP"]
    # 指纹跟着信号表变，Web 概览与 job stats 就是靠它提示「分数过期了」
    assert settings.score.fingerprint != parse(TEMPLATE).score.fingerprint


#: ``[score]`` 不在文件末尾的排版。模板里它正好是最后一段，
#: 而「整段重写」最容易坏的地方恰恰是**段尾在哪**——多吃一行就把别人的段吞了
REORDERED = """[profile]
name = "谁"

[score]
title_multiplier = 2.0

[[score.signals]]
name = "旧信号"
weight = 3
pattern = 'old'

# ---------------------------------------------------------------- 存储
# 这段注释是写给 [storage] 的，不许跟着 [score] 一起被替换掉
[storage]
database = "data/jobs.db"

[search]
keywords = ["旧词"]
"""


def test_rewriting_a_middle_section_does_not_eat_the_next_one(tmp_path):
    path = tmp_path / "profile.toml"
    path.write_text(REORDERED, encoding="utf-8")

    write_score(path, ScoreConfig(signals=[Signal(name="新信号", weight=7, pattern="new")]))

    text = path.read_text(encoding="utf-8")
    assert "# 这段注释是写给 [storage] 的" in text
    assert "旧信号" not in text
    parsed = parse(path)
    assert [s.name for s in parsed.score.signals] == ["新信号"]
    assert parsed.storage.database == Path("data/jobs.db")
    assert parsed.profile.name == "谁"
    # 后面那两段还在，而且还能改
    write_keywords(path, ["新词"])
    assert parse(path).search.keywords == ["新词"]
    assert [s.name for s in parse(path).score.signals] == ["新信号"]


# ---------------------------------------------------------------- 提示词 md


def test_write_prompt_creates_and_removes(tmp_path):
    """空内容 = 删文件、回到内置默认，不是「存一份空提示词」。

    存一份空的会让模型收到一段没有方法论的 system——分数直接变成瞎猜，
    比没有覆盖更糟，而且从界面上看不出来。
    """
    path = tmp_path / "nested" / "score_appeal.md"

    assert write_prompt(path, "  只看薪资高不高。\n") == path
    assert path.read_text(encoding="utf-8") == "只看薪资高不高。\n"

    assert write_prompt(path, "   \n\n") is None
    assert not path.exists()
    # 已经不存在了再删一次也不该炸（页面上连点两次保存）
    assert write_prompt(path, "") is None


def test_write_prompt_is_a_full_replace(tmp_path):
    """整份替换，不是追加——提示词没有「段」可言，也不该有历史残留。"""
    path = tmp_path / "score_fit.md"
    write_prompt(path, "第一版")
    write_prompt(path, "第二版")
    assert path.read_text(encoding="utf-8") == "第二版\n"
