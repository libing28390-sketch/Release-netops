"""Add explicit IPAM FHRP and Anycast logical groups."""

from __future__ import annotations


VERSION = 319
NAME = "ipam_fhrp_groups"


_EXPECTED_COLUMNS = {
    "ipam_fhrp_groups": {
        "id": ("text", "NO"),
        "security_tenant_id": ("text", "NO"),
        "address_space_id": ("text", "NO"),
        "group_type": ("text", "NO"),
        "protocol": ("text", "NO"),
        "group_id": ("text", "NO"),
        "address_family": ("smallint", "NO"),
        "display_name": ("text", "NO"),
        "status": ("text", "NO"),
        "revision": ("integer", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
        "updated_at": ("timestamp with time zone", "NO"),
    },
    "ipam_fhrp_group_members": {
        "id": ("text", "NO"),
        "group_id": ("text", "NO"),
        "device_id": ("text", "NO"),
        "interface_id": ("text", "YES"),
        "interface_name": ("text", "NO"),
        "normalized_interface_name": ("text", "NO"),
        "role": ("text", "YES"),
        "priority": ("integer", "YES"),
        "status": ("text", "NO"),
        "revision": ("integer", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
        "updated_at": ("timestamp with time zone", "NO"),
    },
    "ipam_fhrp_group_vips": {
        "id": ("text", "NO"),
        "group_id": ("text", "NO"),
        "vip_id": ("text", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
    },
}


def _ensure_columns(cursor, table_name: str, expected: dict[str, tuple[str, str]]) -> None:
    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = ?
        """,
        (table_name,),
    )
    columns = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in cursor.fetchall()
    }
    if any(columns.get(name) != shape for name, shape in expected.items()):
        raise RuntimeError(
            f"IPAM FHRP migration blocked: existing {table_name} columns "
            "have an incompatible definition"
        )


def _ensure_tables(cursor) -> None:
    # PostgreSQL requires the matching composite key for the tenant-aware FK.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_address_spaces_id_tenant "
        "ON ipam_address_spaces(id, security_tenant_id)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_fhrp_groups (
            id TEXT PRIMARY KEY,
            security_tenant_id TEXT NOT NULL
                REFERENCES tenants(id) ON DELETE RESTRICT,
            address_space_id TEXT NOT NULL,
            group_type TEXT NOT NULL
                CHECK (group_type IN ('fhrp', 'anycast')),
            protocol TEXT NOT NULL
                CHECK (protocol IN ('hsrp', 'vrrp', 'anycast')),
            group_id TEXT NOT NULL CHECK (btrim(group_id) <> ''),
            address_family SMALLINT NOT NULL CHECK (address_family IN (4, 6)),
            display_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disabled')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_ipam_fhrp_group_protocol CHECK (
                (group_type = 'fhrp' AND protocol IN ('hsrp', 'vrrp'))
                OR (group_type = 'anycast' AND protocol = 'anycast')
            ),
            CONSTRAINT fk_ipam_fhrp_group_address_space_tenant
                FOREIGN KEY (address_space_id, security_tenant_id)
                REFERENCES ipam_address_spaces(id, security_tenant_id)
                ON DELETE RESTRICT
        )
        """
    )
    _ensure_columns(cursor, "ipam_fhrp_groups", _EXPECTED_COLUMNS["ipam_fhrp_groups"])

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_fhrp_group_members (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL
                REFERENCES ipam_fhrp_groups(id) ON DELETE RESTRICT,
            device_id TEXT NOT NULL
                REFERENCES devices(id) ON DELETE RESTRICT,
            interface_id TEXT
                REFERENCES interfaces(id) ON DELETE SET NULL,
            interface_name TEXT NOT NULL CHECK (btrim(interface_name) <> ''),
            normalized_interface_name TEXT NOT NULL
                CHECK (btrim(normalized_interface_name) <> ''),
            role TEXT,
            priority INTEGER CHECK (priority BETWEEN 0 AND 255),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disabled')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_ipam_fhrp_group_member_interface
                UNIQUE (group_id, device_id, normalized_interface_name)
        )
        """
    )
    _ensure_columns(
        cursor,
        "ipam_fhrp_group_members",
        _EXPECTED_COLUMNS["ipam_fhrp_group_members"],
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_fhrp_group_vips (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL
                REFERENCES ipam_fhrp_groups(id) ON DELETE RESTRICT,
            vip_id TEXT NOT NULL
                REFERENCES ipam_vips(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_ipam_fhrp_group_vip_identity UNIQUE (vip_id)
        )
        """
    )
    _ensure_columns(
        cursor,
        "ipam_fhrp_group_vips",
        _EXPECTED_COLUMNS["ipam_fhrp_group_vips"],
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_fhrp_groups_space_status "
        "ON ipam_fhrp_groups(address_space_id, status, protocol)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_fhrp_group_members_device "
        "ON ipam_fhrp_group_members(device_id, normalized_interface_name)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_fhrp_group_members_group "
        "ON ipam_fhrp_group_members(group_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_fhrp_group_vips_group "
        "ON ipam_fhrp_group_vips(group_id, vip_id)"
    )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM FHRP groups require PostgreSQL")
    _ensure_tables(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Explicit group and relationship records must survive application rollback.
    return None
