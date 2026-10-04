"""Scope WAN probe bindings by their operational purpose.

One outbound target may serve several circuit measurements, but a binding's
purpose determines which protocol is valid for that measurement.  Existing
HTTP/DNS bindings were application checks in practice; all other legacy
bindings remain availability checks.
"""

from __future__ import annotations


VERSION = 266
NAME = "wan_probe_binding_purpose"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN probe binding purpose requires PostgreSQL")

    cursor.execute(
        "ALTER TABLE wan_probe_bindings ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'availability'"
    )
    cursor.execute(
        """
        UPDATE wan_probe_bindings b
           SET purpose = CASE
               WHEN UPPER(COALESCE(t.probe_type, '')) IN
                    ('HTTP', 'HTTPS', 'HTTP_GET', 'HTTPS_GET', 'DNS', 'DNS_RESOLVE')
               THEN 'application'
               ELSE 'availability'
           END
          FROM outbound_probe_targets t
         WHERE t.id = b.target_id
           AND (b.purpose IS NULL OR BTRIM(b.purpose) = '' OR b.purpose = 'availability')
        """
    )
    cursor.execute(
        "ALTER TABLE wan_probe_bindings DROP CONSTRAINT IF EXISTS wan_probe_bindings_link_id_target_id_key"
    )
    cursor.execute(
        "DROP INDEX IF EXISTS uq_wan_probe_bindings_link_target"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wan_probe_bindings_link_target_purpose ON wan_probe_bindings(link_id, target_id, purpose)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_probe_bindings_purpose ON wan_probe_bindings(purpose, enabled)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN probe binding purpose requires PostgreSQL")
    # Preserve purpose-specific bindings and audit evidence during rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
