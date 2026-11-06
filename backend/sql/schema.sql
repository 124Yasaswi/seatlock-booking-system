-- SeatLock database schema (PostgreSQL 13+)
--
-- The one rule everything is built around: a seat of a show can be in exactly
-- one state at a time, and the row in show_seats is the single place that
-- state lives. Every change to it happens inside a transaction that first
-- locks the row (SELECT ... FOR UPDATE), so two requests can never both win.

CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE venues (
    id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL
);

-- Physical seats of a venue. row_index 0 is the row closest to the screen.
CREATE TABLE seats (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id    BIGINT NOT NULL REFERENCES venues (id) ON DELETE CASCADE,
    row_label   TEXT NOT NULL,
    row_index   INT  NOT NULL CHECK (row_index >= 0),
    seat_number INT  NOT NULL CHECK (seat_number >= 1),
    category    TEXT NOT NULL CHECK (category IN ('regular', 'premium')),
    UNIQUE (venue_id, row_index, seat_number)
);

CREATE TABLE shows (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id            BIGINT NOT NULL REFERENCES venues (id),
    title               TEXT NOT NULL,
    starts_at           TIMESTAMPTZ NOT NULL,
    regular_price_paise INT NOT NULL CHECK (regular_price_paise > 0),
    premium_price_paise INT NOT NULL CHECK (premium_price_paise > 0)
);
CREATE INDEX shows_starts_at_idx ON shows (starts_at);

-- A hold reserves seats for a few minutes while the user pays.
CREATE TABLE holds (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    BIGINT NOT NULL REFERENCES users (id),
    show_id    BIGINT NOT NULL REFERENCES shows (id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'active'
               CHECK (status IN ('active', 'converted', 'expired', 'released')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The expiry sweeper only ever looks at active holds: a partial index keeps it tiny.
CREATE INDEX holds_active_expiry_idx ON holds (expires_at) WHERE status = 'active';
CREATE INDEX holds_user_show_idx ON holds (user_id, show_id) WHERE status = 'active';

CREATE TABLE bookings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users (id),
    show_id         BIGINT NOT NULL REFERENCES shows (id) ON DELETE CASCADE,
    hold_id         UUID NOT NULL UNIQUE REFERENCES holds (id),   -- one hold -> at most one booking
    idempotency_key TEXT NOT NULL,
    amount_paise    INT NOT NULL CHECK (amount_paise > 0),
    status          TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_at    TIMESTAMPTZ,
    UNIQUE (user_id, idempotency_key)  -- the same "Pay" click can never create two bookings
);
CREATE INDEX bookings_user_idx ON bookings (user_id, created_at DESC);
CREATE INDEX bookings_show_idx ON bookings (show_id) WHERE status = 'confirmed';

-- Seats that belong to a booking (kept after cancellation, for history and analytics).
CREATE TABLE booking_seats (
    booking_id  BIGINT NOT NULL REFERENCES bookings (id) ON DELETE CASCADE,
    seat_id     BIGINT NOT NULL REFERENCES seats (id),
    price_paise INT NOT NULL,
    PRIMARY KEY (booking_id, seat_id)
);
CREATE INDEX booking_seats_seat_idx ON booking_seats (seat_id);

-- Live inventory: one row per seat per show. This is the row that gets locked.
CREATE TABLE show_seats (
    show_id    BIGINT NOT NULL REFERENCES shows (id) ON DELETE CASCADE,
    seat_id    BIGINT NOT NULL REFERENCES seats (id),
    status     TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'held', 'booked')),
    hold_id    UUID REFERENCES holds (id),
    booking_id BIGINT REFERENCES bookings (id),
    PRIMARY KEY (show_id, seat_id),
    -- the database itself refuses inconsistent rows
    CHECK ((status = 'held')   = (hold_id IS NOT NULL)),
    CHECK ((status = 'booked') = (booking_id IS NOT NULL))
);
CREATE INDEX show_seats_hold_idx ON show_seats (hold_id) WHERE hold_id IS NOT NULL;
CREATE INDEX show_seats_booking_idx ON show_seats (booking_id) WHERE booking_id IS NOT NULL;

-- First-come-first-served queue for sold-out shows.
CREATE TABLE waitlist (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users (id),
    show_id      BIGINT NOT NULL REFERENCES shows (id) ON DELETE CASCADE,
    seats_wanted INT NOT NULL CHECK (seats_wanted BETWEEN 1 AND 10),
    status       TEXT NOT NULL DEFAULT 'waiting'
                 CHECK (status IN ('waiting', 'offered', 'fulfilled', 'expired', 'cancelled')),
    hold_id      UUID REFERENCES holds (id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- a user can be in the queue for a show only once at a time
CREATE UNIQUE INDEX waitlist_one_active_per_user ON waitlist (user_id, show_id)
    WHERE status IN ('waiting', 'offered');
CREATE INDEX waitlist_queue_idx ON waitlist (show_id, created_at, id) WHERE status = 'waiting';
