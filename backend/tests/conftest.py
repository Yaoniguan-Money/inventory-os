from __future__ import annotations

import os

# Point the app at the dedicated test database BEFORE importing app modules.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://inventory:inventory_dev_password@localhost:5433/inventory_os_test",
)
os.environ["APP_ENV"] = "test"

from collections.abc import AsyncIterator  # noqa: E402

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import (  # noqa: E402
    Base,
    engine,
    new_session,  # noqa: E402
)
from app.core.security import create_access_token  # noqa: E402
from app.domains.identity.service import create_organization_with_admin  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def prepare_database() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(prepare_database: None) -> AsyncIterator[None]:
    table_names = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest_asyncio.fixture
async def org_owner_headers() -> dict[str, str]:
    async with new_session() as db:
        org, user, _ = await create_organization_with_admin(
            db,
            name="测试组织",
            slug="test-org",
            admin_email="owner@example.com",
            admin_password="Owner@12345",
            display_name="Owner",
        )
        await db.commit()
        token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_org_headers() -> dict[str, str]:
    async with new_session() as db:
        org, user, _ = await create_organization_with_admin(
            db,
            name="另一组织",
            slug="other-org",
            admin_email="owner2@example.com",
            admin_password="Owner2@12345",
            display_name="Owner2",
        )
        await db.commit()
        token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}
