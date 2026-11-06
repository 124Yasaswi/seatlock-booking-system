"""Smart group seating: find the best block of N seats next to each other.

Step 1 (SQL, "gaps and islands"): free seats in a row whose numbers are
consecutive share the same value of  seat_number - ROW_NUMBER().
    seats 3,4,5,9,10 -> row_number 1,2,3,4,5 -> difference 2,2,2,5,5
    -> two islands: [3,4,5] and [9,10]
Only islands with at least N seats come back from the database.

Step 2 (Python): slide an N-wide window over each island and score it.
Lower score = better: close to the middle of the row, and close to the
"sweet spot" row about 60% of the way back from the screen.
"""

FREE_SEATS_SQL = """
    SELECT s.id, s.row_index, s.seat_number
    FROM show_seats ss
    JOIN seats s ON s.id = ss.seat_id
    LEFT JOIN holds h ON h.id = ss.hold_id
    WHERE ss.show_id = %(show_id)s
      AND (ss.status = 'available' OR (ss.status = 'held' AND h.expires_at <= now()))
"""

ISLANDS_SQL = f"""
    WITH free AS ({FREE_SEATS_SQL}),
    numbered AS (
        SELECT id, row_index, seat_number,
               seat_number - ROW_NUMBER() OVER (PARTITION BY row_index ORDER BY seat_number) AS island
        FROM free
    )
    SELECT row_index,
           array_agg(id ORDER BY seat_number)          AS seat_ids,
           array_agg(seat_number ORDER BY seat_number) AS numbers
    FROM numbered
    GROUP BY row_index, island
    HAVING COUNT(*) >= %(n)s
"""

LAYOUT_SQL = """
    SELECT COUNT(DISTINCT s.row_index) AS rows, MAX(s.seat_number) AS seats_per_row
    FROM shows sh JOIN seats s ON s.venue_id = sh.venue_id
    WHERE sh.id = %(show_id)s
"""


def _score(row_index: int, numbers: list[int], rows: int, seats_per_row: int) -> float:
    centre = (seats_per_row + 1) / 2
    sweet_row = round((rows - 1) * 0.6)
    window_centre = (numbers[0] + numbers[-1]) / 2
    return abs(window_centre - centre) + 1.5 * abs(row_index - sweet_row)


async def best_block(conn, show_id: int, n: int, allow_split: bool = False) -> list[int] | None:
    """Seat ids of the best N adjacent seats, or None if there is no such block.

    With allow_split=True (used by the waitlist), fall back to the N best
    individual seats when no adjacent block exists.
    """
    layout = await (await conn.execute(LAYOUT_SQL, {"show_id": show_id})).fetchone()
    rows, per_row = layout["rows"] or 0, layout["seats_per_row"] or 0

    best, best_score = None, float("inf")
    for isl in await (await conn.execute(ISLANDS_SQL, {"show_id": show_id, "n": n})).fetchall():
        ids, nums = isl["seat_ids"], isl["numbers"]
        for start in range(len(ids) - n + 1):
            score = _score(isl["row_index"], nums[start:start + n], rows, per_row)
            if score < best_score:
                best, best_score = ids[start:start + n], score
    if best or not allow_split:
        return best

    free = await (await conn.execute(FREE_SEATS_SQL, {"show_id": show_id})).fetchall()
    if len(free) < n:
        return None
    free.sort(key=lambda s: _score(s["row_index"], [s["seat_number"]], rows, per_row))
    return [s["id"] for s in free[:n]]
