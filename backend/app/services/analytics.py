"""Admin reports. Each one is a single SQL query; the interesting SQL is here on purpose."""

SUMMARY_SQL = """
    SELECT COUNT(*) FILTER (WHERE status = 'confirmed')                          AS bookings,
           COUNT(*) FILTER (WHERE status = 'cancelled')                          AS cancellations,
           COALESCE(SUM(amount_paise) FILTER (WHERE status = 'confirmed'), 0)    AS revenue_paise,
           ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'cancelled') / NULLIF(COUNT(*), 0), 1) AS cancel_rate_pct
    FROM bookings
"""

# Occupancy and revenue per show, ranked with a window function.
SHOWS_SQL = """
    WITH sold AS (
        SELECT b.show_id, COUNT(bs.seat_id) AS seats_sold, SUM(bs.price_paise) AS revenue_paise
        FROM bookings b JOIN booking_seats bs ON bs.booking_id = b.id
        WHERE b.status = 'confirmed'
        GROUP BY b.show_id
    ), capacity AS (
        SELECT show_id, COUNT(*) AS seats_total FROM show_seats GROUP BY show_id
    )
    SELECT sh.id, sh.title, sh.starts_at,
           c.seats_total,
           COALESCE(s.seats_sold, 0)                                     AS seats_sold,
           ROUND(100.0 * COALESCE(s.seats_sold, 0) / c.seats_total, 1)   AS occupancy_pct,
           COALESCE(s.revenue_paise, 0)                                  AS revenue_paise,
           RANK() OVER (ORDER BY COALESCE(s.revenue_paise, 0) DESC)      AS revenue_rank
    FROM shows sh
    JOIN capacity c ON c.show_id = sh.id
    LEFT JOIN sold s ON s.show_id = sh.id
    ORDER BY sh.starts_at
"""

# When do people book? Bookings per hour of the day (Indian time).
HOURS_SQL = """
    SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata')::int AS hour, COUNT(*) AS bookings
    FROM bookings WHERE status = 'confirmed'
    GROUP BY 1 ORDER BY 1
"""

# Daily revenue with a running total (window function over a GROUP BY).
DAILY_SQL = """
    SELECT day, revenue_paise, SUM(revenue_paise) OVER (ORDER BY day) AS running_total_paise
    FROM (
        SELECT (created_at AT TIME ZONE 'Asia/Kolkata')::date AS day, SUM(amount_paise) AS revenue_paise
        FROM bookings WHERE status = 'confirmed' GROUP BY 1
    ) d
    ORDER BY day
"""

# Which seats sell most often across all shows of a venue? Drives the heatmap.
HEATMAP_SQL = """
    SELECT s.id AS seat_id, s.row_label, s.row_index, s.seat_number, s.category,
           COUNT(b.id) AS times_booked
    FROM seats s
    LEFT JOIN booking_seats bs ON bs.seat_id = s.id
    LEFT JOIN bookings b ON b.id = bs.booking_id AND b.status = 'confirmed'
    WHERE s.venue_id = %s
    GROUP BY s.id
    ORDER BY s.row_index, s.seat_number
"""


async def _all(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchall()


async def dashboard(conn) -> dict:
    return {
        "summary": (await _all(conn, SUMMARY_SQL))[0],
        "shows": await _all(conn, SHOWS_SQL),
        "by_hour": await _all(conn, HOURS_SQL),
        "daily": await _all(conn, DAILY_SQL),
    }


async def seat_heatmap(conn, venue_id: int) -> list[dict]:
    return await _all(conn, HEATMAP_SQL, (venue_id,))
