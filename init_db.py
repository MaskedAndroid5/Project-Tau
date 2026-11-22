import asyncio

from sqlmodel import SQLModel

from app.database import engine
from app import models  # noqa: F401


async def main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
