from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.anyio


async def book(client, user, show_id, seat_ids, key):
    h = (await client.post(f"/api/shows/{show_id}/holds", json={"seat_ids": seat_ids}, headers=user["headers"])).json()
    return (await client.post(f"/api/holds/{h['id']}/confirm", headers=user["headers"] | {"Idempotency-Key": key})).json()


async def test_dashboard_numbers(client, world, users):
    [admin] = users(1, role="admin")
    [u] = users(1)
    s = world["seats"]
    await book(client, u, world["show_id"], [s["A1"], s["A2"]], "k1")        # 2 x 200
    b2 = await book(client, u, world["show_id"], [s["C1"]], "k2")            # 1 x 300
    await client.post(f"/api/bookings/{b2['id']}/cancel", headers=u["headers"])

    d = (await client.get("/api/admin/dashboard", headers=admin["headers"])).json()
    assert d["summary"]["bookings"] == 1 and d["summary"]["cancellations"] == 1
    assert d["summary"]["revenue_paise"] == 40000
    assert float(d["summary"]["cancel_rate_pct"]) == 50.0
    [show] = d["shows"]
    assert show["seats_sold"] == 2 and show["seats_total"] == 18 and show["revenue_rank"] == 1
    assert d["daily"][-1]["running_total_paise"] == 40000


async def test_heatmap_counts_confirmed_bookings_only(client, world, users):
    [admin] = users(1, role="admin")
    [u] = users(1)
    s = world["seats"]
    await book(client, u, world["show_id"], [s["B3"]], "k1")
    heat = (await client.get(f"/api/admin/venues/{world['venue_id']}/heatmap", headers=admin["headers"])).json()
    counts = {f'{x["row_label"]}{x["seat_number"]}': x["times_booked"] for x in heat}
    assert counts["B3"] == 1 and counts["B4"] == 0 and len(counts) == 18


async def test_admin_creates_show_with_full_inventory(client, world, users):
    [admin] = users(1, role="admin")
    r = await client.post("/api/admin/shows", headers=admin["headers"], json={
        "venue_id": world["venue_id"], "title": "Late Show",
        "starts_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "regular_price_paise": 15000, "premium_price_paise": 25000})
    assert r.status_code == 201
    detail = (await client.get(f"/api/shows/{r.json()['id']}")).json()
    assert len(detail["seats"]) == 18 and all(x["status"] == "available" for x in detail["seats"])
