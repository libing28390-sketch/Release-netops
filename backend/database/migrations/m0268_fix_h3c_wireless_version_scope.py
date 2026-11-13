"""Remove the non-version ``Comware Dot11`` scope from H3C wireless OIDs."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 268
NAME = "fix_h3c_wireless_version_scope"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("H3C wireless version-scope repair requires PostgreSQL")

    # The old scope names an SNMP feature/MIB family, not a software version.
    # Restrict the backfill to the known bad value so operator-adjusted scopes
    # on the built-in variant are preserved.
    cursor.execute(
        """
        UPDATE snmp_module_variants
           SET supported_version_scope = ?, updated_at = ?
         WHERE variant_key = ?
           AND supported_version_scope = ?
           AND module_id IN (
               SELECT id
                 FROM snmp_modules
                WHERE module_key = ? AND built_in = 1
           )
        """,
        ("[]", _now(), "h3c_wireless_std", '["Comware Dot11"]', "h3c_wireless"),
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("H3C wireless version-scope repair requires PostgreSQL")
    # Reintroducing the invalid filter would disable working Comware AC targets.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
