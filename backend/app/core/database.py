from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    pass


_poolclass = pool.NullPool if settings.app_env == "test" else pool.AsyncAdaptedQueuePool
engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=_poolclass)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def new_session() -> AsyncSession:
    return SessionLocal()
