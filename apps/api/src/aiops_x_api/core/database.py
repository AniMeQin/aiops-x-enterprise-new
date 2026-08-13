from collections.abc import AsyncIterator
from functools import lru_cache

from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.observability import DB_POOL_CHECKED_OUT, DB_POOL_SIZE
from aiops_x_api.core.telemetry import configure_tracer_provider

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    provider = configure_tracer_provider()
    if provider is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=provider)
    pool = engine.sync_engine.pool
    size = getattr(pool, "size", None)
    checkedout = getattr(pool, "checkedout", None)
    if callable(size):
        DB_POOL_SIZE.set_function(size)
    if callable(checkedout):
        DB_POOL_CHECKED_OUT.set_function(checkedout)
    return engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def database_is_ready() -> bool:
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
