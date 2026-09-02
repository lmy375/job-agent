"""测试夹具。

原则：**测试不碰真实的 jobs.db，也不发任何网络请求**。
每个测试都在临时目录里搭一套完整的 config/ + profiles/test/，
这样也顺便验证了「换一个项目根目录也能跑」这件事。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from job_agent.config import Settings, load_settings
from job_agent.context import AppContext
from job_agent.core.liepin.models import Job
from job_agent.core.storage import JobDetailRow

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 全局配置（config/config.toml）：跟人无关的那一半
CONFIG_TOML = """
[profiles]
dir = "profiles"
default = "test"

[liepin]
rate_limit_per_min = 60

[liepin.accounts.default]
user_token = "test-token"

[detail]
sleep_min = 0
sleep_max = 0
block_backoff = 0
max_retries = 2

[agent]
provider = "anthropic"
checkpoint = "data/agent-checkpoint.db"
plan_output = "data/agent-plan.md"

[agent.providers.anthropic]
api = "anthropic"
model = "claude-opus-5"

[logging]
level = "WARNING"
"""

#: profile 配置（profiles/test/profile.toml）：随人而变的那一半
PROFILE_TOML = """
[profile]
name = "测试用户"
account = "default"
resume = "resume.md"
preferences = "preferences.md"

[search]
address = "北京"
salary_kind = "年薪"
salary_floor = 1000000
max_pages = 2

[[search.groups]]
track = "AI"
keywords = ["AI Agent", "大模型"]

[[search.groups]]
track = "安全"
keywords = ["安全专家"]

[[search.groups]]
track = "Web3"
enabled = false
keywords = ["区块链"]

[storage]
database = "data/test.db"

[match]
rules = "match.toml"
shortlist_output = "data/shortlist.md"
"""

#: 测试用的 profile 名。夹具都用它，不用 "default"——
#: 免得哪个用例不小心读到仓库里真实的 profiles/default
PROFILE = "test"


#: 一份最小可用的信号表。刻意小：测试要能一眼看出「这条分数为什么是这个数」。
#: 正则用 TOML 字面量字符串（单引号）——双引号里的 \\b 会被当成退格符转义。
MATCH_TOML = """
[options]
title_multiplier = 2.0

[require]
pattern = '\\bagent\\b|智能体|大模型|\\bllm\\b|\\bai\\b'
penalty = -20.0

[[signals]]
name = "Agent"
weight = 10
pattern = '\\bagent\\b|智能体'

[[signals]]
name = "Python"
weight = 5
pattern = '\\bpython\\b'

[[signals]]
name = "算法训练岗"
weight = -12
pattern = '预训练|强化学习|模型训练'
"""


def make_profile(root: Path, name: str = PROFILE, profile_toml: str = PROFILE_TOML) -> Path:
    """在 ``root`` 下建一个 profile 目录。多 profile 的隔离用例靠它建第二个。"""
    directory = root / "profiles" / name
    (directory / "data").mkdir(parents=True)
    (directory / "profile.toml").write_text(profile_toml, encoding="utf-8")
    (directory / "resume.md").write_text("# 测试简历\n", encoding="utf-8")
    (directory / "preferences.md").write_text("# 求职偏好\n", encoding="utf-8")
    (directory / "match.toml").write_text(MATCH_TOML, encoding="utf-8")
    return directory


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """一个可用的项目根目录（全局 config/ + 一个名为 test 的 profile）。"""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text(CONFIG_TOML, encoding="utf-8")
    make_profile(tmp_path)
    return tmp_path


@pytest.fixture
def profile_dir(project_root: Path) -> Path:
    """当前测试 profile 的目录。简历、信号表、库都在里面。"""
    return project_root / "profiles" / PROFILE


@pytest.fixture
def settings(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    # 真实环境里的覆盖不能泄进测试，否则「缺 token」的用例会假通过
    monkeypatch.delenv("JOB_AGENT_LIEPIN__ACCOUNTS__DEFAULT__USER_TOKEN", raising=False)
    monkeypatch.delenv("JOB_AGENT_PROFILE_NAME", raising=False)
    return load_settings(PROFILE, project_root / "config" / "config.toml")


@pytest.fixture
def context(settings: Settings) -> Iterator[AppContext]:
    ctx = AppContext.from_settings(settings)
    yield ctx
    ctx.close()


def make_job(job_id: int = 1, **overrides: object) -> Job:
    """构造一条职位，字段与 search-job 响应一致。"""
    data = {
        "jobId": job_id,
        "jobType": "2",
        "jobName": "AI Agent 工程师",
        "company": "某公司",
        "location": "北京-海淀区",
        "salary": "60-80k·15薪",
        "education": "本科",
        "workYears": "5-10年",
        "industry": "计算机软件",
        "companyTags": ["大平台"],
        "financingStage": "已上市",
        "companySize": "10000人以上",
        "companyLogo": "",
        "jobDetailUrl": f"https://www.liepin.com/job/{job_id}.shtml",
    }
    data.update(overrides)
    return Job.model_validate(data)


def make_detail(job_id: int = 1, status: str = "ok", **overrides: object) -> JobDetailRow:
    """构造一条 JD 详情行，字段与 job_details 表一致。"""
    return JobDetailRow(jobId=job_id, status=status, **overrides)


def ld_json_page(
    title: str = "AI Agent 工程师",
    description: str = "岗位职责：\n负责 Agent 平台建设\n任职要求：\n熟悉 Python 与 LLM",
    industry: str = "计算机软件",
) -> str:
    """构造一个带 JobPosting 结构化数据的详情页 HTML。"""
    return (
        '<html><head><script type="application/ld+json">'
        f'{{"@type":"JobPosting","title":"{title}","description":"{description}",'
        f'"industry":"{industry}","experienceRequirements":"5-10年",'
        '"educationRequirements":"本科","employmentType":"全职","datePosted":"2026-08-01",'
        '"hiringOrganization":{"name":"某公司","sameAs":"https://example.com"},'
        '"jobLocation":{"address":{"streetAddress":"海淀区"}}}'
        "</script></head><body></body></html>"
    )
