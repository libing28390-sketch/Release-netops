"""Parse and resolve LibreNMS OS detection/discovery rules.

LibreNMS is the trusted source for vendor OID rules.  The parser keeps only
secret-free detection evidence and numeric ``num_oid`` candidates; it never
copies PHP execution code into the Nexora runtime.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover - deployment dependency
    yaml = None

from database import get_db_connection

logger = logging.getLogger(__name__)

_VENDOR_BY_OS = {
    "ios": "Cisco", "iosxe": "Cisco", "iosxr": "Cisco", "comware": "H3C", "vrp": "Huawei",
    "arista": "Arista", "eos": "Arista", "junos": "Juniper", "fortios": "Fortinet",
    "ruijie": "Ruijie", "zxros": "ZTE", "raisecom": "Raisecom", "arubaos": "Aruba",
    "smartzone": "Ruckus", "ruckus": "Ruckus", "mikrotik": "MikroTik", "dlink": "D-Link",
    "tplink": "TP-Link", "allied": "Allied Telesis", "extreme": "Extreme Networks",
    "brocade": "Brocade", "f5": "F5", "paloalto": "Palo Alto", "sonicwall": "SonicWall",
    "checkpoint": "Check Point", "sophos": "Sophos", "watchguard": "WatchGuard",
}
_AUTO_SYNC_LOCK = threading.Lock()
_AUTO_SYNC_DONE = False


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def source_root() -> Path:
    import os

    configured = str(os.environ.get("LIBRENMS_REPO_PATH") or "").strip()
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[1] / "data" / "librenms_repo"


def source_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
        ).stdout.strip()[:64]
    except Exception:
        return ""


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        return dict(value) if isinstance(value, Mapping) else {}
    except Exception as exc:
        logger.debug("LibreNMS YAML parse failed for %s: %s", path, exc)
        return {}


def _numeric_oid(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\{\{[^}]+\}\}", "", text).strip().strip(".")
    match = re.search(r"(?:^|[^0-9])(1(?:\.[0-9]+)+)(?:$|[^0-9])", text)
    return "." + match.group(1) if match else ""


def _category(context: str) -> str:
    token = context.casefold()
    if any(item in token for item in ("cpu", "processor", "cpurate", "cpuload")):
        return "cpu"
    if any(item in token for item in ("memory", "mempool", "memusage", "buffer")):
        return "memory"
    if "temp" in token:
        return "temperature"
    if "fan" in token:
        return "fan"
    if any(item in token for item in ("power", "psu", "supply")):
        return "power_supply"
    if any(item in token for item in ("accesspoint", "onlineap", "wireless")):
        return "wireless_ap_online_count"
    if any(item in token for item in ("client", "station", "assocuser")):
        return "wireless_client_online_count"
    return "other"


def _collect_candidates(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key).casefold() in {"num_oid", "num_oids", "numeric_oid"}:
                values = child if isinstance(child, list) else [child]
                for raw in values:
                    oid = _numeric_oid(raw)
                    if oid:
                        output.append({"category": _category(child_path), "oid": oid, "context": child_path})
            output.extend(_collect_candidates(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            output.extend(_collect_candidates(child, path=f"{path}[{index}]"))
    return output


def parse_rules(root: Path | None = None) -> list[dict[str, Any]]:
    root = (root or source_root()).resolve()
    detection_dir = root / "resources" / "definitions" / "os_detection"
    discovery_dir = root / "resources" / "definitions" / "os_discovery"
    if not detection_dir.exists():
        return []
    commit = source_commit(root)
    rules: list[dict[str, Any]] = []
    for detection_path in sorted(detection_dir.glob("*.yaml")):
        os_key = detection_path.stem.casefold()
        detection = _load_yaml(detection_path)
        discovery_path = discovery_dir / detection_path.name
        discovery = _load_yaml(discovery_path)
        candidates = _collect_candidates(discovery)
        rules.append(
            {
                "id": f"librenms-{os_key}-{commit[:12] or 'local'}",
                "os_key": os_key,
                "vendor": _VENDOR_BY_OS.get(os_key, ""),
                "platform": str(detection.get("os") or os_key),
                "display_name": str(detection.get("text") or os_key),
                "detection": {
                    "sysObjectID": detection.get("discovery") or [],
                    "sysDescr": detection.get("sysDescr") or [],
                    "sysDescr_regex": detection.get("sysDescr_regex") or [],
                },
                "oid_candidates": candidates,
                "source_path": str(detection_path.relative_to(root)).replace("\\", "/"),
                "source_commit": commit,
                "rule_status": "active" if candidates or detection else "identity_only",
                "generated_at": _now(),
            }
        )
    return rules


def sync_rules(conn: Any, root: Path | None = None) -> dict[str, int | str]:
    rules = parse_rules(root)
    if not rules:
        return {"imported": 0, "candidates": 0, "source_commit": ""}
    for rule in rules:
        conn.execute(
            """
            INSERT INTO snmp_librenms_rules
              (id, os_key, vendor, platform, display_name, detection_json,
               oid_candidates_json, source_path, source_commit, rule_status,
               generated_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
              vendor = excluded.vendor, platform = excluded.platform,
              display_name = excluded.display_name, detection_json = excluded.detection_json,
              oid_candidates_json = excluded.oid_candidates_json, source_path = excluded.source_path,
              source_commit = excluded.source_commit, rule_status = excluded.rule_status,
              updated_at = excluded.updated_at
            """,
            (
                rule["id"], rule["os_key"], rule["vendor"], rule["platform"], rule["display_name"],
                json.dumps(rule["detection"], ensure_ascii=False, sort_keys=True),
                json.dumps(rule["oid_candidates"], ensure_ascii=False, sort_keys=True),
                rule["source_path"], rule["source_commit"], rule["rule_status"], rule["generated_at"], _now(),
            ),
        )
    conn.commit()
    return {
        "imported": len(rules),
        "candidates": sum(len(rule["oid_candidates"]) for rule in rules),
        "source_commit": str(rules[0]["source_commit"]),
    }


def sync_rules_from_repository(root: Path | None = None) -> dict[str, int | str]:
    conn = get_db_connection()
    try:
        return sync_rules(conn, root)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def resolve_rule(conn: Any, identity: Mapping[str, Any]) -> dict[str, Any] | None:
    """Pick the best persisted LibreNMS rule for one observed identity."""
    vendor = str(identity.get("vendor") or "").casefold()
    platform = str(identity.get("platform") or "").casefold()
    sys_object_id = str(identity.get("sys_object_id") or "").casefold()
    sys_descr = str(identity.get("sys_descr") or "").casefold()
    rows = conn.execute(
        "SELECT * FROM snmp_librenms_rules WHERE rule_status IN ('active','identity_only') ORDER BY vendor, os_key"
    ).fetchall()
    best: tuple[int, dict[str, Any]] | None = None
    for row in rows:
        item = dict(row)
        if item.get("vendor") and str(item["vendor"]).casefold() != vendor:
            continue
        try:
            detection = json.loads(item.get("detection_json") or "{}")
            candidates = json.loads(item.get("oid_candidates_json") or "[]")
        except (TypeError, ValueError):
            detection, candidates = {}, []
        score = 0
        for raw in detection.get("sysObjectID") or []:
            text = str(raw or "").strip().casefold()
            if text and text.strip(".") in sys_object_id.strip("."):
                score = max(score, 100)
        for raw in detection.get("sysDescr") or []:
            if str(raw or "").casefold() in sys_descr:
                score = max(score, 80)
        for raw in detection.get("sysDescr_regex") or []:
            try:
                if re.search(str(raw), sys_descr, re.IGNORECASE):
                    score = max(score, 90)
            except re.error:
                continue
        if platform and str(item.get("platform") or "").casefold() in platform:
            score = max(score, 60)
        if score <= 0:
            continue
        item["detection"] = detection
        item["oid_candidates"] = candidates
        item["score"] = score
        if best is None or score > best[0]:
            best = (score, item)
    return best[1] if best else None


def ensure_rules_available() -> dict[str, Any]:
    """Fetch and index LibreNMS sources once when no trusted rules exist."""
    global _AUTO_SYNC_DONE
    if _AUTO_SYNC_DONE:
        return {"status": "cached"}
    with _AUTO_SYNC_LOCK:
        if _AUTO_SYNC_DONE:
            return {"status": "cached"}
        from services.librenms_mib_service import fetch_librenms_sources

        root = source_root()
        if not (root / "resources" / "definitions" / "os_detection").exists():
            fetch_librenms_sources(root)
        result = sync_rules_from_repository(root)
        _AUTO_SYNC_DONE = True
        return {"status": "synced", **result}
