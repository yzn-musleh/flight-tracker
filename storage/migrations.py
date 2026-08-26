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
