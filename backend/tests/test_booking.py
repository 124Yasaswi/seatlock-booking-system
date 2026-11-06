import pytest

from app import db
from app.services.booking import sweep_expired

pytestmark = pytest.mark.anyio


async def hold(client, user, show_id, seat_ids):
    return await client.post(f"/api/shows/{show_id}/holds", json={"seat_ids": seat_ids}, headers=user["headers"])


async def confirm(client, user, hold_id, key="key-1"):
    return await client.post(f"/api/holds/{hold_id}/confirm", headers=user["headers"] | {"Idempotency-Key": key})


def seat_status(sql, show_id, seat_id):
    return sql("SELECT status FROM show_seats WHERE show_id = %s AND seat_id = %s", (show_id, seat_id))[0]["status"]


async def test_hold_then_confirm(client, world, users, sql):
    [u] = users(1)
    s = world["seats"]
    r = await hold(client, u, world["show_id"], [s["A1"], s["C1"]])
    assert r.status_code == 201
    h = r.json()
    assert h["amount_paise"] == 20000 + 30000  # one regular + one premium
    assert seat_status(sql, world["show_id"], s["A1"]) == "held"

    r = await confirm(client, u, h["id"])
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "confirmed" and sorted(b["seats"]) == ["A1", "C1"] and b["replayed"] is False
    assert seat_status(sql, world["show_id"], s["A1"]) == "booked"
    assert sql("SELECT status FROM holds WHERE id = %s", (h["id"],))[0]["status"] == "converted"


async def test_second_user_cannot_take_held_seat(client, world, users):
    a, b = users(2)
    s = world["seats"]
    assert (await hold(client, a, world["show_id"], [s["B3"], s["B4"]])).status_code == 201
    r = await hold(client, b, world["show_id"], [s["B4"], s["B5"]])
    assert r.status_code == 409
    assert r.json()["code"] == "seats_taken" and r.json()["seat_ids"] == [s["B4"]]


async def test_same_pay_click_twice_gives_one_booking(client, world, users, sql):
    [u] = users(1)
    h = (await hold(client, u, world["show_id"], [world["seats"]["A2"]])).json()
    first = (await confirm(client, u, h["id"], "same-key")).json()
    again = await confirm(client, u, h["id"], "same-key")
    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["replayed"] is True
    assert sql("SELECT COUNT(*) AS n FROM bookings")[0]["n"] == 1


async def test_reusing_a_key_for_another_hold_is_refused(client, world, users):
    [u] = users(1)
    s = world["seats"]
    h1 = (await hold(client, u, world["show_id"], [s["A1"]])).json()
    assert (await confirm(client, u, h1["id"], "k")).status_code == 200
    h2 = (await hold(client, u, world["show_id"], [s["A2"]])).json()
    r = await confirm(client, u, h2["id"], "k")
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_reused"


async def test_missing_idempotency_key(client, world, users):
    [u] = users(1)
    h = (await hold(client, u, world["show_id"], [world["seats"]["A1"]])).json()
    r = await client.post(f"/api/holds/{h['id']}/confirm", headers=u["headers"])
    assert r.status_code == 400


async def test_expired_hold_cannot_be_paid_and_seat_is_free_again(client, world, users, sql):
    a, b = users(2)
    seat = world["seats"]["B2"]
    h = (await hold(client, a, world["show_id"], [seat])).json()
    sql("UPDATE holds SET expires_at = now() - interval '1 second' WHERE id = %s", (h["id"],))

    r = await confirm(client, a, h["id"])
    assert r.status_code == 410 and r.json()["code"] == "hold_expired"
    # someone else can take the seat at once, even before the sweeper runs
    assert (await hold(client, b, world["show_id"], [seat])).status_code == 201


async def test_sweeper_releases_expired_holds(client, world, users, sql):
    [u] = users(1)
    seat = world["seats"]["C6"]
    h = (await hold(client, u, world["show_id"], [seat])).json()
    sql("UPDATE holds SET expires_at = now() - interval '1 second' WHERE id = %s", (h["id"],))
    async with db.pool.connection() as conn:
        changes = await sweep_expired(conn)
    assert {"show_id": world["show_id"], "seat_id": seat, "status": "available"} in changes
    assert seat_status(sql, world["show_id"], seat) == "available"
    assert sql("SELECT status FROM holds WHERE id = %s", (h["id"],))[0]["status"] == "expired"


async def test_new_hold_replaces_old_one(client, world, users, sql):
    [u] = users(1)
    s = world["seats"]
    h1 = (await hold(client, u, world["show_id"], [s["A1"], s["A2"]])).json()
    h2 = (await hold(client, u, world["show_id"], [s["A2"], s["A3"]])).json()
    assert seat_status(sql, world["show_id"], s["A1"]) == "available"
    assert seat_status(sql, world["show_id"], s["A3"]) == "held"
    assert sql("SELECT status FROM holds WHERE id = %s", (h1["id"],))[0]["status"] == "released"
    assert (await confirm(client, u, h2["id"])).status_code == 200


async def test_release_hold(client, world, users, sql):
    [u] = users(1)
    h = (await hold(client, u, world["show_id"], [world["seats"]["A4"]])).json()
    assert (await client.delete(f"/api/holds/{h['id']}", headers=u["headers"])).status_code == 204
    assert seat_status(sql, world["show_id"], world["seats"]["A4"]) == "available"


async def test_cancel_booking_frees_seats(client, world, users, sql):
    [u] = users(1)
    seat = world["seats"]["B1"]
    h = (await hold(client, u, world["show_id"], [seat])).json()
    b = (await confirm(client, u, h["id"])).json()
    r = await client.post(f"/api/bookings/{b['id']}/cancel", headers=u["headers"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert seat_status(sql, world["show_id"], seat) == "available"
    again = await client.post(f"/api/bookings/{b['id']}/cancel", headers=u["headers"])
    assert again.status_code == 409


async def test_cannot_cancel_someone_elses_booking(client, world, users):
    a, b = users(2)
    h = (await hold(client, a, world["show_id"], [world["seats"]["B1"]])).json()
    bk = (await confirm(client, a, h["id"])).json()
    assert (await client.post(f"/api/bookings/{bk['id']}/cancel", headers=b["headers"])).status_code == 404


async def test_started_show_and_bad_input(client, world, users, sql):
    [u] = users(1)
    s = world["seats"]
    assert (await hold(client, u, world["show_id"], [999999])).status_code == 404
    assert (await hold(client, u, world["show_id"], list(s.values())[:11])).status_code == 422  # more than 10
    sql("UPDATE shows SET starts_at = now() - interval '1 minute'")
    r = await hold(client, u, world["show_id"], [s["A1"]])
    assert r.status_code == 409 and r.json()["code"] == "show_started"


async def test_show_listing_and_seat_map(client, world, users):
    [u] = users(1)
    await hold(client, u, world["show_id"], [world["seats"]["A1"]])
    shows = (await client.get("/api/shows")).json()
    assert shows[0]["seats_total"] == 18 and shows[0]["seats_free"] == 17
    detail = (await client.get(f"/api/shows/{world['show_id']}")).json()
    statuses = {x["id"]: x["status"] for x in detail["seats"]}
    assert statuses[world["seats"]["A1"]] == "held" and statuses[world["seats"]["A2"]] == "available"
