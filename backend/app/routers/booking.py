from uuid import UUID

from fastapi import APIRouter, Depends, Header, WebSocket, WebSocketDisconnect

from app.db import get_conn
from app.realtime import hub
from app.schemas import BestHoldIn, HoldIn, WaitlistIn
from app.security import current_user
from app.services import booking as svc

router = APIRouter(prefix="/api", tags=["booking"])


@router.get("/shows")
async def list_shows(conn=Depends(get_conn)):
    cur = await conn.execute("""
        SELECT sh.id, sh.title, sh.starts_at, sh.regular_price_paise, sh.premium_price_paise,
               v.name AS venue, v.city,
               COUNT(*) AS seats_total,
               COUNT(*) FILTER (WHERE ss.status = 'available'
                                   OR (ss.status = 'held' AND h.expires_at <= now())) AS seats_free
        FROM shows sh
        JOIN venues v ON v.id = sh.venue_id
        JOIN show_seats ss ON ss.show_id = sh.id
        LEFT JOIN holds h ON h.id = ss.hold_id
        WHERE sh.starts_at > now()
        GROUP BY sh.id, v.id
        ORDER BY sh.starts_at""")
    return await cur.fetchall()


@router.get("/shows/{show_id}")
async def show_detail(show_id: int, conn=Depends(get_conn)):
    cur = await conn.execute("""
        SELECT sh.*, v.name AS venue, v.city FROM shows sh JOIN venues v ON v.id = sh.venue_id WHERE sh.id = %s""",
                             (show_id,))
    show = await cur.fetchone()
    if show is None:
        raise svc.BookingError(404, "show_not_found", "Show not found")
    cur = await conn.execute("""
        SELECT s.id, s.row_label, s.row_index, s.seat_number, s.category,
               CASE WHEN ss.status = 'held' AND h.expires_at <= now() THEN 'available' ELSE ss.status END AS status,
               CASE WHEN ss.status = 'held' AND h.expires_at > now() THEN ss.hold_id END AS hold_id
        FROM show_seats ss JOIN seats s ON s.id = ss.seat_id LEFT JOIN holds h ON h.id = ss.hold_id
        WHERE ss.show_id = %s
        ORDER BY s.row_index, s.seat_number""", (show_id,))
    show["seats"] = await cur.fetchall()
    return show


@router.post("/shows/{show_id}/holds", status_code=201)
async def create_hold(show_id: int, body: HoldIn, user=Depends(current_user), conn=Depends(get_conn)):
    hold, changes = await svc.hold_seats(conn, user["id"], show_id, body.seat_ids)
    await hub.publish(changes)
    return hold


@router.post("/shows/{show_id}/holds/best", status_code=201)
async def create_best_hold(show_id: int, body: BestHoldIn, user=Depends(current_user), conn=Depends(get_conn)):
    hold, changes = await svc.hold_best(conn, user["id"], show_id, body.count)
    await hub.publish(changes)
    return hold


@router.get("/holds/me")
async def my_holds(user=Depends(current_user), conn=Depends(get_conn)):
    cur = await conn.execute("""
        SELECT h.id, h.show_id, h.expires_at, sh.title, sh.starts_at,
               (SELECT w.id FROM waitlist w WHERE w.hold_id = h.id) AS waitlist_id,
               array_agg(s.row_label || s.seat_number ORDER BY s.row_index, s.seat_number) AS seats
        FROM holds h
        JOIN shows sh ON sh.id = h.show_id
        JOIN show_seats ss ON ss.hold_id = h.id
        JOIN seats s ON s.id = ss.seat_id
        WHERE h.user_id = %s AND h.status = 'active' AND h.expires_at > now()
        GROUP BY h.id, sh.id ORDER BY h.expires_at""", (user["id"],))
    return await cur.fetchall()


@router.delete("/holds/{hold_id}", status_code=204)
async def delete_hold(hold_id: UUID, user=Depends(current_user), conn=Depends(get_conn)):
    await hub.publish(await svc.release_hold(conn, user["id"], hold_id))


@router.post("/holds/{hold_id}/confirm")
async def confirm(hold_id: UUID, idempotency_key: str = Header(default=""),
                  user=Depends(current_user), conn=Depends(get_conn)):
    booking, changes = await svc.confirm_hold(conn, user["id"], hold_id, idempotency_key)
    await hub.publish(changes)
    return booking


@router.get("/bookings/me")
async def my_bookings(user=Depends(current_user), conn=Depends(get_conn)):
    cur = await conn.execute("SELECT id FROM bookings WHERE user_id = %s ORDER BY created_at DESC", (user["id"],))
    return [await svc._booking_out(conn, r["id"]) for r in await cur.fetchall()]


@router.post("/bookings/{booking_id}/cancel")
async def cancel(booking_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    booking, changes = await svc.cancel_booking(conn, user, booking_id)
    await hub.publish(changes)
    return booking


@router.post("/shows/{show_id}/waitlist", status_code=201)
async def join_waitlist(show_id: int, body: WaitlistIn, user=Depends(current_user), conn=Depends(get_conn)):
    entry, changes = await svc.join_waitlist(conn, user["id"], show_id, body.seats_wanted)
    await hub.publish(changes)
    return entry


@router.get("/waitlist/me")
async def my_waitlist(user=Depends(current_user), conn=Depends(get_conn)):
    cur = await conn.execute("""
        SELECT w.id, w.show_id, w.seats_wanted, w.status, w.hold_id, w.created_at, sh.title, sh.starts_at,
               (SELECT COUNT(*) FROM waitlist w2 WHERE w2.show_id = w.show_id AND w2.status = 'waiting'
                  AND (w2.created_at, w2.id) <= (w.created_at, w.id)) AS position
        FROM waitlist w JOIN shows sh ON sh.id = w.show_id
        WHERE w.user_id = %s AND w.status IN ('waiting', 'offered')
        ORDER BY w.created_at""", (user["id"],))
    return await cur.fetchall()


@router.delete("/waitlist/{entry_id}", status_code=204)
async def leave_waitlist(entry_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    await hub.publish(await svc.leave_waitlist(conn, user["id"], entry_id))


@router.websocket("/ws/shows/{show_id}")
async def seat_updates(ws: WebSocket, show_id: int):
    await hub.join(show_id, ws)
    try:
        while True:
            await ws.receive_text()  # we only push; reading keeps the connection open
    except WebSocketDisconnect:
        hub.leave(show_id, ws)
