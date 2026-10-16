"""Persist remote desktop profiles and single-use PAM tunnel leases."""

from __future__ import annotations


VERSION = 285
NAME = "pam_remote_desktop"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    """Create the profile table and add remote desktop PAM state.

    This migration runs after the baseline on both fresh installations and
    upgrades, so keeping the new DDL here keeps both paths aligned without
    adding a second copy of the table to the legacy bootstrap.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_remote_desktop_profiles (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            protocol TEXT NOT NULL,
            profile_name TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            port INTEGER NOT NULL,
            normal_credential_id TEXT,
            admin_credential_id TEXT,
            rdp_domain TEXT NOT NULL DEFAULT '',
            rdp_security_mode TEXT NOT NULL DEFAULT 'nla',
            clipboard_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT asset_remote_desktop_profiles_protocol_check
                CHECK (protocol IN ('rdp', 'vnc')),
            CONSTRAINT asset_remote_desktop_profiles_port_check
                CHECK (port BETWEEN 1 AND 65535),
            CONSTRAINT asset_remote_desktop_profiles_rdp_security_check
                CHECK (rdp_security_mode IN ('any', 'nla', 'tls', 'rdp')),
            CONSTRAINT asset_remote_desktop_profiles_asset_protocol_key
                UNIQUE (asset_id, protocol),
            CONSTRAINT asset_remote_desktop_profiles_asset_fkey
                FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE,
            CONSTRAINT asset_remote_desktop_profiles_normal_credential_fkey
                FOREIGN KEY (normal_credential_id) REFERENCES credentials(id) ON DELETE RESTRICT,
            CONSTRAINT asset_remote_desktop_profiles_admin_credential_fkey
                FOREIGN KEY (admin_credential_id) REFERENCES credentials(id) ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_remote_desktop_profiles_asset_enabled "
        "ON asset_remote_desktop_profiles(asset_id, enabled, protocol)"
    )

    cursor.execute(
        """
        ALTER TABLE pam_sessions
            ADD COLUMN IF NOT EXISTS remote_desktop_protocol TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS remote_desktop_profile_id TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS remote_desktop_ticket_hash TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS remote_desktop_requester_id TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS remote_desktop_lease_owner TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS remote_desktop_lease_until TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS remote_desktop_guac_id TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS remote_desktop_recording_closed BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pam_sessions_remote_desktop_ticket_hash "
        "ON pam_sessions(remote_desktop_ticket_hash) "
        "WHERE remote_desktop_ticket_hash <> ''"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_pam_sessions_remote_desktop_lease "
        "ON pam_sessions(status, remote_desktop_lease_until) "
        "WHERE remote_desktop_protocol <> ''"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep session metadata and profiles during rollback so active sessions and
    # audit history remain recoverable. The feature can be disabled at the API
    # and deployment boundary without destroying operator data.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
