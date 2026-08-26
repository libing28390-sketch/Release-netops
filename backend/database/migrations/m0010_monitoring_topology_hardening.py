"""Monitoring and topology reliability hardening.

Adds durable collector health, discovery progress metadata, topology match
evidence, and canonical site references without removing legacy columns.
"""

VERSION = 10
NAME = "monitoring_topology_hardening"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_columns(cursor, table: str, definitions: list[tuple[str, str]], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    for name, definition in definitions:
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_snmp_communities(cursor) -> None:
    """Move legacy device SNMP communities into the encrypted credential row.

    Existing encrypted credential values win. A device value is only cleared
    after it has been encrypted successfully, so installations without a valid
    encryption key remain backward compatible instead of losing access.
    """
    try:
        from core.crypto import encrypt_credential
    except Exception:
        return

    rows = cursor.execute(
        """
        SELECT d.id, d.credential_id, d.snmp_community,
               c.snmp_community AS credential_snmp_community
        FROM devices d
        LEFT JOIN credentials c ON c.id = d.credential_id
        WHERE COALESCE(d.snmp_community, '') <> ''
        """
    ).fetchall()
    for row in rows:
        device_id, credential_id, community, credential_value = row[0], row[1], row[2], row[3]
        if not credential_id:
            continue
        try:
            encrypted = credential_value or encrypt_credential(community)
        except Exception:
            continue
        if not encrypted:
            continue
        cursor.execute(
            "UPDATE credentials SET snmp_community = ? WHERE id = ?",
            (encrypted, credential_id),
        )
        cursor.execute("UPDATE devices SET snmp_community = '' WHERE id = ?", (device_id,))


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS device_collection_status (
            device_id TEXT NOT NULL,
            collector TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unknown',
            transport TEXT DEFAULT '',
            source TEXT DEFAULT '',
            last_attempt_at TEXT,
            last_success_at TEXT,
            duration_ms REAL,
            consecutive_failures INTEGER DEFAULT 0,
            coverage_total INTEGER DEFAULT 0,
            coverage_supported INTEGER DEFAULT 0,
            error_code TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (device_id, collector),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_status_collector_status "
        "ON device_collection_status(collector, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_status_last_success "
        "ON device_collection_status(last_success_at)"
    )

    _ensure_columns(cursor, "topology_discovery_runs", [
        ("site_id", "TEXT DEFAULT ''"),
        ("scope_json", "TEXT DEFAULT '{}'"),
        ("cancel_requested", "INTEGER DEFAULT 0"),
    ], use_pg)
    _ensure_columns(cursor, "topology_discovery_run_devices", [
        ("error_code", "TEXT DEFAULT ''"),
    ], use_pg)
    _ensure_columns(cursor, "topology_observations", [
        ("source_site_id", "TEXT DEFAULT ''"),
        ("match_method", "TEXT DEFAULT ''"),
        ("match_status", "TEXT DEFAULT 'unmatched'"),
        ("match_candidates_json", "TEXT DEFAULT '[]'"),
    ], use_pg)
    _ensure_columns(cursor, "topology_links", [
        ("source_site_id", "TEXT DEFAULT ''"),
        ("target_site_id", "TEXT DEFAULT ''"),
    ], use_pg)

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_topology_run_device "
        "ON topology_discovery_run_devices(run_id, device_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_runs_site_status "
        "ON topology_discovery_runs(site_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_links_sites "
        "ON topology_links(source_site_id, target_site_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_obs_match_status "
        "ON topology_observations(match_status, source_site_id)"
    )

    cursor.execute(
        """
        UPDATE topology_observations
        SET source_site_id = COALESCE(
            (SELECT d.site_id FROM devices d WHERE d.id = topology_observations.source_device_id),
            ''
        )
        WHERE COALESCE(source_site_id, '') = ''
        """
    )
    cursor.execute(
        """
        UPDATE topology_observations
        SET match_status = CASE
                WHEN target_device_id IS NOT NULL THEN 'matched'
                ELSE 'unmatched'
            END,
            match_method = CASE
                WHEN target_device_id IS NOT NULL AND COALESCE(match_method, '') = '' THEN 'legacy'
                ELSE COALESCE(match_method, '')
            END
        """
    )
    cursor.execute(
        """
        UPDATE topology_links
        SET source_site_id = COALESCE(
                (SELECT d.site_id FROM devices d WHERE d.id = topology_links.source_device_id),
                ''
            ),
            target_site_id = COALESCE(
                (SELECT d.site_id FROM devices d WHERE d.id = topology_links.target_device_id),
                ''
            )
        WHERE COALESCE(source_site_id, '') = '' OR COALESCE(target_site_id, '') = ''
        """
    )

    _migrate_snmp_communities(cursor)
