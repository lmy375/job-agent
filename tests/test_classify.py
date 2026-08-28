"""分类规则的回归测试。

这里的每个用例都对应一个真实踩过的坑——正则一放宽就会复发，
所以它们比「覆盖率」重要得多。
"""

from __future__ import annotations

import pytest

from job_agent.core.analysis import classify, signal_count
from job_agent.tracks import AI, BACKEND, OTHER, SEC, WEB3

AI_JD = "大模型 Agent 平台，负责 LLM 应用与智能体研发，熟悉 RAG 与模型训练" * 2
SEC_JD = "安全研究、漏洞挖掘、渗透测试、攻防演练、威胁情报与风控" * 2
WEB3_JD = "区块链底层、智能合约、链上数据、以太坊、DeFi、钱包与交易所" * 2


def test_apt_needs_word_boundary():
    """`APT` 不加 \\b 会命中 Caption——实测把 5 个标注岗算成了攻防岗。"""
    track, _ = classify("视频 Caption 标注工程师", AI_JD, AI)
    assert track != SEC


def test_web3_excludes_web_3d():
    """`Web\\s?3` 不排除 3D 会把渲染岗算成 Web3 岗。"""
    track, _ = classify("Web 3D 渲染工程师", AI_JD, AI)
    assert track != WEB3


def test_web3_with_space_still_matches():
    track, _role = classify("Web 3 后端开发工程师", WEB3_JD, WEB3)
    assert track == WEB3


@pytest.mark.parametrize(
    "job_name",
    [
        "功能安全工程师",
        "ISO 26262 功能安全专家",
        "整车安全性能开发",
        "毒理学总监",
        "药物警戒安全官",
        "食品安全经理",
        "安全生产管理员",
    ],
)
def test_non_infosec_safety_excluded(job_name):
    """「安全」是中文歧义词：车规功能安全 / 医药 / 食品与信息安全零交集。"""
    track, _ = classify(job_name, SEC_JD, SEC)
    assert track == OTHER


@pytest.mark.parametrize(
    "job_name", ["销售总监", "大客户经理", "品牌市场负责人", "HR 招聘经理", "CMO"]
)
def test_non_tech_roles_excluded(job_name):
    track, role = classify(job_name, AI_JD, AI)
    assert (track, role) == (OTHER, "非技术岗")


def test_generic_backend_title_reclassified_by_jd():
    """「后端工程师」这类通用职位名看不出赛道，正文信号密集时按正文归属。"""
    track, _ = classify("资深后端工程师", WEB3_JD, BACKEND)
    assert track == WEB3


def test_generic_backend_title_stays_backend_without_signal():
    track, _ = classify("资深后端工程师", "负责业务系统开发与维护，熟悉 MySQL", BACKEND)
    assert track == BACKEND


def test_keyword_fallback_requires_jd_signal():
    """职位名认不出、正文也没信号 → 归「其他」，不硬塞进关键词所属赛道。

    否则按「区块链」关键词返回的 CMO、银行 BD 会被整片算成 Web3 技术岗。
    """
    track, role = classify("高级专家", "负责团队管理与流程优化", WEB3)
    assert (track, role) == (OTHER, "未分类")

    track, _ = classify("高级专家", WEB3_JD, WEB3)
    assert track == WEB3


def test_no_keyword_track_means_other():
    track, role = classify("高级专家", AI_JD, None)
    assert (track, role) == (OTHER, "未分类")


def test_ai_security_goes_to_security_track():
    track, role = classify("大模型安全算法专家", SEC_JD, SEC)
    assert track == SEC
    assert "AI 安全" in role


def test_signal_count_counts_occurrences():
    assert signal_count("区块链 区块链 智能合约", WEB3) >= 3
    assert signal_count("与业务方对齐预期", AI) == 0


# ---------------------------------------------------------------- 缩写边界回归
#
# 两三个字母的英文缩写在 IGNORECASE 下会命中英文单词的中段。
# 这几条是实测踩到的：都被误判成「非技术岗」，而且都是高价值的 Agent 平台岗。


@pytest.mark.parametrize(
    ("title", "jd"),
    [
        # UI 命中 "B(ui)lder"
        ("点评技术-AI Builder 团队负责人", "Agent 平台建设 大模型 提效 Prompt 工程"),
        # PR 命中 "(Pr)oxy"
        ("LLM Proxy 平台负责人", "大模型网关 推理路由 Agent 编排"),
        # UX 同理，构造一个含 "ux" 的英文产品名
        ("Flux Agent 平台工程师", "智能体 平台 大模型 编排"),
    ],
)
def test_ascii_abbreviations_do_not_match_inside_words(title, jd):
    track, role = classify(title, jd, None)
    assert (track, role) != ("其他", "非技术岗"), f"{title} 被误判成非技术岗"


@pytest.mark.parametrize(
    "title",
    [
        "UI设计师",  # 中文紧跟，不能用 \b
        "UI/UX 设计",
        "高级UX研究员",
        "HRVP/CHO",  # HR 只限前边界，HRVP / HRBP / HRD 要留住
        "HRBP",
        "高级BD经理",
        "PR 传播总监",
    ],
)
def test_genuine_non_technical_roles_still_matched(title):
    track, role = classify(title, "岗位职责", None)
    assert (track, role) == ("其他", "非技术岗"), f"{title} 应当仍被判为非技术岗"
