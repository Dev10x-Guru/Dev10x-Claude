from __future__ import annotations

# ADR-0035 D4. MIGRATIONS[N] moves the store from user_version N to
# N + 1. Append only; never edit a migration that has shipped. Each
# migration is a tuple of single statements so it can run inside the
# caller's BEGIN IMMEDIATE transaction (executescript would commit it).
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            space TEXT NOT NULL,
            resource_name TEXT NOT NULL,
            sender TEXT NOT NULL,
            event_time TEXT NOT NULL,
            received_at TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('pubsub', 'poll', 'backfill')),
            via_lookback INTEGER NOT NULL DEFAULT 0,
            payload TEXT NOT NULL
        )
        """,
        "CREATE INDEX events_space_time ON events (space, event_time, resource_name)",
        """
        CREATE TABLE commands (
            id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events (id),
            actor TEXT NOT NULL,
            verb TEXT NOT NULL,
            authorized INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE work_items (
            id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events (id),
            kind TEXT NOT NULL CHECK (kind IN ('reply', 'privileged')),
            status TEXT NOT NULL CHECK (
                status IN ('queued', 'awaiting_approval', 'claimed', 'done', 'rejected')
            ),
            claimed_by TEXT,
            claimed_until TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            result TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (event_id, kind)
        )
        """,
        "CREATE INDEX work_items_claimable ON work_items (status, claimed_until, id)",
        """
        CREATE TABLE cursors (
            space TEXT PRIMARY KEY,
            last_event_time TEXT NOT NULL,
            last_resource_name TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE reaction_snapshot (
            reaction_name TEXT PRIMARY KEY,
            message_name TEXT NOT NULL,
            emoji TEXT NOT NULL,
            user TEXT NOT NULL,
            seen_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE gaps (
            id INTEGER PRIMARY KEY,
            space TEXT NOT NULL,
            from_time TEXT NOT NULL,
            to_time TEXT NOT NULL,
            reason TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """,
    ),
    (
        # GH-1839: one verdict per event, so a replay returns the first
        # verdict instead of authorizing the event a second time.
        "CREATE UNIQUE INDEX commands_one_per_event ON commands (event_id)",
        "ALTER TABLE commands ADD COLUMN outcome TEXT",
        "ALTER TABLE commands ADD COLUMN work_item_id INTEGER REFERENCES work_items (id)",
        """
        CREATE TABLE approvals (
            work_item_id INTEGER PRIMARY KEY REFERENCES work_items (id),
            dm_message TEXT UNIQUE,
            requested_at TEXT NOT NULL,
            approved_by_event INTEGER REFERENCES events (id),
            approved_at TEXT
        )
        """,
    ),
    (
        # GH-1840: the Workspace Events subscription the Pub/Sub source
        # renews, so a restart renews it instead of creating a second one.
        """
        CREATE TABLE subscriptions (
            target TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            expire_time TEXT NOT NULL,
            renewed_at TEXT NOT NULL
        )
        """,
    ),
)

SCHEMA_VERSION = len(MIGRATIONS)
