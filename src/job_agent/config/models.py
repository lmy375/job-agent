"""配置模型。

所有模型都是 ``extra="forbid"``：配置项拼错时立刻报错，而不是被静默忽略
——静默忽略是配置系统最容易埋的坑（比如把 salary_floor 写成 salaryFloor，
结果搜出一堆不达标的岗位却毫无提示）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from job_agent.core.liepin.constants import (
    DEFAULT_BASE_URL,
    DEFAULT_RATE_LIMIT_PER_MIN,
    DEFAULT_TIMEOUT,
    MAX_PAGE,
)
from job_agent.core.liepin.enums import EduLevel, SalaryKind, WorkExperience
from job_agent.errors import MissingTokenError
from job_agent.tracks import TrackName


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ProfileConfig(_Model):
    """求职者信息。只用于报告标题与「简历建议」章节。"""

    name: str = ""
    resume: Path = Path("config/resume.md")


class KeywordGroup(_Model):
    """一组同赛道的搜索关键词。

    ``track`` 除了给报告分组，还是分类兜底的依据：职位名看不出赛道时
    （「技术专家」「负责人」这类），按关键词所属赛道 + JD 正文信号词判定。
    """

    track: TrackName
    keywords: list[str] = Field(min_length=1)
    enabled: bool = True

    @field_validator("keywords")
    @classmethod
    def _strip(cls, value: list[str]) -> list[str]:
        cleaned = [k.strip() for k in value if k.strip()]
        if not cleaned:
            raise ValueError("keywords 不能为空")
        return cleaned


class SearchConfig(_Model):
    """搜索条件。字段留空即不按该维度过滤。"""

    address: str | None = "北京"
    salary_kind: SalaryKind | None = None
    # 单位为「元」，按薪资区间**重叠**过滤（不是「下限 ≥ 该值」），
    # salaryKind=年薪 时把职位薪资年化后比较。数值过小（如 50）等同不过滤。
    salary_floor: int | None = Field(default=None, ge=0)
    salary_cap: int | None = Field(default=None, ge=0)
    edu_level: EduLevel | None = None
    work_experience: WorkExperience | None = None
    max_pages: int = Field(default=MAX_PAGE, ge=1, le=MAX_PAGE)
    groups: list[KeywordGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_salary(self) -> SearchConfig:
        if (
            self.salary_cap is not None
            and self.salary_floor is not None
            and self.salary_cap < self.salary_floor
        ):
            raise ValueError("salary_cap 不能小于 salary_floor")
        if (self.salary_floor or self.salary_cap) and self.salary_kind is None:
            raise ValueError("配置了 salary_floor / salary_cap 时必须同时给出 salary_kind")
        return self

    @property
    def enabled_groups(self) -> list[KeywordGroup]:
        return [g for g in self.groups if g.enabled]

    @property
    def keywords(self) -> list[str]:
        """按配置顺序（= 优先级）展开的关键词，去重且保留首次出现的位置。"""
        seen: dict[str, None] = {}
        for group in self.enabled_groups:
            for keyword in group.keywords:
                seen.setdefault(keyword, None)
        return list(seen)

    def track_for_keyword(self, keyword: str) -> str | None:
        """关键词属于哪条赛道；未配置过的关键词返回 None。

        禁用的组也参与匹配：库里存量数据的 searchKeyword 可能来自已关掉的组，
        分类时仍然要认得它。
        """
        target = keyword.strip().lower()
        if not target:
            return None
        for group in self.groups:
            for configured in group.keywords:
                if configured.strip().lower() == target:
                    return group.track
        return None


class LiepinConfig(_Model):
    """猎聘 API 客户端参数。"""

    base_url: str = DEFAULT_BASE_URL
    timeout: float = Field(default=DEFAULT_TIMEOUT, gt=0)
    # 调大有风险：服务端限流触发后冷却 20 分钟以上，期间任何请求都被拒
    rate_limit_per_min: int = Field(default=DEFAULT_RATE_LIMIT_PER_MIN, ge=1, le=60)


class DetailConfig(_Model):
    """详情页抓取参数。详情页是普通网页、不走 API，节奏得自己控。"""

    sleep_min: float = Field(default=1.2, ge=0)
    sleep_max: float = Field(default=2.5, ge=0)
    block_backoff: float = Field(default=300.0, ge=0)
    max_retries: int = Field(default=3, ge=1)
    timeout: float = Field(default=30.0, gt=0)
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @model_validator(mode="after")
    def _check_sleep(self) -> DetailConfig:
        if self.sleep_max < self.sleep_min:
            raise ValueError("sleep_max 不能小于 sleep_min")
        return self


class StorageConfig(_Model):
    database: Path = Path("data/jobs.db")


class ReportConfig(_Model):
    output: Path = Path("data/job-report.html")
    insights_dir: Path = Path("config/insights")


class WebConfig(_Model):
    host: str = "127.0.0.1"
    port: int = Field(default=18000, ge=1, le=65535)
    open_browser: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    #: 前端构建产物目录；不存在时后端只提供 API
    frontend_dist: Path = Path("frontend/dist")


class LoggingConfig(_Model):
    level: str = "INFO"
    file: Path | None = None

    @field_validator("level")
    @classmethod
    def _upper(cls, value: str) -> str:
        level = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"level 只能是 {'/'.join(sorted(allowed))}")
        return level


class Settings(_Model):
    """整个应用的配置树。

    ``root`` / ``config_file`` / ``token`` 不来自 TOML，由 loader 注入；
    所有路径字段在 loader 里已解析为绝对路径。
    """

    root: Path
    config_file: Path | None = None
    token: str | None = None

    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    liepin: LiepinConfig = Field(default_factory=LiepinConfig)
    detail: DetailConfig = Field(default_factory=DetailConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def require_token(self) -> str:
        """取 token，没有就抛 :class:`MissingTokenError`。"""
        if not (self.token or "").strip():
            raise MissingTokenError
        return str(self.token).strip()

    def redacted(self) -> dict[str, Any]:
        """脱敏后的配置字典，可安全地打印或经 API 返回。"""
        data = self.model_dump(mode="json")
        data["token"] = "已配置" if (self.token or "").strip() else None
        return data
