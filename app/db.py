from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(
    get_settings().database_url,
    pool_size=get_settings().db_pool_size,
    max_overflow=get_settings().db_max_overflow,
    pool_timeout=60,
    # A managed database may close idle connections (Neon suspends after 5 idle minutes) while
    # this process stays up. Without this the first request afterwards picks up a dead pooled
    # connection and crashes ("connection is closed"); with it the pool tests a connection
    # before handing it out and quietly replaces a dead one.
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
