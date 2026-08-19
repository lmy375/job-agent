"""测试夹具。

原则：**测试不碰真实的 jobs.db，也不发任何网络请求**。
每个测试都在临时目录里搭一套完整的 config/ + data/，
这样也顺便验证了「换一个项目根目录也能跑」这件事。
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from job_agent.config import Settings, load_settings
from job_agent.context import AppContext
from job_agent.core.liepin.models import Job

REPO_ROOT = Path(__file__).resolve().parents[1]

CONFIG_TOML = """
[profile]
name = "测试用户"
resume = "config/resume.md"

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

[liepin]
rate_limit_per_min = 60

[detail]
sleep_min = 0
sleep_max = 0
block_backoff = 0
max_retries = 2

[storage]
database = "data/test.db"

[report]
output = "data/report.html"
insights_dir = "config/insights"

[logging]
level = "WARNING"
"""


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """一个可用的项目根目录（config/ + data/）。"""
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config" / "config.toml").write_text(CONFIG_TOML, encoding="utf-8")
    (tmp_path / "config" / "resume.md").write_text("# 测试简历\n", encoding="utf-8")
    (tmp_path / "config" / ".env").write_text("LIEPIN_USER_TOKEN=test-token\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    # 真实环境里的 token 不能泄进测试，否则「缺 token」的用例会假通过
    monkeypatch.delenv("LIEPIN_USER_TOKEN", raising=False)
    return load_settings(project_root / "config" / "config.toml")


@pytest.fixture
def context(settings: Settings) -> Iterator[AppContext]:
    ctx = AppContext.from_settings(settings)
    yield ctx
    ctx.close()


@pytest.fixture
def insights_dir(project_root: Path) -> Path:
    """把仓库里的 insights 模板复制过来。

    用 ``insights.example``（进版本库）而不是用户自己的 ``insights``（不进版本库），
    这样新克隆下来测试也能跑，顺带验证模板本身始终可解析。
    """
    target = project_root / "config" / "insights"
    shutil.copytree(REPO_ROOT / "config" / "insights.example", target)
    return target


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
