VERSION = 6
NAME = "asset_legacy_takeover_exemption"
# Some installations created migration version 6 before the versioned
# migration package was consolidated and recorded this same marker as
# ``interface_telemetry_and_history``.  Keep that historical marker explicit
# so upgrades can continue without allowing arbitrary history drift.
LEGACY_NAMES = ("interface_telemetry_and_history",)


def _column_exists(cursor, table_name: str, column_name: str, use_pg: bool) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table_name, column_name),
    )
    return cursor.fetchone() is not None



def upgrade(cursor, use_pg: bool) -> None:
    columns = [
        ("credential_governance_mode", "TEXT DEFAULT 'managed'"),
        ("takeover_exempt_reason", "TEXT DEFAULT ''"),
        ("takeover_exempt_at", "TEXT DEFAULT ''"),
    ]
    for column_name, definition in columns:
        if not _column_exists(cursor, "physical_assets", column_name, use_pg):
            cursor.execute(f"ALTER TABLE physical_assets ADD COLUMN {column_name} {definition}")
