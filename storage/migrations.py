"""Versioned, idempotent SQLite schema migrations.

Each entry is (version, sql). apply() runs any migration whose version is
greater than the database's current version, in order, inside the caller's
transaction. Safe to call on every connection -- the common case (already at
the latest version) is a single cheap SELECT.
"""

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            flight_iata TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            dep_country TEXT NOT NULL DEFAULT 'Unknown',
            arr_country TEXT NOT NULL DEFAULT 'Unknown',
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_subscriptions_flight_iata ON subscriptions (flight_iata);

        -- One row per (flight_iata, scheduled_date): polling bookkeeping plus
        -- the last-known "key fields" snapshot used for change detection.
        -- has_snapshot distinguishes "never checked yet" from "checked and
        -- every field happened to come back null".
        CREATE TABLE flights (
            flight_iata TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            last_checked TEXT,
            done INTEGER NOT NULL DEFAULT 0,
            dep_scheduled TEXT,
            arr_scheduled TEXT,
            has_snapshot INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            dep_delay INTEGER,
            arr_delay INTEGER,
            dep_gate TEXT,
            arr_gate TEXT,
            dep_estimated TEXT,
            arr_estimated TEXT,
            PRIMARY KEY (flight_iata, scheduled_date)
        );

        -- Audit trail of every detected field change, independent of whether
        -- an alert was actually sent for it. Not yet read by any code path in
        -- Phase 1 -- Phase 3's dedupe/debounce rewrite is the intended
        -- consumer. Writing it now costs nothing and avoids losing history
        -- between now and then.
        CREATE TABLE change_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_iata TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            detected_at TEXT NOT NULL
        );

        CREATE TABLE api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            http_status INTEGER,
            counted INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX idx_api_usage_timestamp ON api_usage (timestamp);

        -- The "warned this month" flag doesn't fit api_usage's one-row-per-
        -- request shape, so it gets its own tiny table keyed by month.
        CREATE TABLE usage_warnings (
            month TEXT PRIMARY KEY,
            warned INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE airports (
            iata TEXT PRIMARY KEY,
            country TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        -- Phase 2 bundles an offline airport dataset (static/airports.csv)
        -- and resolves country/timezone from it directly, at zero cost --
        -- no live lookup, so no cache table is needed any more.
        DROP TABLE airports;
        """,
    ),
    (
        3,
        """
        -- Phase 3: change_events becomes the durable dedupe/retry record for
        -- alerts, not just an audit trail. sent=0 means "recorded before the
        -- send was attempted, not yet confirmed delivered" -- a crash or
        -- restart between recording and sending leaves it 0, so the next
        -- poll retries it instead of silently losing or re-detecting it as
        -- a brand new change (see CLAUDE.md invariant #1).
        ALTER TABLE change_events ADD COLUMN sent INTEGER NOT NULL DEFAULT 0;

        CREATE INDEX idx_change_events_pending
            ON change_events (flight_iata, scheduled_date, sent);
        """,
    ),
    (
        4,
        """
        -- Phase 4: chat_id becomes the tenant boundary (CLAUDE.md invariant
        -- #5). Every subscription now belongs to the chat that created it;
        -- there is no more global "the chat". Default '' only matters for
        -- the ALTER itself (SQLite requires a constant default when adding a
        -- NOT NULL column to a possibly-non-empty table) -- nothing in this
        -- project has ever shipped with real subscription rows, so no
        -- backfill migration for existing data is needed.
        ALTER TABLE subscriptions ADD COLUMN chat_id TEXT NOT NULL DEFAULT '';

        CREATE INDEX idx_subscriptions_chat_id ON subscriptions (chat_id);

        -- Per-chat access approval state and settings. access_status is
        -- 'pending' | 'approved' | 'denied'; a chat_id in ALLOWED_CHAT_IDS
        -- (env var) is always treated as approved regardless of what's (or
        -- isn't) in this table -- see access.py.
        CREATE TABLE chats (
            chat_id TEXT PRIMARY KEY,
            access_status TEXT NOT NULL DEFAULT 'pending',
            timezone TEXT,
            requested_at TEXT NOT NULL,
            decided_at TEXT,
            decided_by TEXT
        );
        """,
    ),
    (
        5,
        """
        -- Phase 5: persisted next_poll_at replaces recomputing "is this due"
        -- from last_checked + the tier interval on every tick. It's fixed at
        -- the moment it's computed (using the tier as of that check), so a
        -- restart resumes from an explicit, stored fact rather than
        -- re-deriving a value that could drift depending on when a process
        -- happens to ask.
        ALTER TABLE flights ADD COLUMN next_poll_at TEXT;
        """,
    ),
]


def apply(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        current = 0
    else:
        current = row[0]

    pending = [(v, sql) for v, sql in MIGRATIONS if v > current]
    if not pending:
        return

    for version, sql in pending:
        conn.executescript(sql)
        conn.execute("UPDATE schema_version SET version = ?", (version,))
        current = version
