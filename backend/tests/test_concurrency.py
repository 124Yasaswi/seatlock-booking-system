"""The headline tests: many people clicking at the same moment.

asyncio.gather fires all requests together; the app runs them on up to 30
database connections in parallel, so PostgreSQL really sees competing
transactions on the same rows.
"""
import asyncio
import itertools

import pytest

pytestmark = pytest.mark.anyio


async def test_200_users_one_seat_exactly_one_winner(client, world, users, sql):
    people = users(200)
    seat = world["seats"]["B3"]
    results = await asyncio.gather(*[
        client.post(f"/api/shows/{world['show_id']}/holds", json={"seat_ids": [seat]}, headers=p["headers"])
        for p in people])
    codes = [r.status_code for r in results]
    assert codes.count(201) == 1
    assert codes.count(409) == 199
    assert sql("SELECT COUNT(*) AS n FROM holds WHERE status = 'active'")[0]["n"] == 1


async def test_overlapping_group_holds_never_share_a_seat(client, world, users, sql):
    # 60 people each want 3 seats in row B; their requests overlap in every possible way
    people = users(60)
    row_b = [world["seats"][f"B{n}"] for n in range(1, 7)]
    windows = [row_b[i:i + 3] for i in range(4)]
    results = await asyncio.gather(*[
        client.post(f"/api/shows/{world['show_id']}/holds", json={"seat_ids": windows[i % 4]}, headers=p["headers"])
        for i, p in enumerate(people)])
    won = [r.json() for r in results if r.status_code == 201]
    assert all(r.status_code in (201, 409) for r in results)  # no 500s, no deadlocks
    seats = [s["seat_id"] for h in won for s in h["seats"]]
    assert len(seats) == len(set(seats))  # nobody shares a seat
    held = sql("SELECT COUNT(*) AS n FROM show_seats WHERE status = 'held'")[0]["n"]
    assert held == len(seats)


async def test_best_seats_rush(client, world, users, sql):
    # 40 people press "best 2 seats" at once on an 18-seat show: at most 9 can win
    people = users(40)
    results = await asyncio.gather(*[
        client.post(f"/api/shows/{world['show_id']}/holds/best", json={"count": 2}, headers=p["headers"])
        for p in people])
    won = [r.json() for r in results if r.status_code == 201]
    assert all(r.status_code in (201, 409) for r in results)
    seats = list(itertools.chain.from_iterable([s["seat_id"] for s in h["seats"]] for h in won))
    assert len(seats) == len(set(seats)) and len(won) <= 9
    assert sql("SELECT COUNT(*) AS n FROM show_seats WHERE status = 'held'")[0]["n"] == len(seats)


async def test_double_click_pay_from_many_tabs(client, world, users, sql):
    [u] = users(1)
    h = (await client.post(f"/api/shows/{world['show_id']}/holds", json={"seat_ids": [world["seats"]["A1"]]},
                           headers=u["headers"])).json()
    # 20 parallel "Pay" requests, half with the same key and half with different keys
    results = await asyncio.gather(*[
        client.post(f"/api/holds/{h['id']}/confirm", headers=u["headers"] | {"Idempotency-Key": f"k{i % 2 * i}"})
        for i in range(20)])
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()["id"] for r in results}) == 1  # every tab sees the same single booking
    assert sql("SELECT COUNT(*) AS n FROM bookings")[0]["n"] == 1
