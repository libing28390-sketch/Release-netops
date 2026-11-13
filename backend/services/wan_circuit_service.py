"""Tenant-scoped WAN circuit configuration and SLA policy services.

``wan_links.id`` remains the root identity used by the existing collectors and
alert/group readers.  This module stores the A/Z circuit model around that
identity and deliberately does not infer path SLA from interface state.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.audit_service import log_audit_event
from services.wan_link_service import _apply_contract_utilization, _ensure_alert_rules, _measurement_scope, _num, _row_dict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


_SLA_POLICY_DEFAULTS: dict[str, Any] = {
    "availability_target_pct": 99.9,
    "minimum_coverage_pct": 99.0,
    "minimum_rtt_samples": 100,
    "minimum_loss_packets": 1000,
    "availability_rule": "any_success",
    "timezone": "Asia/Shanghai",
    "latency_target_ms": None,
    "loss_target_pct": None,
    "maintenance_excluded": False,
}


def _contract_bps(payload: dict[str, Any], direction: str) -> int:
    raw_bps = payload.get(f"contracted_{direction}_bps")
    if raw_bps in (None, ""):
        raw_mbps = payload.get(f"contracted_{direction}_mbps")
        number = _num(raw_mbps)
        if number is not None:
            raw_bps = number * 1_000_000
    number = _num(raw_bps)
    if number is None or number <= 0:
        raise ValueError(f"contracted {direction} bandwidth must be greater than zero")
    return int(round(number))


def _site_for_device(conn, device: dict[str, Any]) -> dict[str, Any] | None:
    site_id = _text(device.get("site_id"))
    site_name = _text(device.get("site"))
    if site_id:
        return _row_dict(conn.execute("SELECT id, site_name, timezone, tenant_id FROM sites WHERE id = ?", (site_id,)).fetchone())
    if site_name:
        return _row_dict(conn.execute("SELECT id, site_name, timezone, tenant_id FROM sites WHERE id = ? OR site_name = ? LIMIT 1", (site_name, site_name)).fetchone())
    return None


def _validate_site(conn, site_id: str, tenant_id: str) -> dict[str, Any] | None:
    if not site_id:
        return None
    site = _row_dict(conn.execute("SELECT id, site_name, timezone, tenant_id FROM sites WHERE id = ?", (site_id,)).fetchone())
    if not site:
        raise ValueError("Selected site does not exist")
    site_tenant = _text(site.get("tenant_id")) or "tenant-default"
    if site_tenant != tenant_id:
        raise ValueError("Selected site belongs to another tenant")
    return site


def _validate_endpoint(conn, endpoint: dict[str, Any], *, side: str, tenant_id: str) -> dict[str, Any]:
    endpoint_type = _text(endpoint.get("endpoint_type") or "managed").lower()
    if endpoint_type not in {"managed", "unmanaged"}:
        raise ValueError("endpoint_type must be managed or unmanaged")
    # Missing measurement metadata is not evidence that a physical interface
    # is dedicated to this circuit.  Require an explicit choice before
    # publishing contract utilization or capacity conclusions.
    default_scope = "shared_interface" if side == "A" else "dedicated"
    scope = _text(endpoint.get("measurement_scope") or default_scope).lower()
    if scope not in {"dedicated", "shared_interface"}:
        raise ValueError("measurement_scope must be dedicated or shared_interface")
    orientation = _text(endpoint.get("counter_orientation") or "normal").lower()
    if orientation not in {"normal", "reversed"}:
        raise ValueError("counter_orientation must be normal or reversed")
    site_id = _text(endpoint.get("site_id"))
    site = _validate_site(conn, site_id, tenant_id) if site_id else None
    device_id = _text(endpoint.get("device_id")) or None
    interface_id = _text(endpoint.get("interface_id")) or None
    if_index = endpoint.get("if_index")
    device = None
    interface = None
    if side == "A" and endpoint_type != "managed":
        raise ValueError("A endpoint must be managed")
    if endpoint_type == "managed":
        if not device_id or not interface_id:
            raise ValueError(f"{side} managed endpoint requires device_id and interface_id")
        device = _row_dict(conn.execute("SELECT id, tenant_id, site_id, site, hostname FROM devices WHERE id = ?", (device_id,)).fetchone())
        if not device:
            raise ValueError(f"{side} endpoint device does not exist")
        device_tenant = _text(device.get("tenant_id")) or "tenant-default"
        if device_tenant != tenant_id:
            raise ValueError(f"{side} endpoint device belongs to another tenant")
        interface = _row_dict(conn.execute("SELECT id, device_id, interface_name, if_index FROM interfaces WHERE id = ? AND device_id = ?", (interface_id, device_id)).fetchone())
        if not interface:
            raise ValueError(f"{side} endpoint interface does not belong to selected device")
        canonical_if_index = interface.get("if_index")
        if canonical_if_index is None:
            raise ValueError(f"{side} endpoint interface has no ifIndex")
        if if_index not in (None, "") and int(if_index) != int(canonical_if_index):
            raise ValueError(f"{side} endpoint ifIndex does not match CMDB")
        if_index = int(canonical_if_index)
        device_site_id = _text(device.get("site_id"))
        if site_id and device_site_id and site_id != device_site_id:
            raise ValueError(f"{side} endpoint device does not belong to selected site")
        if not site_id:
            device_site = _site_for_device(conn, device)
            site_id = _text((device_site or {}).get("id"))
            site = device_site
        if site and (_text(site.get("tenant_id")) or "tenant-default") != tenant_id:
            raise ValueError(f"{side} endpoint site belongs to another tenant")
    elif device_id or interface_id or if_index not in (None, ""):
        raise ValueError(f"{side} unmanaged endpoint cannot contain a CMDB interface")
    return {
        "side": side,
        "endpoint_type": endpoint_type,
        "tenant_id": tenant_id,
        "site_id": site_id,
        "device_id": device_id,
        "interface_id": interface_id,
        "if_index": int(if_index) if if_index not in (None, "") else None,
        "site_name": _text(endpoint.get("site_name") or (site or {}).get("site_name")),
        "endpoint_name": _text(endpoint.get("endpoint_name") or (interface or {}).get("interface_name") or (device or {}).get("hostname")),
        "counter_orientation": orientation,
        "measurement_scope": scope,
    }


_ENDPOINT_IDENTITY_FIELDS = (
    "endpoint_type", "site_id", "device_id", "interface_id", "if_index",
    "site_name", "endpoint_name", "counter_orientation", "measurement_scope",
)


def _endpoint_identity(endpoint: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(endpoint.get(key) if endpoint.get(key) not in (None, "") else None for key in _ENDPOINT_IDENTITY_FIELDS)


def _write_endpoint_history(
    conn,
    *,
    link_id: str,
    tenant_id: str,
    endpoint: dict[str, Any],
    endpoint_id: str,
    version: int,
    actor_id: str,
    valid_from: str,
) -> None:
    snapshot = {
        "id": endpoint_id,
        "link_id": link_id,
        "tenant_id": tenant_id,
        "side": endpoint["side"],
        "endpoint_version": version,
        **{key: endpoint.get(key) for key in _ENDPOINT_IDENTITY_FIELDS},
    }
    conn.execute(
        """INSERT INTO wan_link_endpoint_history (
               id, link_id, tenant_id, side, endpoint_version, endpoint_type,
               site_id, device_id, interface_id, if_index, site_name, endpoint_name,
               counter_orientation, measurement_scope, valid_from, valid_to,
               changed_by, snapshot
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?::jsonb)
           ON CONFLICT (link_id, side, endpoint_version) DO NOTHING""",
        (
            f"wan-endpoint-history-{uuid.uuid4().hex}", link_id, tenant_id,
            endpoint["side"], version, endpoint["endpoint_type"], endpoint["site_id"],
            endpoint["device_id"], endpoint["interface_id"], endpoint["if_index"],
            endpoint["site_name"], endpoint["endpoint_name"],
            endpoint["counter_orientation"], endpoint["measurement_scope"],
            valid_from, _text(actor_id), json.dumps(snapshot, ensure_ascii=False),
        ),
    )


def _persist_endpoint_versions(
    conn,
    *,
    link_id: str,
    tenant_id: str,
    endpoints: list[dict[str, Any]],
    actor_id: str,
    now: str,
) -> None:
    """Keep a current endpoint projection and append history only on change."""
    current_rows = {
        _text(row["side"]): dict(row)
        for row in conn.execute(
            "SELECT * FROM wan_link_endpoints WHERE link_id = ? FOR UPDATE",
            (link_id,),
        ).fetchall()
    }
    for endpoint in endpoints:
        side = endpoint["side"]
        current = current_rows.get(side)
        changed = current is None or _endpoint_identity(current) != _endpoint_identity(endpoint)
        if not changed:
            continue

        if current:
            previous_version = int(current.get("binding_version") or 1)
            version = previous_version + 1
            conn.execute(
                """UPDATE wan_link_endpoint_history
                      SET valid_to = ?
                    WHERE link_id = ? AND side = ? AND endpoint_version = ? AND valid_to IS NULL""",
                (now, link_id, side, previous_version),
            )
            endpoint_id = _text(current.get("id")) or str(uuid.uuid4())
            conn.execute(
                """UPDATE wan_link_endpoints
                      SET endpoint_type = ?, tenant_id = ?, site_id = ?, device_id = ?,
                          interface_id = ?, if_index = ?, site_name = ?, endpoint_name = ?,
                          counter_orientation = ?, measurement_scope = ?, binding_version = ?,
                          updated_at = ?
                    WHERE link_id = ? AND side = ?""",
                (
                    endpoint["endpoint_type"], tenant_id, endpoint["site_id"], endpoint["device_id"],
                    endpoint["interface_id"], endpoint["if_index"], endpoint["site_name"],
                    endpoint["endpoint_name"], endpoint["counter_orientation"],
                    endpoint["measurement_scope"], version, now, link_id, side,
                ),
            )
        else:
            version = 1
            endpoint_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO wan_link_endpoints (
                       id, link_id, side, endpoint_type, tenant_id, site_id, device_id,
                       interface_id, if_index, site_name, endpoint_name,
                       counter_orientation, measurement_scope, created_at, updated_at,
                       binding_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    endpoint_id, link_id, side, endpoint["endpoint_type"], tenant_id,
                    endpoint["site_id"], endpoint["device_id"], endpoint["interface_id"],
                    endpoint["if_index"], endpoint["site_name"], endpoint["endpoint_name"],
                    endpoint["counter_orientation"], endpoint["measurement_scope"], now, now,
                    version,
                ),
            )
        _write_endpoint_history(
            conn,
            link_id=link_id,
            tenant_id=tenant_id,
            endpoint=endpoint,
            endpoint_id=endpoint_id,
            version=version,
            actor_id=actor_id,
            valid_from=now,
        )


def list_wan_circuit_endpoint_history(link_id: str, *, tenant_id: str | None) -> list[dict[str, Any]] | None:
    conn = get_db_connection()
    try:
        link = _row_dict(conn.execute("SELECT tenant_id FROM wan_links WHERE id = ?", (link_id,)).fetchone())
        if not link or (tenant_id and _text(link.get("tenant_id")) != tenant_id):
            return None
        rows = conn.execute(
            """SELECT side, endpoint_version, endpoint_type, site_id, device_id,
                      interface_id, if_index, site_name, endpoint_name,
                      counter_orientation, measurement_scope, valid_from, valid_to,
                      changed_by, snapshot
                 FROM wan_link_endpoint_history
                WHERE link_id = ? AND tenant_id = ?
                ORDER BY side, endpoint_version DESC""",
            (link_id, _text(link.get("tenant_id"))),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["snapshot"] = _json_object(item.get("snapshot"))
            result.append(item)
        return result
    finally:
        conn.close()


def _detail(conn, link_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT l.*, c.sampled_at AS current_sampled_at, c.download_bps AS current_download_bps,
                      c.upload_bps AS current_upload_bps, c.download_util_pct AS current_download_util_pct,
                      c.upload_util_pct AS current_upload_util_pct, c.admin_status AS current_admin_status,
                      c.oper_status AS current_oper_status, c.collection_status AS current_collection_status,
                      c.health_status AS current_health_status, c.active_alert_count AS current_active_alert_count,
                      c.last_success_at AS current_last_success_at
                 FROM wan_links l LEFT JOIN wan_link_current_status c ON c.link_id = l.id
                WHERE l.id = ?""",
        (link_id,),
    ).fetchone()
    item = _row_dict(row)
    if not item:
        return None
    current = {
        key.removeprefix("current_"): value
        for key, value in item.items()
        if key.startswith("current_") and value is not None
    }
    for key in list(item):
        if key.startswith("current_"):
            item.pop(key, None)
    if current:
        current["contracted_download_bps"] = item.get("contracted_download_bps")
        current["contracted_upload_bps"] = item.get("contracted_upload_bps")
    item["endpoints"] = [
        dict(row)
        for row in conn.execute(
            "SELECT id, side, endpoint_type, tenant_id, site_id, device_id, interface_id, if_index, site_name, endpoint_name, counter_orientation, measurement_scope, binding_version, created_at, updated_at FROM wan_link_endpoints WHERE link_id = ? ORDER BY side",
            (link_id,),
        ).fetchall()
    ]
    if current:
        current["endpoints"] = item["endpoints"]
        item["current"] = _apply_contract_utilization(current)
    else:
        item["current"] = None
    return _apply_contract_utilization(item)


def save_wan_circuit(payload: dict, *, tenant_id: str, actor_id: str, link_id: str | None = None) -> dict:
    """Create or update a circuit, atomically persisting A/Z and contract history."""
    conn = get_db_connection()
    now = _now()
    try:
        requested_tenant = _text(tenant_id)
        existing = None
        if link_id or payload.get("id"):
            link_id = _text(link_id or payload.get("id"))
            existing = _row_dict(conn.execute("SELECT * FROM wan_links WHERE id = ? FOR UPDATE", (link_id,)).fetchone())
            if not existing:
                raise ValueError("WAN circuit not found")
        raw_endpoints = payload.get("endpoints")
        if not raw_endpoints:
            raw_endpoints = [{
                "side": "A", "endpoint_type": "managed", "site_id": payload.get("site_id"),
                "device_id": payload.get("device_id"), "interface_id": payload.get("interface_id"),
                "if_index": payload.get("if_index"), "site_name": payload.get("site_name"),
                "counter_orientation": payload.get("direction_mode", "normal"), "measurement_scope": "shared_interface",
            }, {"side": "Z", "endpoint_type": "unmanaged", "site_id": payload.get("site_id"), "site_name": payload.get("site_name")}]
        if not isinstance(raw_endpoints, list):
            raise ValueError("endpoints must be a list")
        by_side = {_text(item.get("side")).upper(): item for item in raw_endpoints if isinstance(item, dict)}
        if set(by_side) != {"A", "Z"}:
            raise ValueError("endpoints must contain exactly one A and one Z endpoint")

        # An empty tenant is only an administrator convenience: derive it from
        # the trusted A-side device before checking any selected asset.
        a_device_id = _text(by_side["A"].get("device_id"))
        a_device = _row_dict(conn.execute("SELECT id, tenant_id FROM devices WHERE id = ?", (a_device_id,)).fetchone()) if a_device_id else None
        trusted_a_tenant = _text((a_device or {}).get("tenant_id")) or "tenant-default"
        effective_tenant = requested_tenant or trusted_a_tenant
        if existing and _text(existing.get("tenant_id")) != effective_tenant:
            raise ValueError("WAN circuit belongs to another tenant")
        endpoints = [_validate_endpoint(conn, by_side[side], side=side, tenant_id=effective_tenant) for side in ("A", "Z")]
        a_endpoint = endpoints[0]
        previous_a_endpoint = _row_dict(conn.execute(
            "SELECT * FROM wan_link_endpoints WHERE link_id = ? AND side = 'A' FOR UPDATE",
            (link_id or _text(payload.get("id")),),
        ).fetchone()) if existing else None
        measurement_changed = previous_a_endpoint is None or any(
            previous_a_endpoint.get(key) != a_endpoint.get(key)
            for key in ("endpoint_type", "site_id", "device_id", "interface_id", "if_index", "counter_orientation", "measurement_scope")
        )
        if _text(a_endpoint.get("tenant_id")) != effective_tenant:
            raise ValueError("A endpoint tenant does not match circuit tenant")
        if existing:
            expected = payload.get("expected_version", payload.get("expected_configuration_version", payload.get("configuration_version")))
            if expected not in (None, "") and int(expected) != int(existing.get("configuration_version") or 1):
                raise ValueError("configuration_version_conflict")
        version = int(existing.get("configuration_version") or 0) + 1 if existing else 1
        site_id = _text(payload.get("site_id") or a_endpoint.get("site_id"))
        site = _validate_site(conn, site_id, effective_tenant) if site_id else None
        down_bps = _contract_bps(payload, "download")
        up_bps = _contract_bps(payload, "upload")
        link_id = link_id or _text(payload.get("id")) or f"wan-link-{uuid.uuid4().hex}"
        site_name = _text(payload.get("site_name") or (site or {}).get("site_name") or a_endpoint.get("site_name"))
        values = {
            "id": link_id, "link_name": _text(payload.get("link_name")), "site_id": site_id,
            "site_name": site_name, "device_id": a_endpoint["device_id"], "interface_id": a_endpoint["interface_id"],
            "interface_name": a_endpoint["endpoint_name"], "if_index": a_endpoint["if_index"],
            "provider": _text(payload.get("provider")), "circuit_number": _text(payload.get("circuit_number")),
            "public_ip": _text(payload.get("public_ip")), "link_type": _text(payload.get("link_type") or "Internet"),
            "link_role": _text(payload.get("link_role") or "standalone"), "direction_mode": _text(payload.get("direction_mode") or a_endpoint["counter_orientation"] or "normal"),
            "contracted_download_bps": down_bps, "contracted_upload_bps": up_bps,
            "collection_interval_sec": int(payload.get("collection_interval_sec") or 60),
            "timezone": _text(payload.get("timezone") or (site or {}).get("timezone") or "Asia/Shanghai"),
            "enabled": bool(payload.get("enabled", True)), "maintenance_window": _text(payload.get("maintenance_window")),
            "notes": _text(payload.get("notes")), "tenant_id": effective_tenant,
            "configuration_version": version, "created_at": _text(existing.get("created_at")) if existing else now, "updated_at": now,
        }
        if not values["link_name"]:
            raise ValueError("link_name is required")
        if values["link_role"] not in {"standalone", "primary", "backup", "load_balanced"}:
            raise ValueError("link_role must be standalone, primary, backup or load_balanced")
        if values["direction_mode"] not in {"normal", "reversed"}:
            raise ValueError("direction_mode must be normal or reversed")
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column not in {"id", "created_at"})
        conn.execute(f"INSERT INTO wan_links ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}", tuple(values[column] for column in columns))
        _persist_endpoint_versions(
            conn, link_id=link_id, tenant_id=effective_tenant, endpoints=endpoints,
            actor_id=actor_id, now=now,
        )
        contract_changed = not existing or any(existing.get(key) != values[key] for key in ("contracted_download_bps", "contracted_upload_bps", "provider", "circuit_number"))
        if contract_changed:
            snapshot = {key: values[key] for key in ("contracted_download_bps", "contracted_upload_bps", "provider", "circuit_number")}
            conn.execute(
                """INSERT INTO wan_link_contract_history (id, link_id, tenant_id, configuration_version, contracted_download_bps, contracted_upload_bps, provider, circuit_number, effective_at, changed_by, snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb)""",
                (str(uuid.uuid4()), link_id, effective_tenant, version, down_bps, up_bps, values["provider"], values["circuit_number"], now, _text(actor_id), json.dumps(snapshot)),
            )
        _ensure_alert_rules(conn, values, now)
        if measurement_changed:
            # Rates from the old interface/scope cannot be reused as the new
            # endpoint's current measurement. The collector will establish a
            # fresh counter baseline under the new binding version.
            conn.execute(
                """UPDATE wan_link_current_status
                      SET download_bps = NULL, upload_bps = NULL,
                          download_util_pct = NULL, upload_util_pct = NULL,
                          health_status = 'unknown', updated_at = ?
                    WHERE link_id = ?""",
                (now, link_id),
            )
        elif _measurement_scope({"endpoints": endpoints}) == "shared_interface":
            conn.execute(
                "UPDATE wan_link_current_status SET download_util_pct = NULL, upload_util_pct = NULL, health_status = CASE WHEN oper_status = 'down' THEN 'unavailable' ELSE 'unknown' END, updated_at = ? WHERE link_id = ?",
                (now, link_id),
            )
        else:
            conn.execute(
                "UPDATE wan_link_current_status SET download_util_pct = CASE WHEN download_bps IS NULL THEN NULL ELSE download_bps * 100.0 / NULLIF(?, 0) END, upload_util_pct = CASE WHEN upload_bps IS NULL THEN NULL ELSE upload_bps * 100.0 / NULLIF(?, 0) END, updated_at = ? WHERE link_id = ?",
                (down_bps, up_bps, now, link_id),
            )
        conn.commit()
        return _detail(conn, link_id) or values
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_wan_circuits(*, tenant_id: str | None, page: int, page_size: int, keyword: str = "", site_id: str = "", site_ids: tuple[str, ...] | None = None, provider: str = "", health_status: str = "", link_role: str = "", group_id: str = "") -> dict:
    conn = get_db_connection()
    try:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        if site_ids is not None and len(site_ids) == 0:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "summary": {"total": 0, "healthy": 0, "risky": 0, "active_alerts": 0}}
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("l.tenant_id = ?")
            params.append(tenant_id)
        if site_ids is not None:
            normalized_sites = tuple(_text(value) for value in site_ids if _text(value))
            if not normalized_sites:
                return {"items": [], "total": 0, "page": page, "page_size": page_size, "summary": {"total": 0, "healthy": 0, "risky": 0, "active_alerts": 0}}
            clauses.append("l.site_id IN (" + ",".join("?" for _ in normalized_sites) + ")")
            params.extend(normalized_sites)
        elif site_id:
            clauses.append("l.site_id = ?")
            params.append(site_id)
        if provider:
            clauses.append("l.provider = ?")
            params.append(provider)
        if health_status:
            clauses.append("COALESCE(c.health_status, 'unknown') = ?")
            params.append(health_status)
        if link_role:
            if link_role not in {"standalone", "primary", "backup", "load_balanced"}:
                raise ValueError("link_role must be standalone, primary, backup or load_balanced")
            clauses.append("l.link_role = ?")
            params.append(link_role)
        if group_id:
            clauses.append("EXISTS (SELECT 1 FROM wan_link_group_members gm WHERE gm.link_id = l.id AND gm.group_id = ?)")
            params.append(group_id)
        if keyword:
            token = f"%{keyword}%"
            clauses.append("(l.link_name LIKE ? OR l.provider LIKE ? OR l.circuit_number LIKE ? OR l.site_name LIKE ?)")
            params.extend([token] * 4)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        total = int(conn.execute(f"SELECT COUNT(*) FROM wan_links l {where}", tuple(params)).fetchone()[0])
        rows = conn.execute(
            f"""SELECT l.*, c.health_status, c.oper_status, c.collection_status, c.active_alert_count, c.sampled_at
                   FROM wan_links l LEFT JOIN wan_link_current_status c ON c.link_id = l.id
                  {where} ORDER BY l.site_name, l.link_name LIMIT ? OFFSET ?""",
            tuple(params + [page_size, (page - 1) * page_size]),
        ).fetchall()
        items = [dict(row) for row in rows]
        if items:
            ids = [str(item["id"]) for item in items]
            endpoints = conn.execute(
                """SELECT link_id, id, side, endpoint_type, tenant_id, site_id, device_id,
                          interface_id, if_index, site_name, endpoint_name,
                          counter_orientation, measurement_scope, binding_version,
                          created_at, updated_at
                     FROM wan_link_endpoints
                    WHERE link_id IN (""" + ",".join("?" for _ in ids) + ") ORDER BY link_id, side",
                tuple(ids),
            ).fetchall()
            endpoints_by_link: dict[str, list[dict[str, Any]]] = {}
            for endpoint_row in endpoints:
                endpoint = dict(endpoint_row)
                endpoints_by_link.setdefault(str(endpoint["link_id"]), []).append(endpoint)
            for item in items:
                item["endpoints"] = endpoints_by_link.get(str(item["id"]), [])
                if _measurement_scope(item) == "shared_interface" and str(item.get("oper_status") or "").lower() != "down":
                    item["health_status"] = "unknown"
                item.update(_apply_contract_utilization(item))
        summary_row = conn.execute(f"""SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN COALESCE(a.measurement_scope, 'shared_interface') = 'dedicated' AND c.health_status = 'healthy' THEN 1 ELSE 0 END), 0) AS healthy,
                       COALESCE(SUM(CASE WHEN c.oper_status = 'down' OR (COALESCE(a.measurement_scope, 'shared_interface') = 'dedicated' AND c.health_status = 'critical') THEN 1 ELSE 0 END), 0) AS risky,
                       COALESCE(SUM(c.active_alert_count), 0) AS active_alerts
                  FROM wan_links l
                  LEFT JOIN wan_link_current_status c ON c.link_id = l.id
                  LEFT JOIN wan_link_endpoints a ON a.link_id = l.id AND a.side = 'A'
                  {where}""", tuple(params)).fetchone()
        return {"items": items, "total": total, "page": page, "page_size": page_size, "summary": dict(summary_row or {})}
    finally:
        conn.close()


def get_wan_circuit(link_id: str, *, tenant_id: str | None) -> dict | None:
    conn = get_db_connection()
    try:
        if tenant_id:
            row = conn.execute("SELECT id FROM wan_links WHERE id = ? AND tenant_id = ?", (link_id, tenant_id)).fetchone()
            if not row:
                return None
        return _detail(conn, link_id)
    finally:
        conn.close()


def list_wan_link_options_scoped(*, tenant_id: str = "", site_id: str = "", site_ids: tuple[str, ...] | None = None, device_id: str = "") -> dict[str, Any]:
    """Return CMDB options after applying the same tenant/resource scope as circuits."""
    from services.wan_link_service import list_wan_link_options

    return list_wan_link_options(tenant_id=tenant_id, site_id=site_id, site_ids=site_ids, device_id=device_id)


def upsert_wan_circuit_sla_policy(link_id: str, payload: dict, *, tenant_id: str, actor_id: str) -> dict:
    conn = get_db_connection()
    now = _now()
    try:
        link = _row_dict(conn.execute("SELECT id, tenant_id FROM wan_links WHERE id = ? FOR UPDATE", (link_id,)).fetchone())
        if not link:
            raise ValueError("WAN circuit not found")
        link_tenant = _text(link.get("tenant_id")) or "tenant-default"
        effective_tenant = _text(tenant_id) or link_tenant
        if effective_tenant != link_tenant:
            raise ValueError("WAN circuit belongs to another tenant")
        current = _row_dict(conn.execute("SELECT * FROM wan_link_sla_policies WHERE link_id = ? FOR UPDATE", (link_id,)).fetchone())
        expected = payload.get("expected_version", payload.get("expected_policy_version", payload.get("policy_version")))
        if current and expected in (None, ""):
            raise ValueError("policy_version_required")
        current_version = int(current.get("policy_version") or 0) if current else 0
        if expected not in (None, "") and int(expected) != current_version:
            raise ValueError("policy_version_conflict")
        policy = dict(_SLA_POLICY_DEFAULTS)
        if current:
            policy.update(_json_object(current.get("policy_json")))
        policy.update({key: value for key, value in payload.items() if key not in {"policy_version", "expected_policy_version", "expected_version"}})
        try:
            policy["availability_target_pct"] = float(policy["availability_target_pct"])
            policy["minimum_coverage_pct"] = float(policy["minimum_coverage_pct"])
            policy["minimum_rtt_samples"] = int(policy["minimum_rtt_samples"])
            policy["minimum_loss_packets"] = int(policy["minimum_loss_packets"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid SLA policy numeric value") from exc
        if not 0 <= policy["availability_target_pct"] <= 100 or not 0 <= policy["minimum_coverage_pct"] <= 100:
            raise ValueError("SLA policy percentages must be between 0 and 100")
        if policy["minimum_rtt_samples"] < 0 or policy["minimum_loss_packets"] < 0:
            raise ValueError("SLA policy minimum samples must be non-negative")
        if policy.get("availability_rule") not in {"any_success", "all_success"}:
            raise ValueError("availability_rule must be any_success or all_success")
        for optional_key in ("latency_target_ms", "loss_target_pct"):
            if policy.get(optional_key) not in (None, ""):
                try:
                    policy[optional_key] = float(policy[optional_key])
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid SLA policy {optional_key}") from exc
        policy["maintenance_excluded"] = bool(policy.get("maintenance_excluded", False))
        version = current_version + 1
        policy_json = json.dumps(policy, ensure_ascii=False)
        conn.execute(
            """INSERT INTO wan_link_sla_policies (link_id, tenant_id, policy_version, policy_json, updated_by, updated_at)
               VALUES (?, ?, ?, ?::jsonb, ?, ?)
               ON CONFLICT(link_id) DO UPDATE SET tenant_id = excluded.tenant_id, policy_version = excluded.policy_version, policy_json = excluded.policy_json, updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
            (link_id, effective_tenant, version, policy_json, _text(actor_id), now),
        )
        conn.execute(
            "INSERT INTO wan_link_sla_policy_history (id, link_id, tenant_id, policy_version, policy_json, changed_by, created_at) VALUES (?, ?, ?, ?, ?::jsonb, ?, ?)",
            (str(uuid.uuid4()), link_id, effective_tenant, version, policy_json, _text(actor_id), now),
        )
        conn.commit()
        return {"link_id": link_id, "tenant_id": effective_tenant, "policy_version": version, "policy": policy, "updated_by": _text(actor_id), "updated_at": now}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_wan_circuit_sla(link_id: str, *, tenant_id: str | None, window: str = "24h") -> dict | None:
    conn = get_db_connection()
    try:
        link = _row_dict(conn.execute("SELECT id, tenant_id FROM wan_links WHERE id = ?", (link_id,)).fetchone())
        if not link or (tenant_id and _text(link.get("tenant_id")) != tenant_id):
            return None
        endpoints = [dict(row) for row in conn.execute("SELECT side, endpoint_type, measurement_scope, site_id, device_id, interface_id FROM wan_link_endpoints WHERE link_id = ? ORDER BY side", (link_id,)).fetchall()]
        shared = any(row.get("side") == "A" and row.get("measurement_scope") == "shared_interface" for row in endpoints)
        reason = "shared_interface_not_path_evidence" if shared else "path_evidence_unavailable"
        policy_row = _row_dict(conn.execute("SELECT policy_version, policy_json, updated_by, updated_at FROM wan_link_sla_policies WHERE link_id = ?", (link_id,)).fetchone())
        policy = _json_object(policy_row.get("policy_json")) if policy_row else None
        return {
            "link_id": link_id, "tenant_id": _text(link.get("tenant_id")), "window": _text(window) or "24h",
            "status": "insufficient_data", "reason_code": reason,
            "availability_pct": None, "latency_ms": None, "packet_loss_pct": None, "jitter_ms": None,
            "availability": {"value": None, "lower_bound": None, "upper_bound": None},
            "coverage_pct": None, "slots": 0, "window_start": None, "window_end": None,
            "reason": reason, "evidence": {"source": None, "sample_count": 0, "path_proven": False},
            "policy_version": int(policy_row["policy_version"]) if policy_row else None, "policy": policy,
        }
    finally:
        conn.close()


def replace_wan_circuit_endpoints(link_id: str, endpoints: list[dict], *, expected_version: int, tenant_id: str, actor_id: str) -> dict:
    """Replace both A/Z endpoints with an optimistic configuration update."""
    conn = get_db_connection()
    now = _now()
    try:
        link = _row_dict(conn.execute("SELECT * FROM wan_links WHERE id = ? FOR UPDATE", (link_id,)).fetchone())
        if not link:
            raise ValueError("WAN circuit not found")
        effective_tenant = _text(tenant_id) or _text(link.get("tenant_id"))
        if effective_tenant != _text(link.get("tenant_id")):
            raise ValueError("WAN circuit belongs to another tenant")
        if int(expected_version) != int(link.get("configuration_version") or 1):
            raise ValueError("configuration_version_conflict")
        if not isinstance(endpoints, list):
            raise ValueError("endpoints must be a list")
        by_side = {_text(item.get("side")).upper(): item for item in endpoints if isinstance(item, dict)}
        if set(by_side) != {"A", "Z"}:
            raise ValueError("endpoints must contain exactly one A and one Z endpoint")
        validated = [_validate_endpoint(conn, by_side[side], side=side, tenant_id=effective_tenant) for side in ("A", "Z")]
        a_endpoint = validated[0]
        next_version = int(link.get("configuration_version") or 1) + 1
        conn.execute(
            """UPDATE wan_links
                  SET device_id = ?, interface_id = ?, interface_name = ?, if_index = ?,
                      site_id = ?, site_name = ?, direction_mode = ?,
                      configuration_version = ?, updated_at = ?
                WHERE id = ?""",
            (a_endpoint["device_id"], a_endpoint["interface_id"], a_endpoint["endpoint_name"], a_endpoint["if_index"], a_endpoint["site_id"], a_endpoint["site_name"], a_endpoint["counter_orientation"], next_version, now, link_id),
        )
        _persist_endpoint_versions(
            conn, link_id=link_id, tenant_id=effective_tenant, endpoints=validated,
            actor_id=actor_id, now=now,
        )
        log_audit_event(
            event_type="wan_circuit_endpoints_replaced", category="monitoring", severity="info", status="completed",
            summary="WAN circuit endpoints replaced", actor_id=actor_id, target_type="wan_link", target_id=link_id,
            details={"tenant_id": effective_tenant, "configuration_version": next_version, "sides": ["A", "Z"]},
            before={"configuration_version": link.get("configuration_version")}, after={"configuration_version": next_version}, conn=conn,
        )
        conn.commit()
        return _detail(conn, link_id) or {"id": link_id, "configuration_version": next_version}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def archive_wan_circuit(link_id: str, *, tenant_id: str, actor_id: str) -> dict:
    """Disable a circuit while retaining its samples, history and audit trail."""
    conn = get_db_connection()
    now = _now()
    try:
        link = _row_dict(conn.execute("SELECT * FROM wan_links WHERE id = ? FOR UPDATE", (link_id,)).fetchone())
        if not link:
            raise ValueError("WAN circuit not found")
        effective_tenant = _text(tenant_id) or _text(link.get("tenant_id"))
        if effective_tenant != _text(link.get("tenant_id")):
            raise ValueError("WAN circuit belongs to another tenant")
        if bool(link.get("enabled")):
            next_version = int(link.get("configuration_version") or 1) + 1
            conn.execute("UPDATE wan_links SET enabled = FALSE, configuration_version = ?, updated_at = ? WHERE id = ?", (next_version, now, link_id))
        else:
            next_version = int(link.get("configuration_version") or 1)
        log_audit_event(
            event_type="wan_circuit_archived", category="monitoring", severity="info", status="completed",
            summary="WAN circuit archived", actor_id=actor_id, target_type="wan_link", target_id=link_id,
            details={"tenant_id": effective_tenant, "configuration_version": next_version},
            before={"enabled": bool(link.get("enabled")), "configuration_version": link.get("configuration_version")},
            after={"enabled": False, "configuration_version": next_version}, conn=conn,
        )
        conn.commit()
        return _detail(conn, link_id) or {"id": link_id, "enabled": False, "configuration_version": next_version}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "save_wan_circuit", "list_wan_circuits", "list_wan_link_options_scoped", "get_wan_circuit", "get_wan_circuit_sla",
    "upsert_wan_circuit_sla_policy", "replace_wan_circuit_endpoints", "list_wan_circuit_endpoint_history", "archive_wan_circuit",
]
