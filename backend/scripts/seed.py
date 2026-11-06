"""Fill the database with demo venues, shows, users and past bookings.

Demo logins (local demo data only):
    admin@seatlock.test / Admin@1234   (admin dashboard)
    demo@seatlock.test  / Demo@1234    (normal user)

Usage:
    python -m scripts.init_db --reset && python -m scripts.seed
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.security import hash_password

IST = timezone(timedelta(hours=5, minutes=30))
VENUES = [
    # name, city, rows, seats per row, how many back rows are premium
    ("Galaxy Screen 1", "Hyderabad", 10, 14, 3),
    ("Orbit Audi 2", "Vijayawada", 8, 12, 2),
]
TITLES = ["The Last Monsoon", "Code of Silence", "Starfall", "Midnight Expressway", "Paper Kites", "River of Stars"]


def make_venue(cur, name, city, rows, per_row, premium_rows):
    venue_id = cur.execute("INSERT INTO venues (name, city) VALUES (%s, %s) RETURNING id", (name, city)).fetchone()["id"]
    cur.executemany(
        "INSERT INTO seats (venue_id, row_label, row_index, seat_number, category) VALUES (%s, %s, %s, %s, %s)",
        [(venue_id, chr(65 + r), r, n, "premium" if r >= rows - premium_rows else "regular")
         for r in range(rows) for n in range(1, per_row + 1)])
    return venue_id


def make_show(cur, venue_id, title, starts_at, regular, premium):
    show_id = cur.execute("""INSERT INTO shows (venue_id, title, starts_at, regular_price_paise, premium_price_paise)
                             VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                          (venue_id, title, starts_at, regular, premium)).fetchone()["id"]
    cur.execute("INSERT INTO show_seats (show_id, seat_id) SELECT %s, id FROM seats WHERE venue_id = %s", (show_id, venue_id))
    return show_id


def book(cur, user_id, show_id, seat_ids, created_at, cancelled=False):
    """Insert a finished booking directly (demo history), keeping every table consistent."""
    prices = {r["id"]: r["price"] for r in cur.execute("""
        SELECT s.id, CASE s.category WHEN 'premium' THEN sh.premium_price_paise ELSE sh.regular_price_paise END AS price
        FROM seats s JOIN shows sh ON sh.venue_id = s.venue_id WHERE sh.id = %s AND s.id = ANY(%s)""",
        (show_id, seat_ids)).fetchall()}
    hold_id = cur.execute("""INSERT INTO holds (user_id, show_id, status, expires_at, created_at)
                             VALUES (%s, %s, 'converted', %s, %s) RETURNING id""",
                          (user_id, show_id, created_at + timedelta(minutes=5), created_at)).fetchone()["id"]
    booking_id = cur.execute("""
        INSERT INTO bookings (user_id, show_id, hold_id, idempotency_key, amount_paise, status, created_at, cancelled_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (user_id, show_id, hold_id, str(uuid.uuid4()), sum(prices.values()),
         "cancelled" if cancelled else "confirmed", created_at,
         created_at + timedelta(hours=3) if cancelled else None)).fetchone()["id"]
    cur.executemany("INSERT INTO booking_seats (booking_id, seat_id, price_paise) VALUES (%s, %s, %s)",
                    [(booking_id, sid, prices[sid]) for sid in seat_ids])
    if not cancelled:
        cur.execute("UPDATE show_seats SET status = 'booked', booking_id = %s WHERE show_id = %s AND seat_id = ANY(%s)",
                    (booking_id, show_id, seat_ids))


def free_blocks(cur, show_id):
    """Free seats grouped per row, in seat order."""
    rows = {}
    for r in cur.execute("""SELECT s.id, s.row_index, s.seat_number FROM show_seats ss JOIN seats s ON s.id = ss.seat_id
                            WHERE ss.show_id = %s AND ss.status = 'available' ORDER BY s.row_index, s.seat_number""",
                         (show_id,)).fetchall():
        rows.setdefault(r["row_index"], []).append(r)
    return rows


def random_booking_time(rng, now):
    # people book more in the evening: weight hours 18-23 higher
    day = now - timedelta(days=rng.randint(0, 6))
    hour = rng.choices(range(24), weights=[1] * 9 + [2] * 9 + [6] * 6)[0]
    t = day.replace(hour=hour, minute=rng.randint(0, 59))
    if t > now - timedelta(minutes=10):  # that time is still to come today: use yesterday instead
        t -= timedelta(days=1)
    return t


def main(url: str = settings.database_url, seed: int = 11):
    rng = random.Random(seed)
    now = datetime.now(IST)
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        if cur.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]:
            raise SystemExit("Database is not empty. Run: python -m scripts.init_db --reset")

        cur.execute("INSERT INTO users (email, name, password_hash, role) VALUES (%s, %s, %s, 'admin')",
                    ("admin@seatlock.test", "Admin", hash_password("Admin@1234")))
        cur.execute("INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s)",
                    ("demo@seatlock.test", "Demo User", hash_password("Demo@1234")))
        filler_hash = hash_password("Filler@1234")
        cur.executemany("INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s)",
                        [(f"user{i}@seatlock.test", f"User {i}", filler_hash) for i in range(1, 41)])
        user_ids = [r["id"] for r in cur.execute("SELECT id FROM users WHERE email LIKE 'user%%'").fetchall()]

        venue_ids = [make_venue(cur, *v) for v in VENUES]
        shows = []
        for day in range(1, 4):
            for i, (hh, mm) in enumerate([(14, 0), (18, 30), (21, 45)]):
                venue = venue_ids[(day + i) % 2]
                starts = (now + timedelta(days=day)).replace(hour=hh, minute=mm, second=0, microsecond=0)
                evening = hh >= 18
                shows.append(make_show(cur, venue, TITLES[(day * 3 + i) % len(TITLES)], starts,
                                       22000 if evening else 18000, 32000 if evening else 26000))

        # Past bookings: mostly groups of 2-4 sitting together, some cancelled.
        for n, show_id in enumerate(shows):
            target = rng.uniform(0.25, 0.75)
            if n == 1:
                target = 0.985  # one almost sold-out show, to try the waitlist
            total = cur.execute("SELECT COUNT(*) AS n FROM show_seats WHERE show_id = %s", (show_id,)).fetchone()["n"]
            booked = 0
            while booked < target * total:
                size = rng.choice([1, 2, 2, 2, 3, 4, 4, 5])
                rows = [r for r in free_blocks(cur, show_id).values() if len(r) >= size]
                if not rows:
                    size, rows = 1, [r for r in free_blocks(cur, show_id).values() if r]
                    if not rows:
                        break
                row = rng.choice(rows)
                start = rng.randint(0, len(row) - size)
                seat_ids = [s["id"] for s in row[start:start + size]]
                cancelled = rng.random() < 0.08
                book(cur, rng.choice(user_ids), show_id, seat_ids, random_booking_time(rng, now), cancelled)
                if not cancelled:
                    booked += size
        conn.commit()
        print(f"seeded {len(venue_ids)} venues, {len(shows)} shows, "
              f"{cur.execute('SELECT COUNT(*) AS n FROM bookings').fetchone()['n']} bookings")


if __name__ == "__main__":
    main()
