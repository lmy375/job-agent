"""应用上下文：一次性把配置、数据库、仓储装好，交给 CLI / Web 复用。

有了它，业务代码不再各自去 ``load_settings()`` 和建 engine——
测试里换一个 :class:`AppContext` 就能整体指向临时库。
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from pydantic import BaseModel, ConfigDict

from job_agent.config import Settings, load_settings
from job_agent.core.liepin import LiepinClient
from job_agent.core.storage import (
    ApplicationRepository,
    Database,
    DetailRepository,
    JobRepository,
    ScoreRepository,
)
from job_agent.errors import ConfigError
from job_agent.log import get_logger, setup_logging

logger = get_logger(__name__)


class AppContext(BaseModel):
    # 装的是数据库句柄与仓储，都不是 pydantic 类型，所以要放行任意类型
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    settings: Settings
    db: Database
    jobs: JobRepository
    details: DetailRepository
    applications: ApplicationRepository
    scores: ScoreRepository

    @classmethod
    def create(
        cls,
        profile: str | None = None,
        config_file: Path | None = None,
        log_level: str | None = None,
        console_level: str | None = None,
        configure_logging: bool = True,
    ) -> AppContext:
        settings = load_settings(profile, config_file)
        if configure_logging:
            setup_logging(
                level=log_level or settings.logging.level,
                file=settings.logging.file,
                console_level=log_level or console_level,
                force=True,
            )
        logger.debug(
            "profile=%s 配置来源：%s + %s",
            settings.profile_name,
            settings.config_file or "（内置默认值）",
            settings.profile_file or "（profile.toml 缺失，全用默认值）",
        )
        return cls.from_settings(settings)

    @classmethod
    def from_settings(cls, settings: Settings) -> AppContext:
        db = Database.from_settings(settings).setup()
        return cls(
            settings=settings,
            db=db,
            jobs=JobRepository(db),
            details=DetailRepository(db),
            applications=ApplicationRepository(db),
            scores=ScoreRepository(db),
        )

    def reload_settings(self) -> Settings:
        """重新读一遍当前 profile 的两份配置文件并换上。

        Web 管理台改完 ``profile.toml``（关键词、``[score]``）之后调它：
        生效的永远是**文件里那份**，而不是内存里攒出来的一份改动——
        「页面上改了但 CLI 跑的是另一套」就是这么来的。

        按 profile **目录**重新定位（而不是名字）：目录是这次运行已经认定的那个，
        不该因为期间有人改了 ``[profiles].default`` 就换一个库。

        数据库路径变了就拒绝——仓储握的是旧库的连接，换设置不换连接会变成
        「设置说 A、读写落在 B」。那种情况重启服务即可。
        """
        fresh = load_settings(
            profile=str(self.settings.profile_dir),
            config_file=self.settings.config_file,
            root=self.settings.root,
        )
        if fresh.storage.database != self.settings.storage.database:
            raise ConfigError(
                f"[storage].database 改了（{self.settings.storage.database} → "
                f"{fresh.storage.database}），热加载不换库连接，请重启服务"
            )
        self.settings = fresh
        return fresh

    def client(self) -> LiepinClient:
        """新建一个猎聘客户端（限速窗口是实例级的，别跨线程共用）。"""
        return LiepinClient.from_settings(self.settings)

    def close(self) -> None:
        self.db.dispose()

    def __enter__(self) -> AppContext:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
