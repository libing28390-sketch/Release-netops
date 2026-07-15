import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from database import get_db_connection
from services.audit_service import log_audit_event, utc_now_iso


BUILTIN_RULES: list[dict[str, Any]] = [
    {
        "id": "MGMT-001",
        "name": "Disable Telnet",
        "description": "Management access must not allow Telnet.",
        "category": "Management Plane",
        "severity": "critical",
        "platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "logic": {"type": "config_absent_any", "patterns": ["transport input telnet", "telnet server enable", "telnet server ipv4"]},
        "remediation": "Disable Telnet and restrict management access to SSH only.",
        "reference": "Internal Network Device Baseline / Management Plane Hardening",
    },
    {
        "id": "MGMT-002",
        "name": "SSHv2 Enabled",
        "description": "Devices should explicitly enable secure SSH management.",
        "category": "Management Plane",
        "severity": "high",
        "platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "logic": {"type": "config_present_any", "patterns": ["ip ssh version 2", "ssh server v2", "stelnet server enable", "set system services ssh"]},
        "remediation": "Enable SSHv2 or the platform-equivalent secure management service.",
        "reference": "Internal Network Device Baseline / Secure Remote Access",
    },
    {
        "id": "SNMP-001",
        "name": "Non-default SNMP Community",
        "description": "Devices must not use default or weak SNMP communities.",
        "category": "Identity and Access",
        "severity": "high",
        "platforms": ["*"],
        "logic": {"type": "snmp_not_default"},
        "remediation": "Replace default SNMP communities with managed secrets or migrate to SNMPv3.",
        "reference": "Internal Network Device Baseline / Secret Hygiene",
    },
    {
        "id": "LOG-001",
        "name": "Centralized Syslog Configured",
        "description": "Devices must send logs to a central collector.",
        "category": "Logging and Time",
        "severity": "medium",
        "platforms": ["*"],
        "logic": {"type": "config_present_any", "patterns": ["logging host", "logging server", "info-center loghost", "set system syslog host"]},
        "remediation": "Configure the approved syslog collector on the device.",
        "reference": "Security Operations Logging Standard",
    },
    {
        "id": "TIME-001",
        "name": "NTP Configured",
        "description": "Devices must synchronize time with approved NTP sources.",
        "category": "Logging and Time",
        "severity": "medium",
        "platforms": ["*"],
        "logic": {"type": "config_present_any", "patterns": ["ntp server", "ntp-service unicast-server", "set system ntp server"]},
        "remediation": "Configure at least one approved NTP server.",
        "reference": "Security Operations Logging Standard",
    },
    {
        "id": "AAA-001",
        "name": "AAA or Central Auth Enabled",
        "description": "Administrative access should be backed by AAA or centralized authentication.",
        "category": "Identity and Access",
        "severity": "high",
        "platforms": ["*"],
        "logic": {"type": "config_present_any", "patterns": ["aaa new-model", "radius-server", "tacacs-server", "authentication-scheme", "set system authentication-order"]},
        "remediation": "Enable AAA / centralized authentication for administrative access.",
        "reference": "Privileged Access Management Standard",
    },
    {
        "id": "L2-001",
        "name": "BPDU Guard or Edge Protection",
        "description": "Access-layer edge protection should be enabled to prevent rogue switching.",
        "category": "Layer2 Security",
        "severity": "medium",
        "platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "logic": {"type": "config_present_any", "patterns": ["spanning-tree bpduguard default", "bpdu-protection enable", "stp edged-port enable", "spanning-tree portfast bpduguard default"]},
        "remediation": "Enable BPDU Guard or the vendor-equivalent edge protection on access ports.",
        "reference": "Campus Access Layer Security Standard",
    },
    {
        "id": "CFG-001",
        "name": "Config Snapshot Available",
        "description": "At least one configuration snapshot should exist for the device.",
        "category": "Change Control",
        "severity": "medium",
        "platforms": ["*"],
        "logic": {"type": "snapshot_exists"},
        "remediation": "Capture and retain a baseline configuration snapshot for this device.",
        "reference": "Change Management Policy",
    },
]


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True)


def ensure_builtin_rules() -> None:
    conn = get_db_connection()
    try:
        now = utc_now_iso()
        for rule in BUILTIN_RULES:
            existing = conn.execute(
                "SELECT id FROM compliance_rules WHERE id = ?", (rule["id"],)
            ).fetchone()
            payload = (
                rule["id"],
                rule["name"],
                rule["description"],
                rule["category"],
                rule["severity"],
                _json_dumps(rule["platforms"]),
                _json_dumps(rule["logic"]),
                rule["remediation"],
                rule["reference"],
                1,
                1,
                now,
                now,
            )
            if existing:
                conn.execute(
                    '''
                    UPDATE compliance_rules
                    SET name = ?, description = ?, category = ?, severity = ?,
                        platforms_json = ?, logic_json = ?, remediation = ?, reference = ?,
                        enabled = 1, updated_at = ?
                    WHERE id = ?
                    ''',
                    (
                        rule["name"],
                        rule["description"],
                        rule["category"],
                        rule["severity"],
                        _json_dumps(rule["platforms"]),
                        _json_dumps(rule["logic"]),
                        rule["remediation"],
                        rule["reference"],
                        now,
                        rule["id"],
                    ),
                )
            else:
                conn.execute(
                    '''
                    INSERT INTO compliance_rules (
                        id, name, description, category, severity,
                        platforms_json, logic_json, remediation, reference,
                        enabled, is_builtin, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    payload,
                )
        conn.commit()
    finally:
        conn.close()


def _normalize_rule(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        item["platforms"] = json.loads(item.get("platforms_json") or "[]")
    except Exception:
        item["platforms"] = []
    try:
        item["logic"] = json.loads(item.get("logic_json") or "{}")
    except Exception:
        item["logic"] = {}
    return item


def list_rules() -> list[dict[str, Any]]:
    ensure_builtin_rules()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM compliance_rules WHERE enabled = 1 ORDER BY severity DESC, category, name"
        ).fetchall()
        return [_normalize_rule(r) for r in rows]
    finally:
        conn.close()


def _rule_applies(rule: dict[str, Any], device: dict[str, Any]) -> bool:
    platforms = rule.get("platforms") or []
    if not platforms or "*" in platforms:
        return True
    return device.get("platform") in platforms


def _match_patterns(config: str, patterns: list[str]) -> list[str]:
    lower = (config or "").lower()
    return [pattern for pattern in patterns if pattern.lower() in lower]


def _extract_snippet(config: str, token: str) -> str:
    if not config or not token:
        return ""
    lines = config.splitlines()
    token_l = token.lower()
    for idx, line in enumerate(lines):
        if token_l in line.lower():
            start = max(0, idx - 1)
            end = min(len(lines), idx + 2)
            return "\n".join(lines[start:end])
    return ""


def _evaluate_rule(rule: dict[str, Any], device: dict[str, Any], snapshot_count: int) -> dict[str, Any] | None:
    logic = rule.get("logic") or {}
    logic_type = logic.get("type")
    config = device.get("current_config") or ""

    if logic_type == "config_absent_any":
        matches = _match_patterns(config, logic.get("patterns") or [])
        if matches:
            return {
                "observed_value": ", ".join(matches),
                "evidence": _extract_snippet(config, matches[0]) or "Matched forbidden management pattern.",
            }
        return None

    if logic_type == "config_present_any":
        matches = _match_patterns(config, logic.get("patterns") or [])
        if not matches:
            return {
                "observed_value": "missing",
                "evidence": "No approved configuration pattern matched the running configuration.",
            }
        return None

    if logic_type == "snmp_not_default":
        community = (device.get("snmp_community") or "").strip().lower()
        if community in {"", "public", "private", "netops"}:
            return {
                "observed_value": community or "empty",
                "evidence": f"Configured SNMP community is '{community or 'empty'}'.",
            }
        return None

    if logic_type == "snapshot_exists":
        if snapshot_count <= 0:
            return {
                "observed_value": "0",
                "evidence": "No configuration snapshot exists for this device.",
            }
        return None

    return None


def run_compliance_audit(
    *,
    device_ids: list[str] | None = None,
    initiated_by: str = "admin",
    actor_id: str | None = None,
    actor_role: str | None = None,
    source_ip: str | None = None,
) -> dict[str, Any]:
    ensure_builtin_rules()
    rules = list_rules()
    run_id = str(uuid.uuid4())
    started_at = utc_now_iso()

    conn = get_db_connection()
    try:
        scope = device_ids or []
        conn.execute(
            '''
            INSERT INTO compliance_runs (id, initiated_by, scope_json, status, started_at, summary_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (run_id, initiated_by, _json_dumps(scope), "running", started_at, _json_dumps({})),
        )
        if device_ids:
            placeholders = ",".join("?" for _ in device_ids)
            device_rows = conn.execute(
                f"SELECT * FROM devices WHERE id IN ({placeholders}) ORDER BY hostname", tuple(device_ids)
            ).fetchall()
        else:
            device_rows = conn.execute("SELECT * FROM devices ORDER BY hostname").fetchall()

        snapshot_rows = conn.execute(
            "SELECT device_id, COUNT(*) AS count FROM config_snapshots GROUP BY device_id"
        ).fetchall()
        snapshot_map = {row["device_id"]: int(row["count"]) for row in snapshot_rows}

        open_findings = conn.execute(
            "SELECT * FROM compliance_findings WHERE status != 'resolved'"
        ).fetchall()
        existing_map = {row["fingerprint"]: dict(row) for row in open_findings}

        now = utc_now_iso()
        active_fingerprints: set[str] = set()
        severity_counter: Counter[str] = Counter()
        category_counter: Counter[str] = Counter()
        device_issue_counter: Counter[str] = Counter()
        total_checks = 0
        passed_checks = 0

        for row in device_rows:
            device = dict(row)
            applicable_rules = [rule for rule in rules if _rule_applies(rule, device)]
            issues_for_device = 0
            for rule in applicable_rules:
                total_checks += 1
                issue = _evaluate_rule(rule, device, snapshot_map.get(device.get("id"), 0))
                fingerprint = f"{device.get('id')}::{rule['id']}"
                if issue is None:
                    passed_checks += 1
                    continue

                active_fingerprints.add(fingerprint)
                issues_for_device += 1
                severity_counter[rule["severity"]] += 1
                category_counter[rule["category"]] += 1
                device_issue_counter[device.get("id")] += 1

                existing = existing_map.get(fingerprint)
                if existing:
                    new_status = existing.get("status") if existing.get("status") == "accepted" else "open"
                    conn.execute(
                        '''
                        UPDATE compliance_findings
                        SET run_id = ?, severity = ?, category = ?, title = ?, description = ?, status = ?,
                            observed_value = ?, evidence = ?, remediation = ?, last_seen_at = ?, resolved_at = NULL
                        WHERE fingerprint = ?
                        ''',
                        (
                            run_id,
                            rule["severity"],
                            rule["category"],
                            rule["name"],
                            rule["description"],
                            new_status,
                            issue.get("observed_value", ""),
                            issue.get("evidence", ""),
                            rule.get("remediation", ""),
                            now,
                            fingerprint,
                        ),
                    )
                else:
                    conn.execute(
                        '''
                        INSERT INTO compliance_findings (
                            id, fingerprint, rule_id, device_id, run_id,
                            severity, category, title, description, status,
                            observed_value, evidence, remediation,
                            owner, note, first_seen_at, last_seen_at, resolved_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, NULL)
                        ''',
                        (
                            str(uuid.uuid4()),
                            fingerprint,
                            rule["id"],
                            device.get("id"),
                            run_id,
                            rule["severity"],
                            rule["category"],
                            rule["name"],
                            rule["description"],
                            "open",
                            issue.get("observed_value", ""),
                            issue.get("evidence", ""),
                            rule.get("remediation", ""),
                            now,
                            now,
                        ),
                    )

            conn.execute(
                "UPDATE devices SET compliance = ? WHERE id = ?",
                ("non-compliant" if issues_for_device > 0 else "compliant", device.get("id")),
            )

        target_device_ids = {d["id"] for d in device_rows}
        for fingerprint, finding in existing_map.items():
            if finding.get("device_id") not in target_device_ids:
                continue
            if fingerprint in active_fingerprints:
                continue
            conn.execute(
                '''
                UPDATE compliance_findings
                SET status = 'resolved', resolved_at = ?, run_id = ?, last_seen_at = ?
                WHERE fingerprint = ?
                ''',
                (now, run_id, now, fingerprint),
            )

        total_devices = len(device_rows)
        score = round((passed_checks / total_checks) * 100) if total_checks else 100
        summary = {
            "run_id": run_id,
            "total_devices": total_devices,
            "total_rules": len(rules),
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": total_checks - passed_checks,
            "score": score,
            "open_findings": sum(severity_counter.values()),
            "severity_counts": dict(severity_counter),
            "category_counts": dict(category_counter),
            "device_issue_counts": dict(device_issue_counter),
        }

        conn.execute(
            "UPDATE compliance_runs SET status = ?, completed_at = ?, summary_json = ? WHERE id = ?",
            ("completed", now, _json_dumps(summary), run_id),
        )
        conn.commit()
    finally:
        conn.close()

    log_audit_event(
        event_type="COMPLIANCE_RUN",
        category="compliance",
        severity="medium",
        status="success",
        summary=f"Compliance audit completed across {summary['total_devices']} device(s)",
        actor_id=actor_id,
        actor_username=initiated_by,
        actor_role=actor_role,
        source_ip=source_ip,
        target_type="compliance_run",
        target_id=run_id,
        target_name="Compliance Audit",
        details=summary,
    )
    return summary


def get_overview() -> dict[str, Any]:
    ensure_builtin_rules()
    conn = get_db_connection()
    try:
        latest_run = conn.execute(
            "SELECT * FROM compliance_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        findings = conn.execute(
            '''
            SELECT cf.*, d.hostname, d.ip_address, d.site, d.role, d.platform
            FROM compliance_findings cf
            LEFT JOIN devices d ON d.id = cf.device_id
            WHERE cf.status != 'resolved'
            ORDER BY
                CASE cf.severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                cf.last_seen_at DESC
            '''
        ).fetchall()
        recent_runs = conn.execute(
            "SELECT * FROM compliance_runs ORDER BY started_at DESC LIMIT 8"
        ).fetchall()
        devices = conn.execute("SELECT id, hostname, compliance, site, platform FROM devices ORDER BY hostname").fetchall()
    finally:
        conn.close()

    items = [dict(row) for row in findings]
    sev_counter = Counter(item.get("severity") or "medium" for item in items)
    cat_counter = Counter(item.get("category") or "Other" for item in items)
    device_counter = Counter(item.get("device_id") for item in items if item.get("device_id"))

    top_devices = []
    device_map = {row["id"]: dict(row) for row in devices}
    for device_id, count in device_counter.most_common(5):
        dev = device_map.get(device_id, {})
        top_devices.append(
            {
                "device_id": device_id,
                "hostname": dev.get("hostname", device_id),
                "site": dev.get("site", ""),
                "platform": dev.get("platform", ""),
                "open_findings": count,
            }
        )

    trend = []
    for row in reversed(recent_runs):
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except Exception:
            summary = {}
        trend.append(
            {
                "run_id": row["id"],
                "started_at": row["started_at"],
                "score": summary.get("score", 0),
                "open_findings": summary.get("open_findings", 0),
                "total_devices": summary.get("total_devices", 0),
            }
        )

    latest_summary = {}
    if latest_run:
        try:
            latest_summary = json.loads(latest_run["summary_json"] or "{}")
        except Exception:
            latest_summary = {}

    return {
        "score": latest_summary.get("score", 100 if not items else max(0, 100 - len(items) * 3)),
        "open_findings": len(items),
        "critical_findings": sev_counter.get("critical", 0),
        "high_findings": sev_counter.get("high", 0),
        "severity_counts": dict(sev_counter),
        "category_counts": dict(cat_counter),
        "top_devices": top_devices,
        "recent_runs": trend,
        "recent_findings": items[:8],
        "total_devices": len(devices),
        "non_compliant_devices": sum(1 for row in devices if row["compliance"] == "non-compliant"),
    }


def list_findings(
    *,
    severity: str | None = None,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if severity and severity != "all":
        where.append("cf.severity = ?")
        params.append(severity)
    if status and status != "all":
        where.append("cf.status = ?")
        params.append(status)
    if category and category != "all":
        where.append("cf.category = ?")
        params.append(category)
    if search and search.strip():
        q = f"%{search.strip()}%"
        where.append("(cf.title LIKE ? OR d.hostname LIKE ? OR d.ip_address LIKE ? OR cf.rule_id LIKE ?)")
        params.extend([q, q, q, q])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    offset = (page - 1) * page_size

    conn = get_db_connection()
    try:
        total_row = conn.execute(
            f'''
            SELECT COUNT(*) AS count
            FROM compliance_findings cf
            LEFT JOIN devices d ON d.id = cf.device_id
            {where_sql}
            ''',
            tuple(params),
        ).fetchone()
        total = int(total_row["count"]) if total_row else 0
        rows = conn.execute(
            f'''
            SELECT cf.*, d.hostname, d.ip_address, d.site, d.role, d.platform
            FROM compliance_findings cf
            LEFT JOIN devices d ON d.id = cf.device_id
            {where_sql}
            ORDER BY
                CASE cf.severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                cf.last_seen_at DESC
            LIMIT ? OFFSET ?
            ''',
            tuple([*params, page_size, offset]),
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    finally:
        conn.close()


def get_finding(finding_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''
            SELECT cf.*, d.hostname, d.ip_address, d.site, d.role, d.platform
            FROM compliance_findings cf
            LEFT JOIN devices d ON d.id = cf.device_id
            WHERE cf.id = ?
            ''',
            (finding_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_finding(
    finding_id: str,
    *,
    status: str | None = None,
    owner: str | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM compliance_findings WHERE id = ?", (finding_id,)).fetchone()
        if not row:
            return None
        current = dict(row)
        next_status = status or current.get("status") or "open"
        resolved_at = utc_now_iso() if next_status == "resolved" else None
        conn.execute(
            '''
            UPDATE compliance_findings
            SET status = ?, owner = ?, note = ?, resolved_at = ?
            WHERE id = ?
            ''',
            (
                next_status,
                owner if owner is not None else current.get("owner", ""),
                note if note is not None else current.get("note", ""),
                resolved_at,
                finding_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_finding(finding_id)
