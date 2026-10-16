"""Per-circuit probe execution and evidence-first SLA aggregation.

The ordinary outbound probe service is intentionally target-scoped.  This
module adds the missing line identity at the execution boundary: every call is
made for one tenant/link/target/context tuple and every persisted sample keeps
that tuple and the configuration/policy/path versions used for the result.

The platform executor can measure whether a target answered, but it cannot
claim that the answer travelled through a configured WAN circuit without a
fresh, reviewable route proof.  Such samples remain visible as target evidence
while their quality slot is ``unknown`` and the SLA is ``insufficient_data``.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import ipaddress
import json
import logging
import threading
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import _USE_PG, get_db_connection
from services import outbound_probe_service

logger = logging.getLogger(__name__)

SLA_ALGORITHM_VERSION = "wan-sla-v1"
DEFAULT_CADENCE_SECONDS = 60
DEFAULT_MAX_CONCURRENCY = 16
DEFAULT_EVIDENCE_MAX_AGE_SECONDS = 24 * 60 * 60
DEFAULT_SLA_POLICY: dict[str, Any] = {
    "availability_target_pct": 99.9,
    "minimum_coverage_pct": 99.0,
    "availability_rule": "any_success",
}

_PROBE_PURPOSES = {"availability", "quality", "application"}

_RUN_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso(value: datetime | None = None) -> str:
    current = value or _now()
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _probe_purpose(value: Any) -> str:
    """Normalize a binding purpose while keeping old rows availability-safe."""

    purpose = _text(value).lower() or "availability"
    return purpose if purpose in _PROBE_PURPOSES else "availability"


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _digest(value: Any, *, prefix: str = "") -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


def _evidence_version(evidence: dict[str, Any]) -> str:
    return _text(evidence.get("version") or evidence.get("evidence_version")) or _digest(evidence, prefix="ev-")


def _source_ip_matches(expected: Any, actual: Any) -> bool:
    """Compare source addresses without accepting an absent binding."""

    expected_text = _text(expected)
    actual_text = _text(actual)
    if not expected_text or not actual_text:
        return False
    try:
        return ipaddress.ip_address(expected_text).compressed == ipaddress.ip_address(actual_text).compressed
    except ValueError:
        return False


def _require_postgres() -> None:
    if not _USE_PG:
        raise RuntimeError("WAN line probe/SLA service requires PostgreSQL")


def _slot_start(value: datetime | str | None = None) -> datetime:
    parsed = value if isinstance(value, datetime) else _parse_datetime(value)
    current = parsed or _now()
    current = current.astimezone(timezone.utc)
    return current.replace(second=(current.second // DEFAULT_CADENCE_SECONDS) * DEFAULT_CADENCE_SECONDS, microsecond=0)


def _probe_target_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Build the same target shape consumed by ``_probe_target``."""

    return {
        "id": row.get("target_id") or row.get("id"),
        "target_id": row.get("target_id") or row.get("id"),
        "target_name": row.get("target_name") or "",
        "host": row.get("host") or "",
        "port": row.get("port") or 0,
        "probe_type": row.get("probe_type") or "TCP_CONNECT",
        "group_name": row.get("group_name") or "business",
        "url": row.get("url") or "",
        "expected_status_code": row.get("expected_status_code") or 200,
        "expected_keyword": row.get("expected_keyword") or "",
        "timeout_ms": row.get("timeout_ms") or 2000,
    }


def _path_evidence(
    binding: dict[str, Any],
    *,
    context_version: str,
    executor_id: str,
    route_mode: str = "default",
    source_ip: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify route evidence without promoting configuration to proof."""

    current = now or _now()
    evidence = _json_object(binding.get("route_evidence_json") or binding.get("path_evidence"))
    raw_status = _text(
        evidence.get("path_status")
        or evidence.get("status")
        or evidence.get("evidence_status")
    ).lower()
    capability = evidence.get("capability_status") or evidence.get("path_capability")
    if capability is False or _text(capability).lower() in {"unsupported", "not_supported", "false"}:
        return {
            "status": "unsupported",
            "reason_code": "path_capability_unsupported",
            "reason": "Configured executor cannot verify the requested route path",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }
    if raw_status in {"unsupported", "not_supported", "capability_unsupported"}:
        return {
            "status": "unsupported",
            "reason_code": "path_capability_unsupported",
            "reason": "Configured executor cannot verify the requested route path",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }
    if raw_status in {"invalid", "mismatch", "expired"}:
        return {
            "status": "invalid",
            "reason_code": f"path_evidence_{raw_status}",
            "reason": "Stored path evidence does not match the active binding",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }
    if raw_status != "verified":
        reason_code = "path_evidence_unavailable"
        if raw_status in {"source_ip_configured_unverified", "source_configured"}:
            reason_code = "source_ip_only"
        elif raw_status in {"insufficient_default_route", "default_route_unverified"}:
            reason_code = "default_route_unverified"
        return {
            "status": "unverified",
            "reason_code": reason_code,
            "reason": "Target response or source-IP configuration does not prove the circuit path",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }

    verified_at = _parse_datetime(evidence.get("verified_at"))
    expires_at = _parse_datetime(evidence.get("expires_at"))
    if verified_at is None or expires_at is None:
        return {
            "status": "invalid",
            "reason_code": "path_evidence_missing_expiry",
            "reason": "Verified path evidence must include verified_at and expires_at",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }
    if verified_at > current or expires_at <= current:
        return {
            "status": "invalid",
            "reason_code": "path_evidence_expired",
            "reason": "Path evidence is outside its effective time window",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }
    if verified_at < current - timedelta(seconds=DEFAULT_EVIDENCE_MAX_AGE_SECONDS):
        return {
            "status": "invalid",
            "reason_code": "path_evidence_stale",
            "reason": "Path evidence is older than the maximum accepted age",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }

    expected_values = {
        "link_id": _text(binding.get("link_id")),
        "target_id": _text(binding.get("target_id")),
        "executor_id": _text(executor_id),
        "configuration_version": int(binding.get("configuration_version") or 1),
        "context_version": context_version,
    }
    aliases = {
        "link_id": ("link_id", "circuit_id"),
        "target_id": ("target_id", "probe_target_id"),
        "executor_id": ("executor_id", "source_executor"),
        "configuration_version": ("configuration_version", "config_version"),
        "context_version": ("context_version", "binding_version"),
    }
    for key, expected in expected_values.items():
        present_values = [
            evidence.get(name)
            for name in aliases[key]
            if name in evidence and evidence.get(name) not in (None, "")
        ]
        if not present_values:
            return {
                "status": "invalid",
                "reason_code": f"path_evidence_{key}_missing",
                "reason": "Path evidence must identify the active execution context",
                "evidence": evidence,
                "evidence_version": _evidence_version(evidence),
            }
        if any(str(present) != str(expected) for present in present_values):
            return {
                "status": "invalid",
                "reason_code": f"path_evidence_{key}_mismatch",
                "reason": "Path evidence identity does not match the active execution context",
                "evidence": evidence,
                "evidence_version": _evidence_version(evidence),
            }

    normalized_route_mode = _text(route_mode or binding.get("route_mode") or "default").lower()
    configured_source_ip = _text(source_ip or binding.get("source_ip"))
    if normalized_route_mode == "source_ip":
        source_values = [
            evidence.get(name)
            for name in ("source_ip", "source_address", "bound_source_ip", "egress_source_ip")
            if name in evidence and evidence.get(name) not in (None, "")
        ]
        if not configured_source_ip:
            return {
                "status": "invalid",
                "reason_code": "source_ip_missing",
                "reason": "Source-IP route mode requires an active source address",
                "evidence": evidence,
                "evidence_version": _evidence_version(evidence),
            }
        if not source_values:
            return {
                "status": "invalid",
                "reason_code": "path_evidence_source_ip_missing",
                "reason": "Source-IP path evidence must identify the bound source address",
                "evidence": evidence,
                "evidence_version": _evidence_version(evidence),
            }
        if any(not _source_ip_matches(configured_source_ip, value) for value in source_values):
            return {
                "status": "invalid",
                "reason_code": "path_evidence_source_ip_mismatch",
                "reason": "Path evidence source address does not match the active binding",
                "evidence": evidence,
                "evidence_version": _evidence_version(evidence),
            }

    # A status label alone is not a proof.  Accept only a reviewable reference
    # or a concrete route fingerprint/hop record supplied by an executor.
    proof_fields = (
        "evidence_ref",
        "proof_ref",
        "route_fingerprint",
        "routing_table_hash",
        "route",
        "path",
        "hop_chain",
        "next_hop",
        "gateway",
    )
    if not any(evidence.get(key) not in (None, "", [], {}) for key in proof_fields):
        return {
            "status": "unverified",
            "reason_code": "path_proof_missing",
            "reason": "Verified label has no reviewable route/path proof reference",
            "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
        }
    return {
        "status": "verified",
        "reason_code": "path_verified",
        "reason": "Fresh route/path evidence matches the active execution context",
        "evidence": evidence,
            "evidence_version": _evidence_version(evidence),
    }


def _load_executor_id(conn) -> str:
    try:
        row = conn.execute(
            "SELECT id, node_name FROM outbound_probe_nodes WHERE node_name = ? AND enabled IS TRUE LIMIT 1",
            ("platform-server",),
        ).fetchone()
        if row:
            return _text(dict(row).get("id") if hasattr(row, "keys") else row[0]) or "platform-server"
    except Exception:
        logger.debug("Unable to resolve platform probe executor", exc_info=True)
    return "platform-server"


def _load_contexts(conn, *, link_id: str = "", tenant_id: str = "") -> list[dict[str, Any]]:
    clauses = ["b.enabled IS TRUE", "l.enabled IS TRUE", "(t.enabled IS TRUE OR t.is_active IS TRUE)"]
    params: list[Any] = []
    if link_id:
        clauses.append("b.link_id = ?")
        params.append(link_id)
    if tenant_id:
        clauses.append("l.tenant_id = ?")
        params.append(tenant_id)
    rows = conn.execute(
        f"""
        SELECT b.*, l.tenant_id AS link_tenant_id, l.configuration_version,
               l.enabled AS link_enabled, l.link_name,
               t.target_name, t.host, t.port, t.probe_type, t.group_name, t.url,
               t.expected_status_code, t.expected_keyword, t.timeout_ms,
               t.tenant_id AS target_tenant_id,
               p.policy_version, p.policy_json
          FROM wan_probe_bindings b
          JOIN wan_links l ON l.id = b.link_id
          JOIN outbound_probe_targets t ON t.id = b.target_id
          LEFT JOIN wan_link_sla_policies p ON p.link_id = b.link_id
         WHERE {' AND '.join(clauses)}
         ORDER BY b.link_id, b.priority, b.id
        """,
        tuple(params),
    ).fetchall()
    executor_id = _load_executor_id(conn)
    contexts: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        target_tenant = _text(item.get("target_tenant_id")) or "tenant-default"
        link_tenant = _text(item.get("link_tenant_id")) or "tenant-default"
        policy = _json_object(item.get("policy_json"))
        base = {
            "link_id": _text(item.get("link_id")),
            "binding_id": _text(item.get("id")),
            "target_id": _text(item.get("target_id")),
            "tenant_id": link_tenant,
            "target_tenant_id": target_tenant,
            "configuration_version": int(item.get("configuration_version") or 1),
            "policy_version": int(item.get("policy_version") or 0),
            "policy": policy,
            "route_mode": _text(item.get("route_mode") or "default").lower(),
            "source_ip": _text(item.get("source_ip")),
            "updated_at": _text(item.get("updated_at")),
            "route_evidence": _json_object(item.get("route_evidence_json")),
            "target_updated_at": _text(item.get("target_updated_at")),
            "purpose": _probe_purpose(item.get("purpose")),
        }
        # The active context version is derived from the current binding,
        # circuit configuration and target.  Evidence may attest to this
        # version, but it must never be allowed to define it retroactively.
        context_version = _digest(
            {
                **{key: value for key, value in base.items() if key != "route_evidence"},
                "target": {
                    "host": item.get("host"),
                    "port": item.get("port"),
                    "probe_type": item.get("probe_type"),
                    "url": item.get("url"),
                    "expected_status_code": item.get("expected_status_code"),
                    "expected_keyword": item.get("expected_keyword"),
                    "timeout_ms": item.get("timeout_ms"),
                },
            },
            prefix="ctxv-",
        )
        path = _path_evidence(
            item,
            context_version=context_version,
            executor_id=executor_id,
            route_mode=base["route_mode"],
            source_ip=base["source_ip"],
        )
        if base["route_mode"] == "source_ip" and not base["source_ip"]:
            path = {
                "status": "invalid",
                "reason_code": "source_ip_missing",
                "reason": "Source-IP route mode requires a configured source address",
                "evidence": path["evidence"],
                "evidence_version": path["evidence_version"],
            }
        context_id = _digest(
            {
                "link_id": base["link_id"],
                "target_id": base["target_id"],
                "binding_id": base["binding_id"],
                "purpose": base["purpose"],
                "context_version": context_version,
            },
            prefix="wanctx-",
        )
        context = {
            **base,
            "context_id": context_id,
            "context_version": context_version,
            "executor_id": executor_id,
            "path_status": path["status"],
            "path_reason_code": path["reason_code"],
            "path_reason": path["reason"],
            "path_evidence": path["evidence"],
            "evidence_version": path["evidence_version"],
            "target": _probe_target_payload(item),
            "target_name": _text(item.get("target_name")),
            "target_host": _text(item.get("host")),
            "link_name": _text(item.get("link_name")),
            "tenant_mismatch": target_tenant != link_tenant,
        }
        if context["tenant_mismatch"]:
            context.update(
                path_status="invalid",
                path_reason_code="tenant_mismatch",
                path_reason="Probe target and circuit belong to different tenants",
            )
        contexts.append(context)
    return contexts


def _coerce_count(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _execute_context(
    context: dict[str, Any],
    *,
    probe_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started = _now_iso()
    if context.get("tenant_mismatch"):
        return {
            "execution_status": "skipped",
            "success": None,
            "started_at": started,
            "finished_at": _now_iso(),
            "error_type": "TENANT_SCOPE_MISMATCH",
            "error_message": context["path_reason"],
            "result": {},
        }
    if context["path_status"] == "unsupported":
        return {
            "execution_status": "unsupported",
            "success": None,
            "started_at": started,
            "finished_at": _now_iso(),
            "error_type": "PATH_UNSUPPORTED",
            "error_message": context["path_reason"],
            "result": {},
        }
    try:
        runner = probe_runner or outbound_probe_service._probe_target
        # A configured source address is meaningful only for an explicit
        # source-ip route mode.  Keep the configured value in the sample for
        # auditability, but never let it silently alter default-route probes.
        source_ip = context.get("source_ip") if context.get("route_mode") == "source_ip" else None
        source_ip = source_ip or None
        if source_ip:
            result = runner(context["target"], source_ip=source_ip)
        else:
            # Preserve the legacy callable contract for default-route targets.
            result = runner(context["target"])
        if not isinstance(result, dict):
            raise TypeError("probe runner must return a mapping")
        if source_ip and not _source_ip_matches(source_ip, result.get("source_ip_used")):
            return {
                "execution_status": "unsupported",
                "success": None,
                "started_at": started,
                "finished_at": _now_iso(),
                "error_type": "SOURCE_BINDING_UNCONFIRMED",
                "error_message": "Probe result did not confirm the configured source address",
                "result": result,
            }
        if result.get("unsupported") or result.get("error_type") == "SOURCE_BIND_UNSUPPORTED":
            return {
                "execution_status": "unsupported",
                "success": None,
                "started_at": started,
                "finished_at": _now_iso(),
                "error_type": _text(result.get("error_type") or "PATH_UNSUPPORTED"),
                "error_message": _text(result.get("error_message") or "Probe path execution is unsupported"),
                "result": result,
            }
        return {
            "execution_status": "completed",
            "success": bool(result.get("success")),
            "started_at": started,
            "finished_at": _now_iso(),
            "error_type": _text(result.get("error_type")),
            "error_message": _text(result.get("error_message")),
            "result": result,
        }
    except Exception as exc:
        return {
            "execution_status": "internal_error",
            "success": None,
            "started_at": started,
            "finished_at": _now_iso(),
            "error_type": "INTERNAL_PROBE_ERROR",
            "error_message": type(exc).__name__,
            "result": {},
        }


def _sample_record(context: dict[str, Any], execution: dict[str, Any], scheduled_at: datetime) -> dict[str, Any]:
    result = execution.get("result") or {}
    sent = _coerce_count(result.get("sent_count", result.get("packets_sent")))
    received = _coerce_count(result.get("received_count", result.get("packets_received")))
    success = execution.get("success") if execution.get("execution_status") == "completed" else None
    source_binding_mismatch = False
    if context.get("route_mode") == "source_ip":
        source_binding_mismatch = not _source_ip_matches(context.get("source_ip"), result.get("source_ip_used"))
    path_status = "invalid" if source_binding_mismatch else context["path_status"]
    sla_eligible = bool(
        _probe_purpose(context.get("purpose")) == "availability"
        and
        path_status == "verified"
        and execution.get("execution_status") == "completed"
        and not source_binding_mismatch
    )
    sample_id = _digest(
        {"context_id": context["context_id"], "scheduled_at": _now_iso(scheduled_at)},
        prefix="wanprobe-",
    )
    return {
        "id": sample_id,
        "tenant_id": context["tenant_id"],
        "link_id": context["link_id"],
        "target_id": context["target_id"],
        "purpose": _probe_purpose(context.get("purpose")),
        "context_id": context["context_id"],
        "context_version": context["context_version"],
        "configuration_version": context["configuration_version"],
        "policy_version": context["policy_version"],
        "executor_id": context["executor_id"],
        "protocol": _text(context["target"].get("probe_type") or "TCP_CONNECT").upper(),
        "route_mode": context["route_mode"],
        "source_ip": context["source_ip"],
        "path_status": path_status,
        "evidence_version": context["evidence_version"],
        "path_evidence": context["path_evidence"],
        "target_name": context["target_name"],
        "target_host": context["target_host"],
        "scheduled_at": _now_iso(scheduled_at),
        "started_at": execution.get("started_at"),
        "finished_at": execution.get("finished_at"),
        "execution_status": execution.get("execution_status") or "internal_error",
        "success": success,
        "sla_eligible": sla_eligible,
        "latency_ms": result.get("latency_ms"),
        "sent_count": sent,
        "received_count": received,
        "packet_loss_percent": result.get("packet_loss_percent"),
        "rtt_jitter_ms": result.get("rtt_jitter_ms"),
        "error_type": _text(
            "SOURCE_BINDING_UNCONFIRMED"
            if source_binding_mismatch
            else execution.get("error_type") or result.get("error_type")
        ),
        "error_message": _text(
            "Probe result did not confirm the configured source address"
            if source_binding_mismatch
            else execution.get("error_message") or result.get("error_message")
        ),
        "resolved_ip": _text(result.get("resolved_ip")),
        "result_json": result,
    }


def _persist_sample(conn, sample: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO wan_line_probe_samples (
            id, tenant_id, link_id, target_id, purpose, context_id, context_version,
            configuration_version, policy_version, executor_id, protocol,
            route_mode, source_ip, path_status, evidence_version, path_evidence,
            target_name, target_host, scheduled_at, started_at, finished_at,
            execution_status, success, sla_eligible, latency_ms, sent_count,
            received_count, packet_loss_percent, rtt_jitter_ms, error_type,
            error_message, resolved_ip, result_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb)
        ON CONFLICT (context_id, scheduled_at) DO UPDATE SET
            id = EXCLUDED.id,
            context_version = EXCLUDED.context_version,
            configuration_version = EXCLUDED.configuration_version,
            policy_version = EXCLUDED.policy_version,
            purpose = EXCLUDED.purpose,
            executor_id = EXCLUDED.executor_id,
            protocol = EXCLUDED.protocol,
            route_mode = EXCLUDED.route_mode,
            source_ip = EXCLUDED.source_ip,
            path_status = EXCLUDED.path_status,
            evidence_version = EXCLUDED.evidence_version,
            path_evidence = EXCLUDED.path_evidence,
            target_name = EXCLUDED.target_name,
            target_host = EXCLUDED.target_host,
            started_at = EXCLUDED.started_at,
            finished_at = EXCLUDED.finished_at,
            execution_status = EXCLUDED.execution_status,
            success = EXCLUDED.success,
            sla_eligible = EXCLUDED.sla_eligible,
            latency_ms = EXCLUDED.latency_ms,
            sent_count = EXCLUDED.sent_count,
            received_count = EXCLUDED.received_count,
            packet_loss_percent = EXCLUDED.packet_loss_percent,
            rtt_jitter_ms = EXCLUDED.rtt_jitter_ms,
            error_type = EXCLUDED.error_type,
            error_message = EXCLUDED.error_message,
            resolved_ip = EXCLUDED.resolved_ip,
            result_json = EXCLUDED.result_json
        """,
        (
            sample["id"], sample["tenant_id"], sample["link_id"], sample["target_id"],
            sample["purpose"], sample["context_id"], sample["context_version"], sample["configuration_version"],
            sample["policy_version"], sample["executor_id"], sample["protocol"],
            sample["route_mode"], sample["source_ip"], sample["path_status"],
            sample["evidence_version"], _json_dump(sample["path_evidence"]),
            sample["target_name"], sample["target_host"], sample["scheduled_at"],
            sample["started_at"], sample["finished_at"], sample["execution_status"],
            sample["success"], sample["sla_eligible"], sample["latency_ms"],
            sample["sent_count"], sample["received_count"], sample["packet_loss_percent"],
            sample["rtt_jitter_ms"], sample["error_type"], sample["error_message"],
            sample["resolved_ip"], _json_dump(sample["result_json"]),
        ),
    )


def _slot_for_contexts(
    contexts: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    *,
    slot_start: datetime,
) -> dict[str, Any]:
    # Quality and application probes remain durable evidence, but cannot
    # change the availability denominator or slot status.
    contexts = [item for item in contexts if _probe_purpose(item.get("purpose")) == "availability"]
    samples = [item for item in samples if _probe_purpose(item.get("purpose")) == "availability"]
    if not contexts:
        raise ValueError("availability slot requires at least one availability probe context")
    first = contexts[0]
    policy = dict(DEFAULT_SLA_POLICY)
    policy.update(first.get("policy") or {})
    rule = _text(policy.get("availability_rule") or "any_success").lower()
    if rule not in {"any_success", "all_success"}:
        rule = "any_success"
    sample_by_context = {str(item["context_id"]): item for item in samples}
    expected = len(contexts)
    verified = [item for item in samples if item.get("path_status") == "verified"]
    executable = [
        item for item in verified
        if item.get("execution_status") == "completed" and item.get("success") is not None
    ]
    status = "unknown"
    reason_code = "path_evidence_unavailable"
    reason = "At least one configured context lacks fresh verifiable path evidence"
    if len(verified) == expected and len(executable) == expected:
        successes = [bool(item.get("success")) for item in executable]
        if (rule == "all_success" and all(successes)) or (rule == "any_success" and any(successes)):
            status = "up"
            reason_code = "required_probe_success"
            reason = "All required contexts produced valid evidence and the availability rule passed"
        elif all(not value for value in successes):
            status = "down"
            reason_code = "required_probe_failure"
            reason = "All required contexts produced valid evidence and failed"
        else:
            status = "unknown"
            reason_code = "availability_rule_not_satisfied"
            reason = "Context results do not satisfy the configured availability rule"
    elif len(verified) == expected:
        reason_code = "probe_execution_incomplete"
        reason = "Path evidence is valid but one or more contexts did not complete"
    elif any(item.get("path_status") == "unsupported" for item in samples):
        reason_code = "path_evidence_unsupported"
        reason = "The configured executor cannot verify at least one circuit path"
    elif any(item.get("path_status") == "invalid" for item in samples):
        reason_code = "path_evidence_invalid"
        reason = "At least one path evidence record is stale or mismatched"
    if not first.get("policy_version"):
        status = "unknown"
        reason_code = "policy_not_configured"
        reason = "No versioned SLA policy is configured for this circuit"

    sent = sum(int(item.get("sent_count") or 0) for item in samples)
    received = sum(int(item.get("received_count") or 0) for item in samples)
    coverage = round(len(executable) / expected * 100, 2) if expected else 0.0
    evidence_refs = [
        {
            "sample_id": item["id"],
            "context_id": item["context_id"],
            "path_status": item["path_status"],
            "evidence_version": item.get("evidence_version") or "",
        }
        for item in samples
    ]
    return {
        "id": _digest(
            {
                "link_id": first["link_id"],
                "slot_start": _now_iso(slot_start),
                "configuration_version": first["configuration_version"],
                "policy_version": first["policy_version"],
            },
            prefix="wanslot-",
        ),
        "tenant_id": first["tenant_id"],
        "link_id": first["link_id"],
        "slot_start": _now_iso(slot_start),
        "slot_end": _now_iso(slot_start + timedelta(seconds=DEFAULT_CADENCE_SECONDS)),
        "configuration_version": first["configuration_version"],
        "policy_version": first["policy_version"],
        "context_ids": [item["context_id"] for item in contexts],
        "context_versions": [item["context_version"] for item in contexts],
        "status": status,
        "reason_code": reason_code,
        "reason": reason,
        "evidence_refs": evidence_refs,
        "sample_count": len(samples),
        "eligible_sample_count": len(executable),
        "sent_count": sent,
        "received_count": received,
        "coverage_percent": coverage,
        "algorithm_version": SLA_ALGORITHM_VERSION,
        "policy": policy,
        "sample_by_context": sample_by_context,
    }


def _persist_slot(conn, slot: dict[str, Any]) -> None:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO wan_line_quality_slots (
            id, tenant_id, link_id, slot_start, slot_end, configuration_version,
            policy_version, context_ids, context_versions, status, reason_code,
            reason, evidence_refs, sample_count, eligible_sample_count,
            sent_count, received_count, coverage_percent, created_at, updated_at,
            algorithm_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?, ?::jsonb,
                  ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (link_id, slot_start, configuration_version, policy_version, algorithm_version)
        DO UPDATE SET
            id = EXCLUDED.id,
            tenant_id = EXCLUDED.tenant_id,
            slot_end = EXCLUDED.slot_end,
            context_ids = EXCLUDED.context_ids,
            context_versions = EXCLUDED.context_versions,
            status = EXCLUDED.status,
            reason_code = EXCLUDED.reason_code,
            reason = EXCLUDED.reason,
            evidence_refs = EXCLUDED.evidence_refs,
            sample_count = EXCLUDED.sample_count,
            eligible_sample_count = EXCLUDED.eligible_sample_count,
            sent_count = EXCLUDED.sent_count,
            received_count = EXCLUDED.received_count,
            coverage_percent = EXCLUDED.coverage_percent,
            updated_at = EXCLUDED.updated_at
        """,
        (
            slot["id"], slot["tenant_id"], slot["link_id"], slot["slot_start"], slot["slot_end"],
            slot["configuration_version"], slot["policy_version"], _json_dump(slot["context_ids"]),
            _json_dump(slot["context_versions"]), slot["status"], slot["reason_code"], slot["reason"],
            _json_dump(slot["evidence_refs"]), slot["sample_count"], slot["eligible_sample_count"],
            slot["sent_count"], slot["received_count"], slot["coverage_percent"], now, now,
            slot["algorithm_version"],
        ),
    )


def _window_bounds(window: str, now: datetime | None = None) -> tuple[str, datetime, datetime]:
    # A slot is eligible only after its 60-second interval has completed.  A
    # rounded end also keeps repeated snapshot reads idempotent within a slot.
    current = _slot_start((now or _now()).astimezone(timezone.utc))
    key = _text(window or "24h").lower()
    if key in {"month", "current_month", "mtd"}:
        start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return key, start, current
    if key.endswith("d"):
        try:
            amount = max(1, min(366, int(key[:-1])))
        except ValueError:
            amount = 1
        return key, current - timedelta(days=amount), current
    if key.endswith("h"):
        try:
            amount = max(1, min(24 * 366, int(key[:-1])))
        except ValueError:
            amount = 24
        return key, current - timedelta(hours=amount), current
    return "24h", current - timedelta(hours=24), current


def _first_completed_slot(value: datetime) -> datetime:
    """Round an activation time up so partial activation minutes are excluded."""

    rounded = _slot_start(value)
    return rounded if rounded >= value else rounded + timedelta(seconds=DEFAULT_CADENCE_SECONDS)


def _effective_sla_start(conn, link: dict[str, Any], policy_row: dict[str, Any], start: datetime) -> datetime:
    """Return the first minute for which this link/policy could be measured."""

    candidates = [start]
    for value in (link.get("created_at"), policy_row.get("updated_at")):
        parsed = _parse_datetime(value)
        if parsed is not None:
            candidates.append(parsed.astimezone(timezone.utc))
    policy_version = int(policy_row.get("policy_version") or 0)
    if policy_version:
        history_row = conn.execute(
            """
            SELECT created_at FROM wan_link_sla_policy_history
             WHERE link_id = ? AND policy_version = ?
             ORDER BY created_at ASC LIMIT 1
            """,
            (link.get("id"), policy_version),
        ).fetchone()
        if history_row:
            parsed = _parse_datetime(history_row[0])
            if parsed is not None:
                candidates.append(parsed.astimezone(timezone.utc))
    return _first_completed_slot(max(candidates))


def _maintenance_intervals(
    conn,
    link: dict[str, Any],
    *,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Expand matching one-time and recurring maintenance into UTC intervals."""
    if end <= start:
        return []
    link_id = _text(link.get("id"))
    site_id = _text(link.get("site_id"))
    device_id = _text(link.get("device_id"))
    group_ids = {
        str(row[0]) for row in conn.execute(
            "SELECT group_id FROM wan_link_group_members WHERE link_id = ?",
            (link_id,),
        ).fetchall()
    }
    rows = conn.execute(
        "SELECT * FROM wan_maintenance_windows WHERE enabled = TRUE AND deleted_at IS NULL"
    ).fetchall()
    result: list[tuple[datetime, datetime]] = []
    for raw_row in rows:
        window = dict(raw_row)
        scopes = [
            ("link", _text(window.get("link_id"))),
            ("site", _text(window.get("site_id"))),
            ("device", _text(window.get("device_id"))),
            ("group", _text(window.get("link_group_id"))),
        ]
        configured_scopes = [(kind, value) for kind, value in scopes if value]
        matches = any(
            (kind == "link" and value == link_id)
            or (kind == "site" and value == site_id)
            or (kind == "device" and value == device_id)
            or (kind == "group" and value in group_ids)
            for kind, value in configured_scopes
        )
        if configured_scopes and not matches:
            continue
        window_start = _parse_datetime(window.get("starts_at"))
        window_end = _parse_datetime(window.get("ends_at"))
        if window_start is None or window_end is None or window_end <= window_start:
            continue
        recurrence = _text(window.get("recurrence") or "once").lower()
        if recurrence == "once":
            intervals = [(window_start, window_end)]
        else:
            try:
                local_zone = ZoneInfo(_text(window.get("timezone") or "UTC"))
            except (TypeError, ValueError, ZoneInfoNotFoundError):
                continue
            local_start = window_start.astimezone(local_zone)
            local_end = end.astimezone(local_zone)
            duration = window_end - window_start
            lookback = max(1, int(duration.total_seconds() // 86400) + 1)
            day = max(local_start.date(), (start.astimezone(local_zone) - timedelta(days=lookback)).date())
            intervals = []
            if recurrence in {"daily", "weekly"}:
                while day <= local_end.date():
                    days_from_start = (day - local_start.date()).days
                    is_occurrence = recurrence == "daily" or days_from_start % 7 == 0
                    if days_from_start >= 0 and is_occurrence:
                        occurrence = datetime.combine(day, local_start.timetz())
                        intervals.append((occurrence.astimezone(timezone.utc), occurrence.astimezone(timezone.utc) + duration))
                    day += timedelta(days=1)
            elif recurrence == "monthly":
                month = max(local_start.year * 12 + local_start.month - 1, day.year * 12 + day.month - 1)
                last_month = local_end.year * 12 + local_end.month - 1
                while month <= last_month:
                    year, month0 = divmod(month, 12)
                    month_number = month0 + 1
                    occurrence_day = min(local_start.day, monthrange(year, month_number)[1])
                    occurrence = local_start.replace(year=year, month=month_number, day=occurrence_day)
                    if occurrence >= local_start:
                        intervals.append((occurrence.astimezone(timezone.utc), occurrence.astimezone(timezone.utc) + duration))
                    month += 1
            else:
                continue
        for interval_start, interval_end in intervals:
            clipped_start = max(start, interval_start.astimezone(timezone.utc))
            clipped_end = min(end, interval_end.astimezone(timezone.utc))
            if clipped_end > clipped_start:
                result.append((clipped_start, clipped_end))

    merged: list[tuple[datetime, datetime]] = []
    for interval_start, interval_end in sorted(result):
        if not merged or interval_start > merged[-1][1]:
            merged.append((interval_start, interval_end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], interval_end))
    return merged


def _eligible_slot_seconds(
    slot_start: datetime,
    slot_end: datetime,
    excluded: list[tuple[datetime, datetime]],
) -> int:
    slot_seconds = max(0.0, (slot_end - slot_start).total_seconds())
    excluded_seconds = sum(
        max(0.0, (min(slot_end, interval_end) - max(slot_start, interval_start)).total_seconds())
        for interval_start, interval_end in excluded
    )
    return max(0, int(round(slot_seconds - excluded_seconds)))


def _calculate_sla(conn, link_id: str, *, tenant_id: str | None, window: str, now: datetime | None = None) -> dict[str, Any]:
    window_key, start, end = _window_bounds(window, now)
    link = conn.execute("SELECT id, tenant_id, configuration_version, created_at, site_id, device_id FROM wan_links WHERE id = ?", (link_id,)).fetchone()
    link_item = dict(link) if link else {}
    if not link_item or (tenant_id and _text(link_item.get("tenant_id")) != _text(tenant_id)):
        return None  # type: ignore[return-value]
    policy_row = conn.execute(
        "SELECT policy_version, policy_json, updated_at FROM wan_link_sla_policies WHERE link_id = ?",
        (link_id,),
    ).fetchone()
    policy_item = dict(policy_row) if policy_row else {}
    policy = _json_object(policy_item.get("policy_json"))
    policy_version = int(policy_item.get("policy_version") or 0)
    effective_start = _effective_sla_start(conn, link_item, policy_item, start) if policy_version else end
    maintenance_intervals = (
        _maintenance_intervals(conn, link_item, start=effective_start, end=end)
        if policy_version and bool(policy.get("maintenance_excluded", False)) and effective_start < end
        else []
    )
    slots = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM wan_line_quality_slots
             WHERE link_id = ? AND slot_start >= ? AND slot_start < ?
             ORDER BY slot_start
            """,
            (link_id, _now_iso(effective_start), _now_iso(end)),
        ).fetchall()
    ]
    # Configuration/policy changes can produce two rows for one timestamp.
    # Count each completed time slot once while retaining all observed version
    # pairs for the mixed-version decision below.
    slots_by_start: dict[str, dict[str, Any]] = {}
    for slot in slots:
        slot_key = _now_iso(_parse_datetime(slot.get("slot_start")) or effective_start)
        previous = slots_by_start.get(slot_key)
        current_updated = _parse_datetime(slot.get("updated_at")) or effective_start
        previous_updated = _parse_datetime(previous.get("updated_at")) if previous else None
        if previous is None or current_updated >= (previous_updated or effective_start):
            slots_by_start[slot_key] = slot
    stats = {"up": 0, "down": 0, "unknown": 0, "up_seconds": 0, "down_seconds": 0, "unknown_seconds": 0}
    evidence_refs: list[Any] = []
    versions: set[tuple[int, int]] = set()
    eligible_slot_count = 0
    observed_slots = 0
    missing_slot_count = 0
    fully_excluded_slot_count = 0
    cursor = effective_start
    while cursor + timedelta(seconds=DEFAULT_CADENCE_SECONDS) <= end:
        slot_end = cursor + timedelta(seconds=DEFAULT_CADENCE_SECONDS)
        eligible_seconds = _eligible_slot_seconds(cursor, slot_end, maintenance_intervals)
        slot_key = _now_iso(cursor)
        slot = slots_by_start.get(slot_key)
        if eligible_seconds <= 0:
            fully_excluded_slot_count += 1
            cursor = slot_end
            continue
        eligible_slot_count += 1
        if slot is None:
            missing_slot_count += 1
            stats["unknown"] += 1
            stats["unknown_seconds"] += eligible_seconds
            cursor = slot_end
            continue
        observed_slots += 1
        status = _text(slot.get("status")) if _text(slot.get("status")) in {"up", "down", "unknown"} else "unknown"
        stats[status] += 1
        stats[f"{status}_seconds"] += eligible_seconds
        evidence_refs.extend(_json_list(slot.get("evidence_refs")))
        versions.add((int(slot.get("configuration_version") or 1), int(slot.get("policy_version") or 0)))
        cursor = slot_end
    eligible_seconds = stats["up_seconds"] + stats["down_seconds"] + stats["unknown_seconds"]
    total_window_seconds = max(0, int((end - effective_start).total_seconds()))
    maintenance_excluded_seconds = max(0, total_window_seconds - eligible_seconds)
    observed_denominator = stats["up_seconds"] + stats["down_seconds"]
    observed = round(stats["up_seconds"] / observed_denominator * 100, 6) if observed_denominator else None
    lower = round(stats["up_seconds"] / eligible_seconds * 100, 6) if eligible_seconds else None
    upper = round((stats["up_seconds"] + stats["unknown_seconds"]) / eligible_seconds * 100, 6) if eligible_seconds else None
    coverage = round(observed_denominator / eligible_seconds * 100, 6) if eligible_seconds else None

    target = float(policy.get("availability_target_pct", DEFAULT_SLA_POLICY["availability_target_pct"]) or 0)
    minimum_coverage = float(policy.get("minimum_coverage_pct", DEFAULT_SLA_POLICY["minimum_coverage_pct"]) or 0)
    if not policy_version:
        status = "insufficient_data"
        reason_code = "policy_not_configured"
        reason = "No versioned SLA policy is configured for this circuit"
    elif eligible_slot_count <= 0:
        status = "not_applicable"
        reason_code = "maintenance_excluded_period" if maintenance_excluded_seconds > 0 else "no_completed_slots"
        reason = "The requested period is fully excluded by maintenance policy" if maintenance_excluded_seconds > 0 else "No completed quality slots are available in the requested window"
    elif not observed_slots:
        status = "insufficient_data"
        reason_code = "no_completed_slots"
        reason = "The active link and SLA policy have no completed quality measurements in the requested window"
    elif upper is not None and upper < target:
        status = "breached"
        reason_code = "availability_upper_below_target"
        reason = "Even the optimistic availability bound is below the configured target"
    elif stats["unknown_seconds"] > 0:
        # Unknown intervals prevent a trusted met conclusion, but a sufficiently
        # low optimistic bound still proves a breach.
        status = "insufficient_data"
        reason_code = "coverage_or_unknown_slots"
        reason = "Unknown slots or missing intervals prevent a trusted SLA conclusion"
    elif coverage is not None and coverage >= minimum_coverage and lower is not None and lower >= target:
        status = "met"
        reason_code = "availability_lower_meets_target"
        reason = "Coverage and the conservative availability bound meet the configured target"
    else:
        status = "insufficient_data"
        reason_code = "coverage_or_unknown_slots"
        reason = "Unknown slots or insufficient coverage prevent a trusted SLA conclusion"
    if observed_slots and stats["up"] + stats["down"] == 0:
        status = "insufficient_data"
        reason_code = "path_evidence_unavailable"
        reason = "All completed slots are unknown because path evidence is unavailable or invalid"

    verified_sample_rows = conn.execute(
        """
        SELECT scheduled_at FROM wan_line_probe_samples
         WHERE link_id = ? AND scheduled_at >= ? AND scheduled_at < ?
           AND purpose = 'availability'
           AND path_status = 'verified' AND sla_eligible IS TRUE
        """,
        (link_id, _now_iso(effective_start), _now_iso(end)),
    ).fetchall()
    verified_sample_count = 0
    for row in verified_sample_rows:
        sample_at = _parse_datetime(row[0])
        if sample_at is None:
            continue
        sample_slot = sample_at.replace(second=(sample_at.second // DEFAULT_CADENCE_SECONDS) * DEFAULT_CADENCE_SECONDS, microsecond=0)
        if _eligible_slot_seconds(sample_slot, sample_slot + timedelta(seconds=DEFAULT_CADENCE_SECONDS), maintenance_intervals) > 0:
            verified_sample_count += 1
    configuration_versions = sorted({version[0] for version in versions})
    policy_versions = sorted({version[1] for version in versions})
    result = {
        "link_id": link_id,
        "tenant_id": _text(link_item.get("tenant_id")) or "tenant-default",
        "window": window_key,
        "window_start": _now_iso(start),
        "window_end": _now_iso(end),
        "status": status,
        "reason_code": reason_code,
        "reason": reason,
        "observed": observed,
        "lower": lower,
        "upper": upper,
        "observed_availability": observed,
        "lower_bound": lower,
        "upper_bound": upper,
        "availability": {"value": observed, "lower_bound": lower, "upper_bound": upper},
        "coverage": coverage,
        "coverage_percent": coverage,
        "slots": eligible_slot_count,
        "slot_stats": {
            **stats,
            "eligible_seconds": eligible_seconds,
            "observed_seconds": observed_denominator,
            "observed_slots": observed_slots,
            "expected_slots": eligible_slot_count,
            "missing_slots": missing_slot_count,
            "fully_excluded_slots": fully_excluded_slot_count,
            "maintenance_excluded_seconds": maintenance_excluded_seconds,
            "maintenance_exclusion_count": len(maintenance_intervals),
            "effective_start": _now_iso(effective_start) if policy_version else None,
        },
        "policy_version": policy_version or None,
        "configuration_version": int(link_item.get("configuration_version") or 1),
        "configuration_versions": configuration_versions,
        "policy_versions": policy_versions,
        "policy": policy or None,
        "evidence": {
            "source": "wan_line_probe_samples",
            "path_proven": bool(verified_sample_count and stats["unknown_seconds"] == 0),
            "verified_sample_count": verified_sample_count,
            "evidence_refs": evidence_refs[:500],
            "version_segments": [
                {"configuration_version": config, "policy_version": policy_v}
                for config, policy_v in sorted(versions)
            ],
        },
        "version_segments": [
            {"configuration_version": config, "policy_version": policy_v}
            for config, policy_v in sorted(versions)
        ],
    }
    if len(versions) > 1 and status in {"met", "breached"}:
        result["status"] = "insufficient_data"
        result["reason_code"] = "mixed_configuration_or_policy_versions"
        result["reason"] = "The requested window contains multiple configuration or policy versions"
    current_configuration_version = int(link_item.get("configuration_version") or 1)
    if slots and (
        (configuration_versions and current_configuration_version not in configuration_versions)
        or (policy_versions and policy_version and policy_version not in policy_versions)
    ):
        result["status"] = "insufficient_data"
        result["reason_code"] = "current_version_not_observed"
        result["reason"] = "The requested window does not contain samples for the current configuration or policy version"
    return result


def _persist_sla_snapshot(conn, result: dict[str, Any]) -> None:
    configuration_version = int(result.get("configuration_version") or 1)
    policy_version = int(result.get("policy_version") or 0)
    snapshot_id = _digest(
        {
            "link_id": result["link_id"],
            "window": result["window"],
            "window_start": result["window_start"],
            "window_end": result["window_end"],
            "configuration_version": configuration_version,
            "policy_version": policy_version,
        },
        prefix="wansla-",
    )
    stats = result.get("slot_stats") or {}
    evidence = result.get("evidence") or {}
    conn.execute(
        """
        INSERT INTO wan_line_sla_snapshots (
            id, tenant_id, link_id, window_key, window_start, window_end,
            configuration_version, policy_version, algorithm_version, status,
            reason_code, reason, observed_availability, lower_bound, upper_bound,
            coverage_percent, eligible_seconds, up_seconds, down_seconds,
            unknown_seconds, slot_count, up_slot_count, down_slot_count,
            unknown_slot_count, slot_stats, evidence, revision, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, 1, ?, ?)
        ON CONFLICT (link_id, window_key, window_start, window_end, configuration_version, policy_version, algorithm_version)
        DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            status = EXCLUDED.status,
            reason_code = EXCLUDED.reason_code,
            reason = EXCLUDED.reason,
            observed_availability = EXCLUDED.observed_availability,
            lower_bound = EXCLUDED.lower_bound,
            upper_bound = EXCLUDED.upper_bound,
            coverage_percent = EXCLUDED.coverage_percent,
            eligible_seconds = EXCLUDED.eligible_seconds,
            up_seconds = EXCLUDED.up_seconds,
            down_seconds = EXCLUDED.down_seconds,
            unknown_seconds = EXCLUDED.unknown_seconds,
            slot_count = EXCLUDED.slot_count,
            up_slot_count = EXCLUDED.up_slot_count,
            down_slot_count = EXCLUDED.down_slot_count,
            unknown_slot_count = EXCLUDED.unknown_slot_count,
            slot_stats = EXCLUDED.slot_stats,
            evidence = EXCLUDED.evidence,
            revision = wan_line_sla_snapshots.revision + 1,
            updated_at = EXCLUDED.updated_at
        """,
        (
            snapshot_id, result["tenant_id"], result["link_id"], result["window"], result["window_start"],
            result["window_end"], configuration_version, policy_version, SLA_ALGORITHM_VERSION,
            result["status"], result["reason_code"], result["reason"], result.get("observed"),
            result.get("lower"), result.get("upper"), result.get("coverage"), stats.get("eligible_seconds", 0),
            stats.get("up_seconds", 0), stats.get("down_seconds", 0), stats.get("unknown_seconds", 0),
            result.get("slots", 0), stats.get("up", 0), stats.get("down", 0), stats.get("unknown", 0),
            _json_dump(stats), _json_dump(evidence), _now_iso(), _now_iso(),
        ),
    )


def run_wan_line_probe_once(
    *,
    scheduled_at: datetime | str | None = None,
    link_id: str = "",
    tenant_id: str = "",
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    probe_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one bounded, idempotent circuit-probe slot.

    ``probe_runner`` is an injection seam for isolated tests.  Production uses
    the SSRF-protected outbound probe implementation.  A concurrent scheduler
    invocation is coalesced by the in-process lock and by the scheduler's
    cross-instance lock wrapper.
    """

    _require_postgres()
    if not _RUN_LOCK.acquire(blocking=False):
        return {"status": "skipped", "reason_code": "overlap", "contexts": 0, "samples": 0}
    conn = None
    try:
        slot_start = _slot_start(scheduled_at)
        conn = get_db_connection()
        contexts = _load_contexts(conn, link_id=link_id, tenant_id=tenant_id)
        if not contexts:
            return {
                "status": "completed",
                "reason_code": "no_enabled_probe_contexts",
                "scheduled_at": _now_iso(slot_start),
                "contexts": 0,
                "samples": 0,
                "links": 0,
            }
        workers = max(1, min(DEFAULT_MAX_CONCURRENCY, int(max_concurrency or DEFAULT_MAX_CONCURRENCY), len(contexts)))
        executions: dict[str, dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wan-line-probe") as executor:
            future_map = {
                executor.submit(_execute_context, context, probe_runner=probe_runner): context
                for context in contexts
            }
            for future in concurrent.futures.as_completed(future_map):
                context = future_map[future]
                try:
                    executions[context["context_id"]] = future.result()
                except Exception as exc:
                    executions[context["context_id"]] = {
                        "execution_status": "internal_error",
                        "success": None,
                        "started_at": _now_iso(),
                        "finished_at": _now_iso(),
                        "error_type": "INTERNAL_PROBE_ERROR",
                        "error_message": type(exc).__name__,
                        "result": {},
                    }
        samples = []
        for context in contexts:
            sample = _sample_record(context, executions[context["context_id"]], slot_start)
            _persist_sample(conn, sample)
            samples.append(sample)
        by_link: dict[str, list[dict[str, Any]]] = {}
        contexts_by_link: dict[str, list[dict[str, Any]]] = {}
        for context in contexts:
            contexts_by_link.setdefault(context["link_id"], []).append(context)
        for sample in samples:
            by_link.setdefault(sample["link_id"], []).append(sample)
        availability_contexts_by_link = {
            current_link: [item for item in current_contexts if _probe_purpose(item.get("purpose")) == "availability"]
            for current_link, current_contexts in contexts_by_link.items()
        }
        availability_samples_by_link = {
            current_link: [item for item in current_samples if _probe_purpose(item.get("purpose")) == "availability"]
            for current_link, current_samples in by_link.items()
        }
        results_by_link: dict[str, dict[str, Any]] = {}
        for current_link, current_contexts in availability_contexts_by_link.items():
            if not current_contexts:
                continue
            slot = _slot_for_contexts(
                current_contexts,
                availability_samples_by_link.get(current_link, []),
                slot_start=slot_start,
            )
            _persist_slot(conn, slot)
            sla = _calculate_sla(conn, current_link, tenant_id=current_contexts[0]["tenant_id"], window="24h")
            if sla:
                _persist_sla_snapshot(conn, sla)
                results_by_link[current_link] = sla
        conn.commit()
        return {
            "status": "completed",
            "scheduled_at": _now_iso(slot_start),
            "contexts": len(contexts),
            "samples": len(samples),
            "links": len(contexts_by_link),
            "up": sum(1 for current in by_link if results_by_link.get(current, {}).get("status") == "met"),
            "sla": results_by_link,
        }
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception("WAN line probe slot failed")
        return {"status": "failed", "reason_code": "internal_error"}
    finally:
        if conn is not None:
            conn.close()
        _RUN_LOCK.release()


def get_wan_line_sla(
    link_id: str,
    *,
    tenant_id: str | None = None,
    window: str = "24h",
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    """Read a versioned SLA summary and optionally refresh its durable snapshot."""

    _require_postgres()
    conn = get_db_connection()
    try:
        result = _calculate_sla(conn, link_id, tenant_id=tenant_id, window=window)
        if result is not None and persist_snapshot:
            _persist_sla_snapshot(conn, result)
            conn.commit()
        return result
    finally:
        conn.close()


def calculate_wan_line_sla(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    """Compatibility alias for callers that name the operation explicitly."""

    return get_wan_line_sla(*args, **kwargs)


def run_wan_circuit_probe_once(**kwargs: Any) -> dict[str, Any]:
    """Compatibility alias used by early S2 scheduler integrations."""

    return run_wan_line_probe_once(**kwargs)


__all__ = [
    "SLA_ALGORITHM_VERSION",
    "calculate_wan_line_sla",
    "get_wan_line_sla",
    "run_wan_circuit_probe_once",
    "run_wan_line_probe_once",
]
