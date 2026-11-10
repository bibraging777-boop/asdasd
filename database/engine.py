"""Engine / session factory construction."""
from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from database.models import Base


def create_engine_and_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, pool_pre_ping=True)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """Create missing tables. Use Alembic migrations once the schema evolves."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
