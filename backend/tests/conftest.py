import os

# Point the app at the test database before it is imported.
os.environ.setdefault("TEST_DATABASE_URL", "postgresql://seatlock:seatlock_dev_pw@localhost:5433/seatlock_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["RUN_SWEEPER"] = "false"
os.environ["DB_POOL_MAX"] = "30"

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import httpx  # noqa: E402
import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_token, hash_password  # noqa: E402
from scripts.init_db import init  # noqa: E402

URL = os.environ["DATABASE_URL"]
PW_HASH = hash_password("Passw0rd!")  # hashed once: bcrypt is slow on purpose


@pytest.fixture(scope="session", autouse=True)
def schema():
    init(URL, reset=True)


@pytest.fixture
def anyio_backend():
    # psycopg's async mode needs a selector event loop (Windows defaults to Proactor)
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


@pytest.fixture
def sql():
    """Plain synchronous connection for arranging and checking data in tests."""
    with psycopg.connect(URL, autocommit=True, row_factory=dict_row) as conn:
        yield lambda q, p=(): conn.execute(q, p).fetchall() if conn.execute(q, p).description else []


@pytest.fixture
def world(schema):
    """Fresh data for every test: one venue (3 rows x 6 seats, row C premium) and one show tomorrow."""
    with psycopg.connect(URL, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("TRUNCATE users, venues, seats, shows, holds, bookings, booking_seats, show_seats, waitlist "
                     "RESTART IDENTITY CASCADE")
        venue = conn.execute("INSERT INTO venues (name, city) VALUES ('Test Hall', 'Hyderabad') RETURNING id").fetchone()["id"]
        for r in range(3):
            for n in range(1, 7):
                conn.execute("INSERT INTO seats (venue_id, row_label, row_index, seat_number, category) "
                             "VALUES (%s, %s, %s, %s, %s)", (venue, "ABC"[r], r, n, "premium" if r == 2 else "regular"))
        show = conn.execute("""INSERT INTO shows (venue_id, title, starts_at, regular_price_paise, premium_price_paise)
                               VALUES (%s, 'Test Movie', %s, 20000, 30000) RETURNING id""",
                            (venue, datetime.now(timezone.utc) + timedelta(days=1))).fetchone()["id"]
        conn.execute("INSERT INTO show_seats (show_id, seat_id) SELECT %s, id FROM seats WHERE venue_id = %s", (show, venue))
        seats = {f'{r["row_label"]}{r["seat_number"]}': r["id"] for r in
                 conn.execute("SELECT id, row_label, seat_number FROM seats").fetchall()}
        return {"venue_id": venue, "show_id": show, "seats": seats}


@pytest.fixture
async def client(world):
    await db.open_pool(URL)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await db.close_pool()


def make_users(n: int, role: str = "user") -> list[dict]:
    """Insert users straight into the database and return auth headers for each."""
    with psycopg.connect(URL, autocommit=True, row_factory=dict_row) as conn:
        start = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM users").fetchone()["m"]
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO users (email, name, password_hash, role) VALUES (%s, %s, %s, %s)",
                            [(f"u{start + i}@test.local", f"U{i}", PW_HASH, role) for i in range(1, n + 1)])
        rows = conn.execute("SELECT id FROM users WHERE id > %s ORDER BY id", (start,)).fetchall()
    return [{"id": r["id"], "headers": {"Authorization": f"Bearer {create_token(r['id'], role)}"}} for r in rows]


@pytest.fixture
def users():
    return make_users
