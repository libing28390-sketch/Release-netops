"""Upgrade ip_inventory from bare-IP primary key to multi-device/multi-VRF composite key.

Previously ``ip_inventory`` used ``ip TEXT PRIMARY KEY``, which caused SNMP/CLI
interface IP persistence to fail with a collision error whenever two devices in
different VRFs, sites, or HA pairs shared an overlapping private IP (for example
``192.168.1.1``).
"""

from __future__ import annotations

VERSION = 336
NAME = "ip_inventory_multi_domain_key"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute(
        "ALTER TABLE ip_inventory ADD COLUMN IF NOT EXISTS vrf_name TEXT NOT NULL DEFAULT 'default'"
    )
    cursor.execute("UPDATE ip_inventory SET device_id = '' WHERE device_id IS NULL")
    cursor.execute("UPDATE ip_inventory SET interface = '' WHERE interface IS NULL")
    cursor.execute(
        "UPDATE ip_inventory SET vrf_name = 'default' WHERE vrf_name IS NULL OR BTRIM(vrf_name) = ''"
    )
    cursor.execute("ALTER TABLE ip_inventory ALTER COLUMN device_id SET DEFAULT ''")
    cursor.execute("ALTER TABLE ip_inventory ALTER COLUMN device_id SET NOT NULL")
    cursor.execute("ALTER TABLE ip_inventory ALTER COLUMN interface SET DEFAULT ''")
    cursor.execute("ALTER TABLE ip_inventory ALTER COLUMN interface SET NOT NULL")
    cursor.execute("ALTER TABLE ip_inventory ALTER COLUMN vrf_name SET DEFAULT 'default'")
    cursor.execute("ALTER TABLE ip_inventory ALTER COLUMN vrf_name SET NOT NULL")
    cursor.execute(
        """
        DO $$
        DECLARE
            pk_name text;
            pk_cols text[];
        BEGIN
            SELECT c.conname,
                   ARRAY(
                       SELECT a.attname::text
                         FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                         JOIN pg_attribute a
                           ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                        ORDER BY k.ord
                   )
              INTO pk_name, pk_cols
              FROM pg_constraint c
             WHERE c.conrelid = 'ip_inventory'::regclass
               AND c.contype = 'p'
             LIMIT 1;

            IF pk_name IS NOT NULL
               AND pk_cols IS DISTINCT FROM ARRAY['device_id', 'interface', 'vrf_name', 'ip'] THEN
                EXECUTE format('ALTER TABLE ip_inventory DROP CONSTRAINT %I', pk_name);
                pk_name := NULL;
            END IF;

            IF pk_name IS NULL THEN
                ALTER TABLE ip_inventory
                    ADD CONSTRAINT ip_inventory_pkey
                    PRIMARY KEY (device_id, interface, vrf_name, ip);
            END IF;
        END $$;
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ip_inventory_ip ON ip_inventory(ip)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ip_inventory_device_vrf ON ip_inventory(device_id, vrf_name)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("DROP INDEX IF EXISTS idx_ip_inventory_device_vrf")
    cursor.execute("DROP INDEX IF EXISTS idx_ip_inventory_ip")
