import pytest

from app import db
from app.services.booking import sweep_expired

pytestmark = pytest.mark.anyio


async def best(client, user, show_id, count):
    return await client.post(f"/api/shows/{show_id}/holds/best", json={"count": count}, headers=user["headers"])


def labels(hold):
    return sorted(s["label"] for s in hold["seats"])


async def test_best_block_is_centred_in_the_sweet_row(client, world, users):
    # 3 rows: the sweet spot is row B (60% back), centre of 6 seats is between 3 and 4
    [u] = users(1)
    r = await best(client, u, world["show_id"], 2)
    assert r.status_code == 201
    assert labels(r.json()) == ["B3", "B4"]


async def test_best_block_skips_broken_rows(client, world, users, sql):
    a, b = users(2)
    s = world["seats"]
    # block B3 so row B has islands [1,2] and [4,5,6]: a group of 3 fits only in 4-6
    await client.post(f"/api/shows/{world['show_id']}/holds", json={"seat_ids": [s["B3"]]}, headers=a["headers"])
    r = await best(client, b, world["show_id"], 3)
    assert labels(r.json()) == ["B4", "B5", "B6"]


async def test_no_block_big_enough(client, world, users):
    [u] = users(1)
    r = await best(client, u, world["show_id"], 7)  # rows only have 6 seats
    assert r.status_code == 409 and r.json()["code"] == "no_block"


async def fill_show(client, world, user, keep=()):
    """Book every seat except the ones in `keep`."""
    ids = [sid for label, sid in world["seats"].items() if label not in keep]
    for i in range(0, len(ids), 10):
        h = (await client.post(f"/api/shows/{world['show_id']}/holds", json={"seat_ids": ids[i:i + 10]},
                               headers=user["headers"])).json()
        b = (await client.post(f"/api/holds/{h['id']}/confirm",
                               headers=user["headers"] | {"Idempotency-Key": f"fill-{i}"})).json()
    return b


async def test_waitlist_gets_seats_when_someone_cancels(client, world, users, sql):
    owner, waiter = users(2)
    last_booking = await fill_show(client, world, owner)
    r = await client.post(f"/api/shows/{world['show_id']}/waitlist", json={"seats_wanted": 2}, headers=waiter["headers"])
    assert r.status_code == 201 and r.json()["status"] == "waiting"

    # the owner cancels the last booking (8 seats) -> the waiter is offered 2 of them as a hold
    await client.post(f"/api/bookings/{last_booking['id']}/cancel", headers=owner["headers"])
    [entry] = (await client.get("/api/waitlist/me", headers=waiter["headers"])).json()
    assert entry["status"] == "offered" and entry["hold_id"]

    [offer] = (await client.get("/api/holds/me", headers=waiter["headers"])).json()
    assert len(offer["seats"]) == 2
    r = await client.post(f"/api/holds/{offer['id']}/confirm", headers=waiter["headers"] | {"Idempotency-Key": "w1"})
    assert r.status_code == 200
    assert sql("SELECT status FROM waitlist")[0]["status"] == "fulfilled"


async def test_waitlist_is_first_come_first_served(client, world, users, sql):
    owner, first, second = users(3)
    await fill_show(client, world, owner, keep=("A1",))
    await client.post(f"/api/shows/{world['show_id']}/waitlist", json={"seats_wanted": 2}, headers=first["headers"])
    await client.post(f"/api/shows/{world['show_id']}/waitlist", json={"seats_wanted": 1}, headers=second["headers"])
    # one seat is free, but the person at the front wants two: nobody jumps the queue
    statuses = [r["status"] for r in sql("SELECT status FROM waitlist ORDER BY id")]
    assert statuses == ["waiting", "waiting"]
    dup = await client.post(f"/api/shows/{world['show_id']}/waitlist", json={"seats_wanted": 1}, headers=first["headers"])
    assert dup.status_code == 409


async def test_unclaimed_offer_expires_and_moves_on(client, world, users, sql):
    owner, first, second = users(3)
    booking = await fill_show(client, world, owner)
    await client.post(f"/api/shows/{world['show_id']}/waitlist", json={"seats_wanted": 8}, headers=first["headers"])
    await client.post(f"/api/shows/{world['show_id']}/waitlist", json={"seats_wanted": 8}, headers=second["headers"])
    await client.post(f"/api/bookings/{booking['id']}/cancel", headers=owner["headers"])  # frees exactly 8 seats
    assert [r["status"] for r in sql("SELECT status FROM waitlist ORDER BY id")] == ["offered", "waiting"]

    sql("UPDATE holds SET expires_at = now() - interval '1 second' WHERE status = 'active'")
    async with db.pool.connection() as conn:
        await sweep_expired(conn)
    assert [r["status"] for r in sql("SELECT status FROM waitlist ORDER BY id")] == ["expired", "offered"]
