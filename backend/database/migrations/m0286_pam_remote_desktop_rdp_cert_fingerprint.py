"""Add an optional SHA-256 certificate pin to RDP asset profiles."""

from __future__ import annotations


VERSION = 286
NAME = "pam_remote_desktop_rdp_cert_fingerprint"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        """
        ALTER TABLE asset_remote_desktop_profiles
            ADD COLUMN IF NOT EXISTS rdp_cert_fingerprint TEXT NOT NULL DEFAULT ''
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve configured trust pins during application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
