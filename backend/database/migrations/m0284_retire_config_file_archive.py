"""Remove credentials and targets for the retired remote config archive."""

from __future__ import annotations


VERSION = 284
NAME = "retire_config_file_archive"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        """
        UPDATE config_backup_policies
           SET tftp_enabled = 0,
               tftp_server = '',
               tftp_port = 69,
               tftp_path_prefix = 'backups',
               tftp_protocol = 'tftp',
               tftp_username = '',
               tftp_password = ''
        """
    )
    cursor.execute("DELETE FROM global_vars WHERE key = 'tftp_backup_settings'")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Removed credentials cannot be restored; retired columns remain for rollback compatibility.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
