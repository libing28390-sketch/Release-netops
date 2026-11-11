"""Give IPAM pools explicit scope and independent range policies."""

from __future__ import annotations

import ipaddress


VERSION = 309
NAME = "ipam_pool_range_policies"


def _check_mapped_pool_ranges(cursor) -> None:
    cursor.execute(
        """SELECT pool.id, pool.address_space_id, pool.tenant_id,
                  pool.start_ip, pool.end_ip, prefix.address_space_id AS prefix_space_id,
                  prefix.tenant_id AS prefix_tenant_id, prefix.prefix
             FROM ipam_pools pool
             JOIN prefixes prefix ON prefix.id = pool.prefix_id
            WHERE pool.address_space_id IS NOT NULL
            ORDER BY pool.address_space_id, pool.id"""
    )
    ranges: dict[tuple[str, int], list[tuple[int, int, str]]] = {}
    invalid: list[str] = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        for row in batch:
            pool_id = str(row['id'])
            space_id = str(row['address_space_id'] or '')
            prefix_space_id = str(row['prefix_space_id'] or '')
            pool_tenant = str(row['tenant_id'] or '').strip()
            prefix_tenant = str(row['prefix_tenant_id'] or '').strip()
            try:
                parent = ipaddress.ip_network(str(row['prefix'] or ''), strict=False)
                start = ipaddress.ip_address(str(row['start_ip'] or '').strip())
                end = ipaddress.ip_address(str(row['end_ip'] or '').strip())
            except ValueError:
                invalid.append(pool_id)
                continue
            if (
                not space_id
                or prefix_space_id != space_id
                or not pool_tenant
                or pool_tenant != prefix_tenant
                or start.version != end.version
                or start.version != parent.version
                or int(start) > int(end)
                or start not in parent
                or end not in parent
            ):
                invalid.append(pool_id)
                continue
            ranges.setdefault((space_id, start.version), []).append((int(start), int(end), pool_id))

    if invalid:
        samples = ', '.join(invalid[:5])
        raise RuntimeError(
            f"IPAM Pool migration blocked: {len(invalid)} mapped Pool(s) have "
            f"an invalid tenant, space, or range; sample Pool IDs: {samples}"
        )

    conflicts: list[str] = []
    conflict_groups = 0
    for (space_id, _version), entries in ranges.items():
        entries.sort(key=lambda item: (item[0], item[1], item[2]))
        max_end = -1
        max_end_pool = ''
        for start, end, pool_id in entries:
            if start <= max_end:
                conflict_groups += 1
                if len(conflicts) < 5:
                    conflicts.append(f"{max_end_pool}/{pool_id}")
            if end > max_end:
                max_end = end
                max_end_pool = pool_id
    if conflict_groups:
        samples = ', '.join(conflicts) if conflicts else 'unavailable'
        raise RuntimeError(
            f"IPAM Pool migration blocked: {conflict_groups} inclusive range overlap(s) "
            f"exist within an address space; sample Pool IDs: {samples}"
        )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM pool range policies require PostgreSQL")

    cursor.execute("ALTER TABLE ipam_pools ADD COLUMN IF NOT EXISTS address_space_id TEXT")
    cursor.execute("ALTER TABLE ipam_pools ADD COLUMN IF NOT EXISTS management_mode TEXT")
    cursor.execute("ALTER TABLE ipam_pools ADD COLUMN IF NOT EXISTS allocation_allowed BOOLEAN")
    cursor.execute(
        "ALTER TABLE ipam_pools ADD COLUMN IF NOT EXISTS mark_populated BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cursor.execute(
        "ALTER TABLE ipam_pools ADD COLUMN IF NOT EXISTS mark_utilized BOOLEAN NOT NULL DEFAULT FALSE"
    )

    # A Pool inherits scope only from a Prefix whose space has already been
    # explicitly established. Legacy scope and policy stay NULL for review;
    # assigning an old row a local or external mode would change allocation.
    cursor.execute(
        """
        UPDATE ipam_pools pool
           SET address_space_id = prefix.address_space_id
          FROM prefixes prefix
         WHERE pool.prefix_id = prefix.id
           AND pool.address_space_id IS NULL
           AND prefix.address_space_id IS NOT NULL
           AND pool.tenant_id IS NOT NULL
           AND prefix.tenant_id IS NOT NULL
           AND pool.tenant_id = prefix.tenant_id
        """
    )
    _check_mapped_pool_ranges(cursor)

    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_ipam_pools_address_space'
            ) THEN
                ALTER TABLE ipam_pools
                    ADD CONSTRAINT fk_ipam_pools_address_space
                    FOREIGN KEY (address_space_id)
                    REFERENCES ipam_address_spaces(id)
                    ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_ipam_pools_management_mode'
            ) THEN
                ALTER TABLE ipam_pools
                    ADD CONSTRAINT ck_ipam_pools_management_mode
                    CHECK (
                        management_mode IS NULL
                        OR management_mode IN (
                            'local_static', 'reserved', 'external_dhcp', 'external_other'
                        )
                    );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_ipam_pools_mode_allocation'
            ) THEN
                ALTER TABLE ipam_pools
                    ADD CONSTRAINT ck_ipam_pools_mode_allocation
                    CHECK (
                        management_mode IS NULL
                        OR management_mode = 'local_static'
                        OR allocation_allowed IS FALSE
                    );
            END IF;
        END $$
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_pools_space_status "
        "ON ipam_pools(address_space_id, status)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Do not discard allocation policy or explicit scope during application
    # rollback. The additive columns remain safe for older code to ignore.
    return None
