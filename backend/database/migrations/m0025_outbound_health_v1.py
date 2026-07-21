"""Upgrade outbound probes to the production-grade health-check model."""

VERSION = 25
NAME = "outbound_health_v1"


def _columns(cursor, table: str, _use_pg: bool = True) -> set[str]:
    if _use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}
    else:
        rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}


def _data_type(cursor, table: str, column: str, _use_pg: bool = True) -> str | None:
    if _use_pg:
        row = cursor.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s",
            (table, column),
        ).fetchone()
        return str(row[0]).lower() if row else None
    else:
        rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
        for r in rows:
            if str(r[1]).lower() == column.lower():
                return str(r[2]).lower()
        return None


def _add_columns(cursor, table: str, definitions: dict[str, str], _use_pg: bool = True) -> None:
    columns = _columns(cursor, table, _use_pg)
    for name, definition in definitions.items():
        if name in columns:
            continue
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _seed_target(cursor, row: tuple, _use_pg: bool = True) -> None:
    placeholder = "%s" if _use_pg else "?"
    placeholders = ", ".join([placeholder] * len(row))
    cursor.execute(
        f"""
        INSERT INTO outbound_probe_targets (
            id, target_name, host, port, probe_type, is_active, created_at,
            group_name, url, expected_status_code, expected_keyword,
            timeout_ms, enabled, updated_at
        ) VALUES ({placeholders})
        """,
        row,
    )


def upgrade(cursor, _use_pg: bool) -> None:
    # Version 24 created these tables. Keep the migration safe for fresh
    # databases and for installations that already applied version 24.
    _add_columns(
        cursor,
        "outbound_probe_targets",
        {
            "group_name": "TEXT NOT NULL DEFAULT 'business'",
            "url": "TEXT DEFAULT ''",
            "expected_status_code": "INTEGER DEFAULT 200",
            "expected_keyword": "TEXT DEFAULT ''",
            "timeout_ms": "INTEGER NOT NULL DEFAULT 2000",
            "enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
            "updated_at": "TEXT DEFAULT ''",
        },
        _use_pg,
    )

    # Version 24 deployments may have created integer flags. Normalize them
    # before the boolean expressions below are evaluated.
    if _use_pg:
        if _data_type(cursor, "outbound_probe_targets", "is_active", _use_pg) != "boolean":
            cursor.execute(
                "ALTER TABLE outbound_probe_targets ALTER COLUMN is_active TYPE BOOLEAN "
                "USING (is_active <> 0)"
            )
        if _data_type(cursor, "outbound_probe_targets", "enabled", _use_pg) != "boolean":
            cursor.execute(
                "ALTER TABLE outbound_probe_targets ALTER COLUMN enabled TYPE BOOLEAN "
                "USING (enabled <> 0)"
            )
    _add_columns(
        cursor,
        "outbound_probe_samples",
        {
            "node_id": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'unknown'",
            "status_reason": "TEXT DEFAULT ''",
            "public_ip_changed": "BOOLEAN NOT NULL DEFAULT FALSE",
            "consecutive_failure_count": "INTEGER NOT NULL DEFAULT 0",
            "consecutive_recovery_count": "INTEGER NOT NULL DEFAULT 0",
        },
        _use_pg,
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS outbound_probe_nodes (
            id              TEXT PRIMARY KEY,
            node_name       TEXT NOT NULL UNIQUE,
            node_type       TEXT NOT NULL DEFAULT 'platform-server',
            source_ip       TEXT DEFAULT '',
            enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            last_seen_at    TEXT DEFAULT '',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS outbound_probe_runs (
            id                          TEXT PRIMARY KEY,
            node_id                     TEXT NOT NULL,
            started_at                  TEXT NOT NULL,
            finished_at                 TEXT NOT NULL,
            status                      TEXT NOT NULL,
            raw_status                  TEXT NOT NULL,
            status_reason               TEXT NOT NULL DEFAULT '',
            success_count               INTEGER NOT NULL DEFAULT 0,
            total_targets               INTEGER NOT NULL DEFAULT 0,
            availability_percent        REAL NOT NULL DEFAULT 0,
            average_latency_ms          REAL,
            public_ip                   TEXT DEFAULT '',
            public_ip_changed           BOOLEAN NOT NULL DEFAULT FALSE,
            consecutive_failure_count   INTEGER NOT NULL DEFAULT 0,
            consecutive_recovery_count  INTEGER NOT NULL DEFAULT 0,
            group_status_json           TEXT NOT NULL DEFAULT '{}',
            created_at                  TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS outbound_probe_results (
            id              TEXT PRIMARY KEY,
            run_id          TEXT NOT NULL,
            target_id       TEXT NOT NULL,
            target_name     TEXT NOT NULL,
            group_name      TEXT NOT NULL,
            probe_type      TEXT NOT NULL,
            sampled_at      TEXT NOT NULL,
            success         BOOLEAN NOT NULL DEFAULT FALSE,
            latency_ms      REAL,
            error_type      TEXT,
            error_message   TEXT,
            resolved_ip     TEXT,
            http_status     INTEGER,
            dns_answers_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS outbound_egress_ip_events (
            id              TEXT PRIMARY KEY,
            node_id         TEXT NOT NULL,
            observed_at     TEXT NOT NULL,
            previous_ip     TEXT DEFAULT '',
            confirmed_ip    TEXT DEFAULT '',
            source_a_ip     TEXT DEFAULT '',
            source_b_ip     TEXT DEFAULT '',
            consistent      BOOLEAN NOT NULL DEFAULT FALSE,
            error_message   TEXT DEFAULT ''
        )
        """
    )

    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_outbound_runs_node_time ON outbound_probe_runs(node_id, finished_at)",
        "CREATE INDEX IF NOT EXISTS ix_outbound_results_run ON outbound_probe_results(run_id)",
        "CREATE INDEX IF NOT EXISTS ix_outbound_results_target_time ON outbound_probe_results(target_id, sampled_at)",
        "CREATE INDEX IF NOT EXISTS ix_outbound_ip_events_node_time ON outbound_egress_ip_events(node_id, observed_at)",
        "CREATE INDEX IF NOT EXISTS ix_outbound_samples_time ON outbound_probe_samples(timestamp)",
    ):
        cursor.execute(index_sql)

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    q_placeholder = "%s" if _use_pg else "?"
    cursor.execute(f"SELECT id FROM outbound_probe_nodes WHERE node_name = {q_placeholder}", ("platform-server",))
    node = cursor.fetchone()
    node_id = str(node[0]) if node else "platform-server"
    if not node:
        cursor.execute(
            f"""
            INSERT INTO outbound_probe_nodes
                (id, node_name, node_type, source_ip, enabled, last_seen_at, created_at, updated_at)
            VALUES ({q_placeholder}, {q_placeholder}, {q_placeholder}, {q_placeholder}, TRUE, {q_placeholder}, {q_placeholder}, {q_placeholder})
            """,
            (node_id, "platform-server", "platform-server", "", now, now, now),
        )

    # Normalize the legacy rows created by m0024.
    cursor.execute(
        f"""
        UPDATE outbound_probe_targets
        SET probe_type = CASE LOWER(COALESCE(probe_type, 'tcp'))
                WHEN 'tcp' THEN 'TCP_CONNECT'
                WHEN 'http' THEN 'HTTP_GET'
                WHEN 'https' THEN 'HTTPS_GET'
                WHEN 'dns' THEN 'DNS_RESOLVE'
                ELSE UPPER(probe_type)
            END,
            group_name = CASE
                WHEN COALESCE(group_name, '') IN ('', 'business') AND port = 53 THEN 'dns'
                WHEN COALESCE(group_name, '') IN ('', 'business') AND port = 443 THEN 'domestic'
                ELSE COALESCE(NULLIF(group_name, ''), 'business')
            END,
            enabled = COALESCE(is_active, enabled, TRUE),
            updated_at = COALESCE(NULLIF(updated_at, ''), created_at, {q_placeholder})
        """,
        (now,),
    )
    if _use_pg:
        cursor.execute(
            "UPDATE outbound_probe_targets SET is_active = enabled WHERE is_active IS NULL OR is_active IS DISTINCT FROM enabled"
        )
    else:
        cursor.execute(
            "UPDATE outbound_probe_targets SET is_active = enabled WHERE is_active IS NULL OR is_active IS NOT enabled"
        )

    # Add a minimum domestic/international set without duplicating user data.
    cursor.execute("SELECT target_name FROM outbound_probe_targets")
    names = {str(row[0]) for row in cursor.fetchall()}
    defaults = [
        ("default-cloudflare-dns", "Cloudflare DNS", "1.1.1.1", 53, "DNS_RESOLVE", "international", "", 200),
        ("default-baidu-https", "Baidu HTTPS", "www.baidu.com", 443, "HTTPS_GET", "domestic", "https://www.baidu.com/", 200),
        ("default-cloudflare-https", "Cloudflare HTTPS", "www.cloudflare.com", 443, "HTTPS_GET", "international", "https://www.cloudflare.com/", 200),
    ]
    for target_id, name, host, port, probe_type, group_name, url, expected_status in defaults:
        if name in names:
            continue
        _seed_target(
            cursor,
            (target_id, name, host, port, probe_type, True, now, group_name, url, expected_status, "", 2500, True, now),
            _use_pg,
        )
