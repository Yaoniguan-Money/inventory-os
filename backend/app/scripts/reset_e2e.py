"""重建 e2e 数据库并写入 Demo 数据（供 Playwright 使用）。"""

from __future__ import annotations

import asyncio

from app.core.database import Base, engine
from app.scripts.seed import seed_business, seed_identity


async def run() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await seed_identity()
    await seed_business()
    print("E2E database rebuilt and seeded")


if __name__ == "__main__":
    asyncio.run(run())
