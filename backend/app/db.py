"""Connection pool. Every request borrows one connection for its lifetime."""
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

pool: AsyncConnectionPool | None = None


async def open_pool(conninfo: str | None = None) -> AsyncConnectionPool:
    global pool
    pool = AsyncConnectionPool(conninfo or settings.database_url, min_size=2, max_size=settings.db_pool_max,
                               kwargs={"row_factory": dict_row, "autocommit": True}, open=False)
    await pool.open(wait=True)
    return pool


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


async def get_conn():
    """FastAPI dependency. Connections are in autocommit mode; services open
    explicit transactions (`async with conn.transaction()`) where it matters."""
    async with pool.connection() as conn:
        yield conn
