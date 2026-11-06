"""Live load test against a running server: N users hit the same seat at once.

    python run.py                       # in one terminal
    python -m scripts.race_test -n 200  # in another

Creates N throwaway users (race<i>@seatlock.test), fires all hold requests
together over real HTTP, prints who won, then cleans everything up.
"""
import argparse
import asyncio
import sys
import time
from collections import Counter

import httpx
import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.security import create_token, hash_password


def setup(n: int):
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        pw = hash_password("Race@1234")
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            [(f"race{i}@seatlock.test", f"Race {i}", pw) for i in range(n)])
        users = conn.execute("SELECT id FROM users WHERE email LIKE 'race%%@seatlock.test' ORDER BY id LIMIT %s",
                             (n,)).fetchall()
        target = conn.execute("""
            SELECT ss.show_id, ss.seat_id, s.row_label || s.seat_number AS label, sh.title
            FROM show_seats ss JOIN seats s ON s.id = ss.seat_id JOIN shows sh ON sh.id = ss.show_id
            WHERE ss.status = 'available' AND sh.starts_at > now()
            ORDER BY sh.starts_at, s.row_index, s.seat_number LIMIT 1""").fetchone()
    return [create_token(u["id"], "user") for u in users], target


def cleanup():
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        race = "SELECT id FROM users WHERE email LIKE 'race%%@seatlock.test'"
        conn.execute(f"UPDATE show_seats SET status = 'available', hold_id = NULL "
                     f"WHERE hold_id IN (SELECT id FROM holds WHERE user_id IN ({race}))")
        conn.execute(f"DELETE FROM holds WHERE user_id IN ({race})")
        conn.execute("DELETE FROM users WHERE email LIKE 'race%%@seatlock.test'")


async def race(base: str, tokens: list[str], target: dict):
    limits = httpx.Limits(max_connections=len(tokens), max_keepalive_connections=len(tokens))
    async with httpx.AsyncClient(base_url=base, limits=limits, timeout=60) as client:
        async def attempt(token):
            r = await client.post(f"/api/shows/{target['show_id']}/holds", json={"seat_ids": [target["seat_id"]]},
                                  headers={"Authorization": f"Bearer {token}"})
            return r.status_code
        start = time.perf_counter()
        codes = await asyncio.gather(*[attempt(t) for t in tokens])
        return Counter(codes), time.perf_counter() - start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--base", default="http://127.0.0.1:8030")
    args = ap.parse_args()

    tokens, target = setup(args.n)
    print(f"{args.n} users -> seat {target['label']} of '{target['title']}' (show {target['show_id']})")
    try:
        if sys.platform == "win32":
            codes, secs = asyncio.run(race(args.base, tokens, target), loop_factory=asyncio.SelectorEventLoop)
        else:
            codes, secs = asyncio.run(race(args.base, tokens, target))
    finally:
        cleanup()
    print(f"  201 Created (won the seat): {codes.get(201, 0)}")
    print(f"  409 Conflict (seat taken) : {codes.get(409, 0)}")
    others = {c: k for c, k in codes.items() if c not in (201, 409)}
    print(f"  anything else             : {others or 0}")
    print(f"  all {args.n} requests answered in {secs:.2f} s")
    sys.exit(0 if codes.get(201) == 1 and not others else 1)


if __name__ == "__main__":
    main()
