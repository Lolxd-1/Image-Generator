"""Async SQLAlchemy engine, session factory, declarative base, and FastAPI DB dependency."""
import logging
from collections.abc import AsyncGenerator
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# Supabase's connection string on port 6543 is PgBouncer in *transaction*
# pooling mode, and that breaks asyncpg's defaults in two ways:
#
#   1. asyncpg caches prepared statements per connection. PgBouncer hands the
#      same server connection to different clients between transactions, so a
#      cached statement can vanish underneath us -> "prepared statement
#      _asyncpg_stmt_x_ does not exist" at random.
#   2. SQLAlchemy's asyncpg dialect names prepared statements predictably, so
#      two pooled clients can collide -> "prepared statement already exists".
#
# Disabling both caches and giving every statement a UUID name is the
# documented fix. NullPool on top, because pooling on our side behind a pooler
# just holds Supabase connections open for no benefit.
_connect_args: dict = {}
if "pooler.supabase.com" in settings.DATABASE_URL or ":6543" in settings.DATABASE_URL:
    _connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        # The pooler terminates idle connections; don't sit on a dead socket.
        "server_settings": {"jit": "off"},
    }

engine = create_async_engine(
    settings.DATABASE_URL,
    future=True,
    poolclass=NullPool if _connect_args else None,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def init_models() -> None:
    # No Alembic by design (SPEC.md §2): one deployment, one schema owner.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # create_all never adds a column to a table that already exists, and a
    # deployed instance already has pace_state; a hard failure here would
    # take the app down at boot on a database we cannot migrate, which is
    # worse than running without the column.
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("ALTER TABLE pace_state ADD COLUMN IF NOT EXISTS leased_until TIMESTAMPTZ")
            )
    except Exception:
        logger.warning("failed to add pace_state.leased_until column", exc_info=True)
