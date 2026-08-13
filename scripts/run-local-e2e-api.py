"""Run an isolated local API for browser E2E without external infrastructure."""

import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import Base, get_session
from aiops_x_api.main import create_app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def main() -> None:
    database_path = Path(tempfile.mkdtemp(prefix="aiops-x-e2e-")) / "control-plane.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield
        await engine.dispose()

    os.environ.setdefault("AIOPS_OTEL_EXPORTER_OTLP_ENDPOINT", "")
    get_settings.cache_clear()
    application = create_app()
    application.router.lifespan_context = lifespan
    application.dependency_overrides[get_session] = override_session
    uvicorn.run(application, host="127.0.0.1", port=18000, log_level="warning")


if __name__ == "__main__":
    main()
