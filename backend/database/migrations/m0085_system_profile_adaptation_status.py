"""Record whether a SYSTEM profile has production-confirmed CLI samples."""

from __future__ import annotations


VERSION = 85
NAME = "system_profile_adaptation_status"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "platform_profiles", use_pg)
    if "adaptation_status" not in columns:
        cursor.execute(
            "ALTER TABLE platform_profiles ADD COLUMN adaptation_status TEXT NOT NULL DEFAULT 'UNVERIFIED'"
        )
    if "sample_status" not in columns:
        cursor.execute(
            "ALTER TABLE platform_profiles ADD COLUMN sample_status TEXT NOT NULL DEFAULT 'MISSING'"
        )

    # Do not manufacture show-version samples.  The domestic profiles are
    # explicitly visible as unverified until a real device capture is
    # supplied; their existing system release remains immutable and readable.
    cursor.execute(
        """UPDATE platform_profiles
           SET adaptation_status = CASE
               WHEN source = 'SYSTEM' AND platform_code IN (
                   'zte_5900_v6', 'zte_zsrv2_v3',
                   'ruijie_s6k_rgos12', 'ruijie_eg_rgos11',
                   'dptech_fw_s211', 'maipu_s3330_v9'
               ) THEN 'UNVERIFIED'
               WHEN source = 'SYSTEM' THEN 'BASELINE'
               ELSE COALESCE(NULLIF(adaptation_status, ''), 'UNVERIFIED')
           END,
           sample_status = CASE
               WHEN source = 'SYSTEM' THEN 'MISSING'
               ELSE COALESCE(NULLIF(sample_status, ''), 'MISSING')
           END"""
    )
