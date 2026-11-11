"""Add explicit IPAM address-space identity and preserve unresolved legacy scope."""

from __future__ import annotations


VERSION = 308
NAME = "ipam_address_spaces"


def _raise_if_duplicates(
    cursor, *, sql: str, label: str, sample_sql: str,
) -> None:
    cursor.execute(sql)
    row = cursor.fetchone()
    if row and int(row[0] or 0):
        group_count = int(row[0])
        cursor.execute(sample_sql)
        examples = [str(sample[0]) for sample in cursor.fetchmany(5)]
        example_text = ', '.join(examples) if examples else 'unavailable'
        raise RuntimeError(
            f"IPAM address-space migration blocked: {label} contains "
            f"{group_count} duplicate group(s); sample row IDs: {example_text}; "
            "resolve them before enabling scope indexes"
        )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM address spaces require PostgreSQL")

    # A composite FK below ensures that a VRF and its address-space security
    # tenant cannot disagree. The VRF primary key already makes this pair
    # unique, but PostgreSQL needs a matching unique key for the FK target.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vrfs_id_tenant_id "
        "ON vrfs(id, tenant_id)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_address_spaces (
            id TEXT PRIMARY KEY,
            security_tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('global', 'vrf')),
            vrf_id TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'inactive')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CONSTRAINT ipam_address_spaces_kind_vrf_chk CHECK (
                (kind = 'global' AND vrf_id IS NULL)
                OR (kind = 'vrf' AND vrf_id IS NOT NULL)
            ),
            CONSTRAINT ipam_address_spaces_tenant_fk
                FOREIGN KEY (security_tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT,
            CONSTRAINT ipam_address_spaces_vrf_tenant_fk
                FOREIGN KEY (vrf_id, security_tenant_id)
                REFERENCES vrfs(id, tenant_id) ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_address_spaces_tenant_name "
        "ON ipam_address_spaces(security_tenant_id, lower(btrim(name)))"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_address_spaces_vrf "
        "ON ipam_address_spaces(vrf_id) WHERE vrf_id IS NOT NULL"
    )

    cursor.execute(
        "ALTER TABLE prefixes ADD COLUMN IF NOT EXISTS address_space_id TEXT "
        "REFERENCES ipam_address_spaces(id) ON DELETE RESTRICT"
    )
    cursor.execute(
        "ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS address_space_id TEXT "
        "REFERENCES ipam_address_spaces(id) ON DELETE RESTRICT"
    )

    # Materialize only VRFs whose tenant is explicit. Empty/unknown VRF scope
    # is not evidence of a Global address space.
    cursor.execute(
        """
        WITH vrf_names AS (
            SELECT id, tenant_id, NULLIF(btrim(vrf_name), '') AS vrf_name,
                   COUNT(*) OVER (
                       PARTITION BY tenant_id, lower(NULLIF(btrim(vrf_name), ''))
                   ) AS name_count
              FROM vrfs
             WHERE tenant_id IS NOT NULL
        )
        INSERT INTO ipam_address_spaces (
            id, security_tenant_id, name, kind, vrf_id,
            status, revision, created_at, updated_at
        )
        SELECT 'as-vrf:' || id, tenant_id,
               CASE
                   WHEN name_count > 1
                       THEN COALESCE(vrf_name, 'VRF') || ' [' || id || ']'
                   ELSE COALESCE(vrf_name, 'VRF ' || id)
               END,
               'vrf', id, 'active', 1,
               CURRENT_TIMESTAMP::text, CURRENT_TIMESTAMP::text
          FROM vrf_names
        ON CONFLICT (id) DO NOTHING
        """
    )

    # Attach a Prefix only when its existing VRF and tenant jointly prove the
    # routing domain and that domain has no same-CIDR row at another site.
    # Such duplicate legacy Prefix rows remain unresolved for explicit review.
    cursor.execute(
        """
        WITH candidates AS (
            SELECT p.id, 'as-vrf:' || p.vrf_id AS address_space_id,
                   COUNT(*) OVER (
                       PARTITION BY p.tenant_id, p.vrf_id, p.prefix_cidr
                   ) AS cidr_count
              FROM prefixes p
              JOIN vrfs v ON v.id = p.vrf_id
                         AND v.tenant_id = p.tenant_id
             WHERE p.vrf_id IS NOT NULL
               AND p.tenant_id IS NOT NULL
               AND p.prefix_cidr IS NOT NULL
               AND p.address_space_id IS NULL
        )
        UPDATE prefixes p
           SET address_space_id = c.address_space_id
          FROM candidates c
         WHERE p.id = c.id
           AND c.cidr_count = 1
        """
    )
    cursor.execute(
        """
        UPDATE ip_addresses ip
           SET address_space_id = p.address_space_id
          FROM prefixes p
         WHERE ip.subnet_id = p.id
           AND p.address_space_id IS NOT NULL
           AND ip.address_space_id IS NULL
        """
    )

    # Fail closed before replacing legacy scope indexes. These checks are
    # intentional: a warning-and-skip would leave the new identity model
    # without its promised database-level uniqueness guarantee.
    _raise_if_duplicates(
        cursor,
        label="unmapped Prefix CIDR identity",
        sql="""
            SELECT COUNT(*) FROM (
                SELECT COALESCE(tenant_id, 'tenant-default'), COALESCE(vrf_id, ''),
                       COALESCE(site_id, ''), prefix_cidr
                  FROM prefixes
                 WHERE address_space_id IS NULL AND prefix_cidr IS NOT NULL
                 GROUP BY COALESCE(tenant_id, 'tenant-default'), COALESCE(vrf_id, ''),
                          COALESCE(site_id, ''), prefix_cidr
                HAVING COUNT(*) > 1
            ) duplicate_groups
        """,
        sample_sql="""
            SELECT string_agg(id, ',') FROM (
                SELECT id, COALESCE(tenant_id, 'tenant-default') AS tenant_key,
                       COALESCE(vrf_id, '') AS vrf_key, COALESCE(site_id, '') AS site_key,
                       prefix_cidr,
                       COUNT(*) OVER (
                           PARTITION BY COALESCE(tenant_id, 'tenant-default'),
                                        COALESCE(vrf_id, ''), COALESCE(site_id, ''), prefix_cidr
                       ) AS duplicate_count
                  FROM prefixes
                 WHERE address_space_id IS NULL AND prefix_cidr IS NOT NULL
            ) duplicates
            WHERE duplicate_count > 1
            GROUP BY tenant_key, vrf_key, site_key, prefix_cidr
            ORDER BY MIN(id)
            LIMIT 5
        """,
    )
    _raise_if_duplicates(
        cursor,
        label="mapped Prefix address-space CIDR identity",
        sql="""
            SELECT COUNT(*) FROM (
                SELECT address_space_id, prefix_cidr
                  FROM prefixes
                 WHERE address_space_id IS NOT NULL AND prefix_cidr IS NOT NULL
                 GROUP BY address_space_id, prefix_cidr
                HAVING COUNT(*) > 1
            ) duplicate_groups
        """,
        sample_sql="""
            SELECT string_agg(id, ',') FROM (
                SELECT id, address_space_id, prefix_cidr
                  FROM prefixes
                 WHERE address_space_id IS NOT NULL AND prefix_cidr IS NOT NULL
            ) rows
            GROUP BY address_space_id, prefix_cidr
            HAVING COUNT(*) > 1
            ORDER BY MIN(id)
            LIMIT 5
        """,
    )
    _raise_if_duplicates(
        cursor,
        label="unmapped active IP identity",
        sql="""
            SELECT COUNT(*) FROM (
                SELECT COALESCE(tenant_id, 'tenant-default'),
                       COALESCE(vrf_id, ''), address_inet
                  FROM ip_addresses
                 WHERE address_space_id IS NULL
                   AND address_inet IS NOT NULL
                   AND COALESCE(status, 'active') NOT IN ('released', 'available')
                 GROUP BY COALESCE(tenant_id, 'tenant-default'),
                          COALESCE(vrf_id, ''), address_inet
                HAVING COUNT(*) > 1
            ) duplicate_groups
        """,
        sample_sql="""
            SELECT string_agg(id, ',') FROM (
                SELECT id, COALESCE(tenant_id, 'tenant-default') AS tenant_key,
                       COALESCE(vrf_id, '') AS vrf_key, address_inet
                  FROM ip_addresses
                 WHERE address_space_id IS NULL
                   AND address_inet IS NOT NULL
                   AND COALESCE(status, 'active') NOT IN ('released', 'available')
            ) rows
            GROUP BY tenant_key, vrf_key, address_inet
            HAVING COUNT(*) > 1
            ORDER BY MIN(id)
            LIMIT 5
        """,
    )
    _raise_if_duplicates(
        cursor,
        label="mapped active IP identity",
        sql="""
            SELECT COUNT(*) FROM (
                SELECT address_space_id, address_inet
                  FROM ip_addresses
                 WHERE address_space_id IS NOT NULL
                   AND address_inet IS NOT NULL
                   AND COALESCE(status, 'active') NOT IN ('released', 'available')
                 GROUP BY address_space_id, address_inet
                HAVING COUNT(*) > 1
            ) duplicate_groups
        """,
        sample_sql="""
            SELECT string_agg(id, ',') FROM (
                SELECT id, address_space_id, address_inet
                  FROM ip_addresses
                 WHERE address_space_id IS NOT NULL
                   AND address_inet IS NOT NULL
                   AND COALESCE(status, 'active') NOT IN ('released', 'available')
            ) rows
            GROUP BY address_space_id, address_inet
            HAVING COUNT(*) > 1
            ORDER BY MIN(id)
            LIMIT 5
        """,
    )

    cursor.execute("DROP INDEX IF EXISTS uq_prefixes_scope_cidr")
    cursor.execute("DROP INDEX IF EXISTS uq_ip_addresses_scope_active")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prefixes_address_space_cidr "
        "ON prefixes(address_space_id, prefix_cidr) "
        "WHERE address_space_id IS NOT NULL AND prefix_cidr IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prefixes_legacy_scope_cidr "
        "ON prefixes(COALESCE(tenant_id, 'tenant-default'), COALESCE(vrf_id, ''), "
        "COALESCE(site_id, ''), prefix_cidr) "
        "WHERE address_space_id IS NULL AND prefix_cidr IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_addresses_space_active "
        "ON ip_addresses(address_space_id, address_inet) "
        "WHERE address_space_id IS NOT NULL AND address_inet IS NOT NULL "
        "AND COALESCE(status, 'active') NOT IN ('released', 'available')"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_addresses_legacy_scope_active "
        "ON ip_addresses(COALESCE(tenant_id, 'tenant-default'), "
        "COALESCE(vrf_id, ''), address_inet) "
        "WHERE address_space_id IS NULL AND address_inet IS NOT NULL "
        "AND COALESCE(status, 'active') NOT IN ('released', 'available')"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_prefixes_address_space "
        "ON prefixes(address_space_id, prefix_cidr)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ip_addresses_address_space "
        "ON ip_addresses(address_space_id, address_inet)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Scope mappings may have been explicitly confirmed after the migration.
    # Retain the additive identity and indexes through application rollback.
    return None
