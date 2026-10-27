"""PostgreSQL revision counters for CMDB-owned read projections.

Call ``bump_read_versions`` in the same transaction as each source write.
External collector-owned tables are intentionally not modified here; their
cache views must use a bounded freshness window or read the dynamic field from
PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def bump_read_versions(conn, domains: Iterable[str], *, scope_key: str = "") -> None:
    """Increment one or more versioned cache namespaces inside the caller txn."""
    now = _utc_now_iso()
    for domain in sorted({str(value).strip().lower() for value in domains if str(value).strip()}):
        conn.execute(
            """INSERT INTO cmdb_read_versions (domain, scope_key, revision, updated_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT (domain, scope_key) DO UPDATE SET
                   revision = cmdb_read_versions.revision + 1,
                   updated_at = excluded.updated_at""",
            (domain, str(scope_key or ""), now),
        )


def read_versions(conn, domains: Iterable[str], *, scope_key: str = "") -> dict[str, int]:
    """Read stable version inputs; missing namespaces start at revision zero."""
    normalized = sorted({str(value).strip().lower() for value in domains if str(value).strip()})
    if not normalized:
        return {}
    placeholders = ",".join("?" for _ in normalized)
    rows = conn.execute(
        f"""SELECT domain, revision FROM cmdb_read_versions
            WHERE scope_key = ? AND domain IN ({placeholders})""",
        (str(scope_key or ""), *normalized),
    ).fetchall()
    found = {str(row["domain"]): int(row["revision"] or 0) for row in rows}
    return {domain: found.get(domain, 0) for domain in normalized}
