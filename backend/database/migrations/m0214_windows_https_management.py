"""Add the minimal Windows WinRM HTTPS management fields."""

from __future__ import annotations


VERSION = 214
NAME = "windows_https_management"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Windows HTTPS management migration requires PostgreSQL")

    columns = (
        ("winrm_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("winrm_port", "INTEGER NOT NULL DEFAULT 5986"),
        ("winrm_auth_mode", "TEXT NOT NULL DEFAULT 'ntlm'"),
        ("winrm_tls_mode", "TEXT NOT NULL DEFAULT 'pin_fingerprint'"),
        ("winrm_cert_fingerprint", "TEXT NOT NULL DEFAULT ''"),
    )
    for name, definition in columns:
        cursor.execute(
            f"ALTER TABLE physical_assets ADD COLUMN IF NOT EXISTS {name} {definition}"
        )

    constraints = (
        ("ck_physical_assets_winrm_auth_mode", "winrm_auth_mode IN ('ntlm', 'basic')"),
        ("ck_physical_assets_winrm_tls_mode", "winrm_tls_mode IN ('verify_ca', 'pin_fingerprint', 'insecure_lab')"),
        ("ck_physical_assets_winrm_port", "winrm_port BETWEEN 1 AND 65535"),
    )
    for name, expression in constraints:
        cursor.execute(f"ALTER TABLE physical_assets DROP CONSTRAINT IF EXISTS {name}")
        cursor.execute(
            f"ALTER TABLE physical_assets ADD CONSTRAINT {name} CHECK ({expression})"
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Retain additive fields so rolling back the application does not destroy
    # an operator's Windows access configuration.
    return None
