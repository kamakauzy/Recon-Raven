"""
Database engine and session factory — SQLite with WAL mode.
"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

_engine = None
_session_factory = None


def get_engine(db_path: str):
    global _engine
    if _engine is None:
        url = f"sqlite+aiosqlite:///{db_path}"
        _engine = create_async_engine(url, echo=False)

        @event.listens_for(_engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return _engine


def get_session_factory(db_path: str) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine(db_path)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def init_db(db_path: str):
    """Create all tables."""
    from .models import Base
    engine = get_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
