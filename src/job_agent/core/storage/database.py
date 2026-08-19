"""数据库句柄。

刻意不用模块级全局 engine：Web 服务、CLI、测试各自需要指向不同的库，
全局单例会让测试只能对着真实的 jobs.db 跑。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from job_agent.core.storage.migrations import run_migrations
from job_agent.core.storage.models import Base
from job_agent.errors import StorageError
from job_agent.log import get_logger

if TYPE_CHECKING:
    from job_agent.config import Settings

logger = get_logger(__name__)

#: 等锁时长。Web 端一边采集一边查询时，没有它会直接报 "database is locked"
BUSY_TIMEOUT_MS = 5000


class Database:
    """一个 SQLite 数据库文件的连接与会话工厂。"""

    def __init__(self, path: Path | str, echo: bool = False) -> None:
        self.path = Path(path)
        if self.path.parent and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        url = "sqlite://" if str(self.path) == ":memory:" else f"sqlite:///{self.path}"
        # check_same_thread=False：Web 端的后台采集线程与请求线程会共用同一个库
        self.engine: Engine = create_engine(
            url, echo=echo, connect_args={"check_same_thread": False}
        )
        _apply_pragmas(self.engine, wal=str(self.path) != ":memory:")
        self._sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Settings, echo: bool = False) -> Database:
        return cls(settings.storage.database, echo=echo)

    def setup(self) -> Database:
        """建表 + 跑轻量迁移。幂等，每个入口启动时调一次即可。"""
        try:
            Base.metadata.create_all(self.engine)
            run_migrations(self.engine)
        except SQLAlchemyError as exc:
            raise StorageError(f"数据库初始化失败（{self.path}）：{exc}") from exc
        return self

    @contextmanager
    def session(self) -> Iterator[Session]:
        """会话上下文：正常退出自动 commit，异常自动 rollback。"""
        session = self._sessionmaker()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"数据库操作失败：{exc}") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()

    def __repr__(self) -> str:
        return f"Database(path={self.path})"


def _apply_pragmas(engine: Engine, wal: bool) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
        cursor = dbapi_conn.cursor()
        try:
            if wal:
                # WAL：读不阻塞写。采集在跑的时候 Web 端还要能查
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
