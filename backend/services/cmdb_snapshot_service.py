"""Generation-fenced metadata for CMDB interface and VLAN snapshots."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from database import get_db_connection
from services.cmdb_version_service import bump_read_versions


_VALID_DOMAINS = frozenset({"interface_inventory", "vlan_inventory"})
_SAFE_CODE = re.compile(r"[^A-Za-z0-9_.-]+")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_metadata(value: dict[str, Any] | None) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def _domain(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _VALID_DOMAINS:
        raise ValueError("Unsupported CMDB collection snapshot domain")
    return normalized


def begin_snapshot_attempt(device_id: str, domain: str) -> dict[str, Any]:
    """Durably advance one domain generation before any device I/O begins."""
    normalized_domain = _domain(domain)
    run_id = str(uuid.uuid4())
    started_at = _now()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """INSERT INTO cmdb_collection_snapshots
                   (device_id, domain, attempt_generation, attempt_status,
                    run_id, last_attempt_at, failure_code, metadata_json)
               VALUES (?, ?, 1, 'running', ?, ?, '', '{}')
               ON CONFLICT (device_id, domain) DO UPDATE SET
                   attempt_generation = cmdb_collection_snapshots.attempt_generation + 1,
                   attempt_status = 'running',
                   run_id = excluded.run_id,
                   last_attempt_at = excluded.last_attempt_at,
                   failure_code = '',
                   metadata_json = '{}'
               RETURNING attempt_generation""",
            (str(device_id), normalized_domain, run_id, started_at),
        ).fetchone()
        conn.commit()
        return {
            "device_id": str(device_id),
            "domain": normalized_domain,
            "generation": int(row["attempt_generation"]),
            "run_id": run_id,
            "started_at": started_at,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_snapshot(
    conn,
    attempt: dict[str, Any],
    *,
    observed_at: str,
    transport: str,
    record_count: int,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Mark the current attempt successful inside the caller's fact transaction.

    A stale worker cannot publish a newer successful generation. The caller
    must rollback its fact writes when ``False`` is returned.
    """
    domain = _domain(str(attempt.get("domain") or ""))
    current = conn.execute(
        """SELECT attempt_generation FROM cmdb_collection_snapshots
           WHERE device_id = ? AND domain = ? FOR UPDATE""",
        (str(attempt["device_id"]), domain),
    ).fetchone()
    generation = int(attempt.get("generation") or 0)
    if not current or int(current["attempt_generation"] or 0) != generation:
        return False

    completed_at = str(observed_at or _now())
    conn.execute(
        """UPDATE cmdb_collection_snapshots
           SET successful_generation = ?, attempt_status = 'success',
               last_success_at = ?, observed_at = ?, transport = ?,
               record_count = ?, failure_code = ?, metadata_json = ?
           WHERE device_id = ? AND domain = ? AND attempt_generation = ?""",
        (
            generation,
            completed_at,
            completed_at,
            str(transport or "")[:32],
            max(0, int(record_count)),
            "",
            _safe_metadata(metadata),
            str(attempt["device_id"]),
            domain,
            generation,
        ),
    )
    bump_read_versions(
        conn,
        ("interfaces",)
        if domain == "interface_inventory"
        else ("vlans", "bindings", "interfaces"),
    )
    return True


def fail_snapshot_attempt(
    attempt: dict[str, Any],
    *,
    error_code: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a failed current attempt without replacing last-good facts/time."""
    domain = _domain(str(attempt.get("domain") or ""))
    code = _SAFE_CODE.sub("_", str(error_code or "collection_failed"))[:80]
    conn = get_db_connection()
    try:
        conn.execute(
            """UPDATE cmdb_collection_snapshots
               SET attempt_status = 'failed', failure_code = ?, metadata_json = ?
               WHERE device_id = ? AND domain = ? AND attempt_generation = ?
                 AND attempt_status = 'running'""",
            (
                code,
                _safe_metadata(metadata),
                str(attempt["device_id"]),
                domain,
                int(attempt.get("generation") or 0),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def replace_device_vlan_observations(
    conn,
    attempt: dict[str, Any],
    observations: Iterable[dict[str, Any]],
) -> int:
    """Replace one device's complete CLI VLAN observation set transactionally."""
    domain = _domain(str(attempt.get("domain") or ""))
    if domain != "vlan_inventory":
        raise ValueError("Device VLAN observations require a VLAN inventory attempt")
    device_id = str(attempt["device_id"])
    generation = int(attempt.get("generation") or 0)
    run_id = str(attempt.get("run_id") or "")
    observed_at = str(attempt.get("observed_at") or "")
    normalized: dict[int, dict[str, Any]] = {}
    for item in observations:
        vlan_id = int(item.get("vlan_id"))
        if not 1 <= vlan_id <= 4094:
            raise ValueError("CLI VLAN ID outside 1..4094")
        normalized[vlan_id] = {
            "site_id": str(item.get("site_id") or ""),
            "vlan_name": str(item.get("vlan_name") or "").strip(),
            "vlan_status": str(item.get("vlan_status") or "").strip(),
        }

    current = conn.execute(
        """SELECT attempt_generation FROM cmdb_collection_snapshots
           WHERE device_id = ? AND domain = ? FOR UPDATE""",
        (device_id, domain),
    ).fetchone()
    if not current or int(current["attempt_generation"] or 0) != generation:
        raise RuntimeError("CMDB VLAN snapshot was superseded")

    for vlan_id, item in normalized.items():
        conn.execute(
            """INSERT INTO cmdb_device_vlan_observations
                   (device_id, vlan_id, site_id, vlan_name, vlan_status,
                    generation, observed_at, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (device_id, vlan_id) DO UPDATE SET
                   site_id = excluded.site_id,
                   vlan_name = excluded.vlan_name,
                   vlan_status = excluded.vlan_status,
                   generation = excluded.generation,
                   observed_at = excluded.observed_at,
                   run_id = excluded.run_id""",
            (
                device_id, vlan_id, item["site_id"], item["vlan_name"],
                item["vlan_status"], generation, observed_at or None, run_id,
            ),
        )
    conn.execute(
        """DELETE FROM cmdb_device_vlan_observations
           WHERE device_id = ? AND generation < ?""",
        (device_id, generation),
    )
    return len(normalized)
