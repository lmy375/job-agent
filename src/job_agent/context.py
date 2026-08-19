"""应用上下文：一次性把配置、数据库、仓储装好，交给 CLI / Web 复用。

有了它，业务代码不再各自去 ``load_settings()`` 和建 engine——
测试里换一个 :class:`AppContext` 就能整体指向临时库。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from job_agent.config import Settings, load_settings
from job_agent.core.liepin import LiepinClient
from job_agent.core.storage import (
    ApplicationRepository,
    Database,
    DetailRepository,
    JobRepository,
)
from job_agent.log import get_logger, setup_logging

logger = get_logger(__name__)


@dataclass(slots=True)
class AppContext:
    settings: Settings
    db: Database
    jobs: JobRepository
    details: DetailRepository
    applications: ApplicationRepository

    @classmethod
    def create(
        cls,
        config_file: Path | None = None,
        log_level: str | None = None,
        console_level: str | None = None,
        configure_logging: bool = True,
    ) -> AppContext:
        settings = load_settings(config_file)
        if configure_logging:
            setup_logging(
                level=log_level or settings.logging.level,
                file=settings.logging.file,
                console_level=log_level or console_level,
                force=True,
            )
        logger.debug("配置来源：%s", settings.config_file or "（内置默认值）")
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
        )

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
