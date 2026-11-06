"""Holds, bookings, cancellations, expiry and the waitlist.

Locking rules (they are what makes double booking impossible):

1. A seat's state only changes while its show_seats row is locked with
   SELECT ... FOR UPDATE inside a transaction. A second transaction that
   wants the same row waits; when it continues it sees the new state and
   gives up with "seat taken".
2. Rows are always locked in seat_id order, so two transactions that want
   overlapping seats can never deadlock (both queue up in the same order).
3. When a transaction needs a hold row and seat rows, it locks the hold
   first, then the seats.
4. A held seat whose hold has expired counts as free straight away, even
   before the background sweeper has cleaned it up.

Every function returns the list of seat changes it made, so the caller can
push them to browsers after the transaction has committed.
"""
from datetime import timedelta

from psycopg import errors

from app.config import settings
from app.services.seating import best_block

HOLD_TTL = timedelta(minutes=settings.hold_minutes)


class BookingError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


async def _one(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchone()


async def _all(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchall()


def _price(show: dict, category: str) -> int:
    return show["premium_price_paise"] if category == "premium" else show["regular_price_paise"]


async def _open_show(conn, show_id: int) -> dict:
    show = await _one(conn, "SELECT *, now() AS now FROM shows WHERE id = %s", (show_id,))
    if show is None:
        raise BookingError(404, "show_not_found", "Show not found")
    if show["starts_at"] <= show["now"]:
        raise BookingError(409, "show_started", "This show has already started")
    return show


async def _hold_locked(conn, user_id: int, show: dict, seat_ids: list[int]) -> tuple[dict, list[dict]]:
    """Core of every hold. Must run inside a transaction."""
    show_id, now = show["id"], show["now"]
    seat_ids = sorted(set(seat_ids))
    if not 1 <= len(seat_ids) <= settings.max_seats_per_booking:
        raise BookingError(422, "bad_seat_count", f"Pick 1 to {settings.max_seats_per_booking} seats")

    # The user's previous hold for this show is replaced by the new one (picking different seats).
    old = [r["id"] for r in await _all(
        conn, "SELECT id FROM holds WHERE user_id = %s AND show_id = %s AND status = 'active' FOR UPDATE",
        (user_id, show_id))]

    rows = await _all(conn, """
        SELECT ss.seat_id, ss.status, ss.hold_id, s.category, s.row_label, s.seat_number
        FROM show_seats ss
        JOIN seats s ON s.id = ss.seat_id
        WHERE ss.show_id = %s AND (ss.seat_id = ANY(%s) OR ss.hold_id = ANY(%s))
        ORDER BY ss.seat_id
        FOR UPDATE OF ss
    """, (show_id, seat_ids, old))
    wanted = {r["seat_id"]: r for r in rows if r["seat_id"] in seat_ids}
    if len(wanted) != len(seat_ids):
        raise BookingError(404, "seat_not_found", "Some seats do not exist in this show")

    # Read hold expiry times only *after* the seat rows are locked, in a separate
    # statement. Joining holds into the locking query is a trap: when this
    # transaction had to wait for the lock, PostgreSQL re-reads the locked seat
    # row but not the joined hold row, so a hold created by the winner looks
    # missing. (Found by the 200-users test.)
    hold_ids = list({r["hold_id"] for r in wanted.values() if r["hold_id"]})
    expiry = {h["id"]: h["expires_at"] for h in await _all(
        conn, "SELECT id, expires_at FROM holds WHERE id = ANY(%s)", (hold_ids,))}

    def free(r):
        return r["status"] == "available" or (
            r["status"] == "held" and (r["hold_id"] in old or expiry[r["hold_id"]] <= now))

    taken = [sid for sid, r in wanted.items() if not free(r)]
    if taken:
        raise BookingError(409, "seats_taken", "Some of these seats were just taken", seat_ids=taken)

    changes = []
    if old:
        await conn.execute("UPDATE holds SET status = 'released' WHERE id = ANY(%s)", (old,))
        await conn.execute("UPDATE waitlist SET status = 'cancelled' WHERE hold_id = ANY(%s) AND status = 'offered'", (old,))
        freed = await _all(conn, """
            UPDATE show_seats SET status = 'available', hold_id = NULL
            WHERE show_id = %s AND hold_id = ANY(%s) AND NOT (seat_id = ANY(%s))
            RETURNING seat_id
        """, (show_id, old, seat_ids))
        changes += [{"show_id": show_id, "seat_id": r["seat_id"], "status": "available"} for r in freed]

    hold = await _one(conn, """
        INSERT INTO holds (user_id, show_id, expires_at) VALUES (%s, %s, %s)
        RETURNING id, show_id, status, expires_at, created_at
    """, (user_id, show_id, now + HOLD_TTL))
    await conn.execute("UPDATE show_seats SET status = 'held', hold_id = %s WHERE show_id = %s AND seat_id = ANY(%s)",
                       (hold["id"], show_id, seat_ids))
    changes += [{"show_id": show_id, "seat_id": sid, "status": "held"} for sid in seat_ids]

    hold["seats"] = [{"seat_id": r["seat_id"], "label": f'{r["row_label"]}{r["seat_number"]}',
                      "category": r["category"], "price_paise": _price(show, r["category"])}
                     for r in wanted.values()]
    hold["amount_paise"] = sum(s["price_paise"] for s in hold["seats"])
    return hold, changes


async def hold_seats(conn, user_id: int, show_id: int, seat_ids: list[int]):
    async with conn.transaction():
        show = await _open_show(conn, show_id)
        return await _hold_locked(conn, user_id, show, seat_ids)


async def hold_best(conn, user_id: int, show_id: int, count: int, attempts: int = 3):
    """Pick the best adjacent block and hold it. If someone grabs one of those
    seats in the tiny gap between choosing and locking, choose again."""
    for _ in range(attempts):
        seat_ids = await best_block(conn, show_id, count)
        if seat_ids is None:
            raise BookingError(409, "no_block", f"No {count} seats together are free. Join the waitlist?")
        try:
            return await hold_seats(conn, user_id, show_id, seat_ids)
        except BookingError as e:
            if e.code != "seats_taken":
                raise
    raise BookingError(409, "busy", "Seats are selling fast, please try again")


async def release_hold(conn, user_id: int, hold_id):
    async with conn.transaction():
        hold = await _one(conn, "SELECT * FROM holds WHERE id = %s AND user_id = %s FOR UPDATE", (hold_id, user_id))
        if hold is None:
            raise BookingError(404, "hold_not_found", "Hold not found")
        if hold["status"] != "active":
            raise BookingError(409, "hold_not_active", f"Hold is already {hold['status']}")
        await conn.execute("UPDATE holds SET status = 'released' WHERE id = %s", (hold_id,))
        await conn.execute("UPDATE waitlist SET status = 'cancelled' WHERE hold_id = %s AND status = 'offered'", (hold_id,))
        freed = await _all(conn, "UPDATE show_seats SET status = 'available', hold_id = NULL WHERE hold_id = %s "
                                 "RETURNING show_id, seat_id", (hold_id,))
        changes = [{"show_id": r["show_id"], "seat_id": r["seat_id"], "status": "available"} for r in freed]
        changes += await process_waitlist(conn, hold["show_id"])
        return changes


async def _booking_out(conn, booking_id: int) -> dict:
    b = await _one(conn, """
        SELECT b.id, b.show_id, b.hold_id, b.amount_paise, b.status, b.created_at, b.cancelled_at,
               sh.title, sh.starts_at, v.name AS venue
        FROM bookings b JOIN shows sh ON sh.id = b.show_id JOIN venues v ON v.id = sh.venue_id
        WHERE b.id = %s""", (booking_id,))
    b["seats"] = [f'{r["row_label"]}{r["seat_number"]}' for r in await _all(conn, """
        SELECT s.row_label, s.seat_number FROM booking_seats bs JOIN seats s ON s.id = bs.seat_id
        WHERE bs.booking_id = %s ORDER BY s.row_index, s.seat_number""", (booking_id,))]
    return b


async def confirm_hold(conn, user_id: int, hold_id, idempotency_key: str):
    """Pay for a hold and turn it into a booking. Safe to call twice: the same
    Idempotency-Key (or the same hold) always returns the same booking."""
    if not idempotency_key or len(idempotency_key) > 100:
        raise BookingError(400, "idempotency_key_required", "Send an Idempotency-Key header (max 100 chars)")
    async with conn.transaction():
        existing = await _one(conn, "SELECT id, hold_id FROM bookings WHERE user_id = %s AND idempotency_key = %s",
                              (user_id, idempotency_key))
        if existing:
            if str(existing["hold_id"]) != str(hold_id):
                raise BookingError(409, "idempotency_key_reused", "This Idempotency-Key was used for another booking")
            return await _booking_out(conn, existing["id"]) | {"replayed": True}, []

        hold = await _one(conn, "SELECT *, now() AS now FROM holds WHERE id = %s AND user_id = %s FOR UPDATE",
                          (hold_id, user_id))
        if hold is None:
            raise BookingError(404, "hold_not_found", "Hold not found")
        if hold["status"] == "converted":  # a parallel click with another key won the race
            b = await _one(conn, "SELECT id FROM bookings WHERE hold_id = %s", (hold_id,))
            return await _booking_out(conn, b["id"]) | {"replayed": True}, []
        if hold["status"] != "active" or hold["expires_at"] <= hold["now"]:
            raise BookingError(410, "hold_expired", "Your hold has expired, please pick seats again")

        show = await _one(conn, "SELECT * FROM shows WHERE id = %s", (hold["show_id"],))
        seats = await _all(conn, """
            SELECT ss.seat_id, s.category FROM show_seats ss JOIN seats s ON s.id = ss.seat_id
            WHERE ss.show_id = %s AND ss.hold_id = %s ORDER BY ss.seat_id FOR UPDATE OF ss
        """, (hold["show_id"], hold_id))
        if not seats:
            raise BookingError(410, "hold_expired", "Your hold has expired, please pick seats again")

        # Payment is simulated: in a real system the payment gateway call goes here,
        # and the same idempotency key is passed on to the gateway.
        amount = sum(_price(show, s["category"]) for s in seats)
        try:
            booking = await _one(conn, """
                INSERT INTO bookings (user_id, show_id, hold_id, idempotency_key, amount_paise)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (user_id, hold["show_id"], hold_id, idempotency_key, amount))
        except errors.UniqueViolation:
            raise BookingError(409, "idempotency_key_reused", "This Idempotency-Key was used for another booking")

        await conn.execute("UPDATE show_seats SET status = 'booked', hold_id = NULL, booking_id = %s "
                           "WHERE show_id = %s AND hold_id = %s", (booking["id"], hold["show_id"], hold_id))
        async with conn.cursor() as cur:
            await cur.executemany("INSERT INTO booking_seats (booking_id, seat_id, price_paise) VALUES (%s, %s, %s)",
                                  [(booking["id"], s["seat_id"], _price(show, s["category"])) for s in seats])
        await conn.execute("UPDATE holds SET status = 'converted' WHERE id = %s", (hold_id,))
        await conn.execute("UPDATE waitlist SET status = 'fulfilled' WHERE hold_id = %s", (hold_id,))

        changes = [{"show_id": hold["show_id"], "seat_id": s["seat_id"], "status": "booked"} for s in seats]
        return await _booking_out(conn, booking["id"]) | {"replayed": False}, changes


async def cancel_booking(conn, user: dict, booking_id: int):
    async with conn.transaction():
        b = await _one(conn, """
            SELECT b.*, sh.starts_at, now() AS now FROM bookings b JOIN shows sh ON sh.id = b.show_id
            WHERE b.id = %s FOR UPDATE OF b""", (booking_id,))
        if b is None or (b["user_id"] != user["id"] and user["role"] != "admin"):
            raise BookingError(404, "booking_not_found", "Booking not found")
        if b["status"] != "confirmed":
            raise BookingError(409, "already_cancelled", "Booking is already cancelled")
        if b["starts_at"] <= b["now"]:
            raise BookingError(409, "show_started", "Cannot cancel after the show has started")
        await conn.execute("UPDATE bookings SET status = 'cancelled', cancelled_at = now() WHERE id = %s", (booking_id,))
        freed = await _all(conn, "UPDATE show_seats SET status = 'available', booking_id = NULL "
                                 "WHERE booking_id = %s RETURNING show_id, seat_id", (booking_id,))
        changes = [{"show_id": r["show_id"], "seat_id": r["seat_id"], "status": "available"} for r in freed]
        changes += await process_waitlist(conn, b["show_id"])
        return await _booking_out(conn, booking_id), changes


async def join_waitlist(conn, user_id: int, show_id: int, seats_wanted: int):
    async with conn.transaction():
        await _open_show(conn, show_id)
        try:
            entry = await _one(conn, """
                INSERT INTO waitlist (user_id, show_id, seats_wanted) VALUES (%s, %s, %s)
                RETURNING id, show_id, seats_wanted, status, created_at""", (user_id, show_id, seats_wanted))
        except errors.UniqueViolation:
            raise BookingError(409, "already_waiting", "You are already on the waitlist for this show")
        # Seats may already be free (e.g. someone cancelled a moment ago)
        changes = await process_waitlist(conn, show_id)
        return entry, changes


async def leave_waitlist(conn, user_id: int, entry_id: int):
    async with conn.transaction():
        entry = await _one(conn, "SELECT * FROM waitlist WHERE id = %s AND user_id = %s FOR UPDATE", (entry_id, user_id))
        if entry is None or entry["status"] not in ("waiting", "offered"):
            raise BookingError(404, "waitlist_not_found", "Waitlist entry not found")
        await conn.execute("UPDATE waitlist SET status = 'cancelled' WHERE id = %s", (entry_id,))
    if entry["status"] == "offered":  # give the offered seats back to the queue
        try:
            return await release_hold(conn, user_id, entry["hold_id"])
        except BookingError:  # the offer had already expired or been used
            return []
    return []


async def process_waitlist(conn, show_id: int) -> list[dict]:
    """Offer free seats to the queue, strictly first come first served.
    Runs inside the caller's transaction. Each offer is a normal hold that
    the user confirms (pays for) from the "My bookings" page."""
    changes = []
    while True:
        entry = await _one(conn, """
            SELECT * FROM waitlist WHERE show_id = %s AND status = 'waiting'
            ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED""", (show_id,))
        if entry is None:
            break
        seat_ids = await best_block(conn, show_id, entry["seats_wanted"], allow_split=True)
        if seat_ids is None:
            break  # the person at the front needs more seats than are free: keep the order fair
        show = await _one(conn, "SELECT *, now() AS now FROM shows WHERE id = %s", (show_id,))
        try:
            async with conn.transaction():  # savepoint: a lost race must not undo the caller's work
                hold, ch = await _hold_locked(conn, entry["user_id"], show, seat_ids)
        except BookingError:
            break
        await conn.execute("UPDATE waitlist SET status = 'offered', hold_id = %s WHERE id = %s", (hold["id"], entry["id"]))
        changes += ch
    return changes


async def sweep_expired(conn, limit: int = 200) -> list[dict]:
    """Release seats of expired holds, then let the waitlist have them."""
    async with conn.transaction():
        expired = await _all(conn, """
            SELECT id, show_id FROM holds WHERE status = 'active' AND expires_at <= now()
            ORDER BY expires_at LIMIT %s FOR UPDATE SKIP LOCKED""", (limit,))
        if not expired:
            return []
        ids = [h["id"] for h in expired]
        await conn.execute("UPDATE holds SET status = 'expired' WHERE id = ANY(%s)", (ids,))
        await conn.execute("UPDATE waitlist SET status = 'expired' WHERE hold_id = ANY(%s) AND status = 'offered'", (ids,))
        freed = await _all(conn, "UPDATE show_seats SET status = 'available', hold_id = NULL "
                                 "WHERE hold_id = ANY(%s) RETURNING show_id, seat_id", (ids,))
        changes = [{"show_id": r["show_id"], "seat_id": r["seat_id"], "status": "available"} for r in freed]
        for show_id in sorted({h["show_id"] for h in expired}):
            changes += await process_waitlist(conn, show_id)
        return changes
