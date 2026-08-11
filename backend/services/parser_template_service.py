"""Tenant-scoped parser template development services for P1."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.playbook_output_service import load_output, protect_output
from services.platform_registry_service import (
    PlatformRegistryError,
    _row_dict,
    _coerce_field_types,
    _field_contract,
    _normalize_records,
    _validate_field_contract,
    normalize_parser_command,
    normalize_platform_code,
    validate_platform_code,
    validate_template_code,
)
from services.textfsm_sandbox_service import TextFSMSandboxError, parse_template_in_sandbox


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _validate_parser_platform(value: Any) -> str:
    """Normalize a template platform and reject non-public H3C selectors.

    V5/V7/V9 are selected by the bound Profile and its template filename
    variant. They must not become separate values in ``parser_templates``.
    """
    raw = str(value or "").strip().lower()
    normalized = normalize_platform_code(raw)
    if raw in {"hp_comware", "h3c_comware9", "h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9"}:
        raise PlatformRegistryError(
            "INVALID_PARSER_PLATFORM",
            "H3C TextFSM 模板平台必须使用 h3c_comware；V5/V7/V9 请通过 Profile 和模板变体区分",
            status_code=400,
        )
    return validate_platform_code(normalized)


def _actor_key(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("username") or "")


def _audit_parser_event(
    conn,
    template_id: str,
    version_id: str | None,
    event_type: str,
    user: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write a small, non-sensitive lifecycle event inside the caller's transaction."""
    conn.execute(
        """INSERT INTO parser_template_audit_logs
           (id, template_id, version_id, event_type, actor_id, actor_username, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()), template_id, version_id or None, event_type,
            _actor_key(user), str(user.get("username") or ""),
            json.dumps(metadata or {}, ensure_ascii=False), _now(),
        ),
    )


def _summary_for_records(records: list[dict[str, Any]], contract: dict[str, Any], duration_ms: int) -> dict[str, Any]:
    fields = sorted({str(key) for record in records for key in record})
    contract_fields = sorted(
        set(contract.get("required") or [])
        | set(contract.get("optional") or [])
        | set((contract.get("types") or {}).keys())
    )
    coverage = {
        field: round(
            sum(1 for record in records if record.get(field) not in (None, "")) / len(records),
            4,
        ) if records else 0
        for field in contract_fields
    }
    return {
        "passed": True,
        "record_count": len(records),
        "fields": fields,
        "field_coverage": coverage,
        "field_contract": contract,
        "duration_ms": max(0, int(duration_ms)),
        "tested_at": _now(),
    }


def _release_manager_or_administrator(user: dict[str, Any]) -> None:
    role = str(user.get("role") or "")
    profile = str(user.get("role_profile") or "")
    if role == "Administrator" or profile in {"Release Manager", "System Administrator"}:
        return
    raise PlatformRegistryError(
        "PARSER_RELEASE_PERMISSION_REQUIRED",
        "Only a release manager or Administrator can change a published parser version",
        status_code=403,
    )


def _assert_template_access(conn, template_id: str, user: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM parser_templates WHERE id = ?", (template_id,)).fetchone()
    template = _row_dict(row)
    if not template:
        raise PlatformRegistryError("PARSER_TEMPLATE_NOT_FOUND", "Parser template not found", status_code=404)
    tenant_id = str(template.get("tenant_id") or "")
    user_tenant = str(user.get("tenant_id") or "")
    if tenant_id and tenant_id != user_tenant and user.get("role") != "Administrator":
        raise PlatformRegistryError("PARSER_SCOPE_DENIED", "Parser template is outside the current tenant scope", status_code=403)
    return template


def _load_version(conn, version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    row = _row_dict(conn.execute(
        """SELECT v.*, t.id AS template_id, t.tenant_id AS template_tenant_id,
                  t.platform_code, t.source AS template_source
           FROM parser_template_versions v
           JOIN parser_templates t ON t.id = v.template_id
           WHERE v.id = ?""",
        (version_id,),
    ).fetchone())
    if not row:
        raise PlatformRegistryError("PARSER_VERSION_NOT_FOUND", "Parser template version not found", status_code=404)
    _assert_template_access(conn, str(row["template_id"]), user)
    return row


def _require_administrator(user: dict[str, Any]) -> None:
    if user.get("role") != "Administrator":
        raise PlatformRegistryError(
            "PARSER_RELEASE_PERMISSION_REQUIRED",
            "Only an Administrator can approve or publish parser versions",
            status_code=403,
        )


def _require_sandbox_pass(row: dict[str, Any], event: str) -> dict[str, Any]:
    """Require a successful test for every forward lifecycle transition.

    The summary is cleared whenever a draft is edited, so a ``passed`` flag
    here represents the currently persisted draft content rather than a
    stale test result from an earlier revision.
    """
    try:
        summary = json.loads(row.get("test_summary_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        summary = {}
    if not isinstance(summary, dict):
        summary = {}
    if summary.get("passed") is not True:
        stage = {
            "submit": "提交审核",
            "approve": "审批",
            "publish": "发布",
        }.get(event, "继续流转")
        raise PlatformRegistryError(
            "PARSER_TEST_REQUIRED",
            f"解析版本在{stage}前必须先通过 Sandbox 测试",
            status_code=409,
        )
    return summary


def _validated_contract(value: Any) -> dict[str, Any]:
    contract = _field_contract(value or {})
    allowed_types = {"string", "integer", "number", "boolean"}
    invalid_types = sorted({kind for kind in (contract.get("types") or {}).values() if kind not in allowed_types})
    if invalid_types:
        raise PlatformRegistryError(
            "INVALID_FIELD_CONTRACT",
            f"Unsupported field contract types: {', '.join(invalid_types)}",
        )
    fields = set(contract.get("required") or []) | set(contract.get("optional") or []) | set((contract.get("types") or {}).keys())
    if len(fields) > 128:
        raise PlatformRegistryError("FIELD_LIMIT_EXCEEDED", "Field contract contains too many fields")
    return contract


def list_templates(
    user: dict[str, Any],
    *,
    platform_code: str = "",
    driver_platform: str = "",
) -> list[dict[str, Any]]:
    return list_templates_page(user, platform_code=platform_code, driver_platform=driver_platform)["items"]


def list_templates_page(
    user: dict[str, Any],
    *,
    platform_code: str = "",
    driver_platform: str = "",
    search: str = "",
    source: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Return a bounded, tenant-scoped page for the registry UI."""
    conn = get_db_connection()
    try:
        tenant_id = str(user.get("tenant_id") or "")
        clauses = [] if status.strip().upper() == "ARCHIVED" else ["status <> 'ARCHIVED'"]
        params: list[Any] = []
        if user.get("role") != "Administrator" or tenant_id:
            clauses.insert(0, "(tenant_id IS NULL OR tenant_id = ?)")
            params.append(tenant_id)
        if platform_code:
            clauses.append("platform_code = ?")
            params.append(normalize_platform_code(platform_code))
        if driver_platform.strip():
            # TextFSM stores the canonical parser platform, while the
            # platform registry stores the Netmiko-facing connection driver.
            # Resolve the driver to its parser key through the registry so the
            # UI can filter by the same driver taxonomy used by devices.
            clauses.append(
                "platform_code IN ("
                "SELECT DISTINCT pp.parser_platform FROM platform_profiles pp "
                "WHERE LOWER(COALESCE(pp.connection_driver, pp.parser_platform)) = ?"
                ")"
            )
            params.append(driver_platform.strip().lower())
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append("(template_code LIKE ? OR name LIKE ? OR platform_code LIKE ?)")
            params.extend([needle, needle, needle])
        if source.strip():
            clauses.append("source = ?")
            params.append(source.strip().upper())
        if status.strip():
            clauses.append("status = ?")
            params.append(status.strip().upper())
        where = " AND ".join(clauses) or "1 = 1"
        total_row = conn.execute(f"SELECT COUNT(*) AS total FROM parser_templates WHERE {where}", params).fetchone()
        total = int((total_row["total"] if total_row else 0) or 0)
        safe_page = max(1, int(page or 1))
        safe_size = min(100, max(1, int(page_size or 50)))
        offset = (safe_page - 1) * safe_size
        rows = conn.execute(
            "SELECT * FROM parser_templates WHERE " + where
            + " ORDER BY source, platform_code, template_code LIMIT ? OFFSET ?",
            [*params, safe_size, offset],
        ).fetchall()
        return {
            "items": [_row_dict(row) or {} for row in rows],
            "total": total,
            "page": safe_page,
            "page_size": safe_size,
            "pages": (total + safe_size - 1) // safe_size if total else 0,
        }
    finally:
        conn.close()


def create_template(payload: dict[str, Any], user: dict[str, Any], *, _source: str = "CUSTOM") -> dict[str, Any]:
    platform_code = _validate_parser_platform(payload.get("platform_code"))
    template_code = validate_template_code(payload.get("template_code"))
    command = normalize_parser_command(payload.get("command"))
    tenant_id = str(user.get("tenant_id") or "")
    if _source == "FORKED" and not tenant_id:
        raise PlatformRegistryError(
            "TENANT_REQUIRED",
            "Forked parser templates must be created inside a tenant scope",
            status_code=400,
        )
    if not tenant_id and user.get("role") != "Administrator":
        raise PlatformRegistryError("TENANT_REQUIRED", "Tenant users must create tenant-scoped templates")
    template_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        profile_id = payload.get("platform_profile_id") or None
        if profile_id:
            profile = _row_dict(conn.execute("SELECT id, tenant_id, platform_code, parser_platform FROM platform_profiles WHERE id = ?", (profile_id,)).fetchone())
            if not profile:
                raise PlatformRegistryError("PLATFORM_NOT_FOUND", "Platform profile not found", status_code=404)
            if profile.get("parser_platform") != platform_code:
                raise PlatformRegistryError("PARSER_PLATFORM_MISMATCH", "Template parser platform does not match the selected profile")
            if profile.get("tenant_id") and profile.get("tenant_id") != tenant_id and user.get("role") != "Administrator":
                raise PlatformRegistryError("PARSER_SCOPE_DENIED", "Platform profile is outside the current tenant scope", status_code=403)
        source = _source if _source in {"CUSTOM", "FORKED"} else "CUSTOM"
        conn.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, command, name, source, status, created_by, created_at, updated_at, lock_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, 1)""",
            (
                template_id, tenant_id or None, profile_id, platform_code, template_code,
                str(payload.get("source_filename") or ""), command, str(payload.get("name") or template_code),
                source, user.get("id") or user.get("username") or "", now, now,
            ),
        )
        _audit_parser_event(conn, template_id, None, "TEMPLATE_CREATED", user, {"source": source})
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM parser_templates WHERE id = ?", (template_id,)).fetchone()) or {}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_TEMPLATE_CREATE_FAILED", "Parser template could not be created") from exc
    finally:
        conn.close()


def update_template(template_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Update the identity/scope of a tenant-owned draft template."""
    platform_code = _validate_parser_platform(payload.get("platform_code"))
    template_code = validate_template_code(payload.get("template_code"))
    name = str(payload.get("name") or template_code).strip() or template_code
    profile_id = payload.get("platform_profile_id") or None
    expected_lock = payload.get("lock_version")
    conn = get_db_connection()
    try:
        template = _assert_template_access(conn, template_id, user)
        if template.get("source") == "SYSTEM":
            raise PlatformRegistryError(
                "SYSTEM_TEMPLATE_IMMUTABLE",
                "SYSTEM templates cannot be edited; create a tenant template instead",
                status_code=403,
            )
        raw_command = payload.get("command")
        command = normalize_parser_command(template.get("command") if raw_command is None else raw_command)
        lifecycle = conn.execute(
            "SELECT status FROM parser_template_versions WHERE template_id = ? AND status NOT IN ('DRAFT', 'DEPRECATED') LIMIT 1",
            (template_id,),
        ).fetchone()
        if lifecycle:
            raise PlatformRegistryError(
                "PARSER_TEMPLATE_IMMUTABLE",
                "Only templates with draft or deprecated versions can be edited",
                status_code=409,
            )
        tenant_id = template.get("tenant_id")
        if profile_id:
            profile = _row_dict(conn.execute(
                "SELECT id, tenant_id, parser_platform FROM platform_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone())
            if not profile:
                raise PlatformRegistryError("PLATFORM_NOT_FOUND", "Platform profile not found", status_code=404)
            if profile.get("parser_platform") != platform_code:
                raise PlatformRegistryError("PARSER_PLATFORM_MISMATCH", "Template parser platform does not match the selected profile")
            if profile.get("tenant_id") and profile.get("tenant_id") != tenant_id and user.get("role") != "Administrator":
                raise PlatformRegistryError("PARSER_SCOPE_DENIED", "Platform profile is outside the current tenant scope", status_code=403)
        duplicate = conn.execute(
            """SELECT id FROM parser_templates
               WHERE id <> ? AND (tenant_id = ? OR (tenant_id IS NULL AND ? IS NULL))
                 AND platform_code = ? AND template_code = ? LIMIT 1""",
            (template_id, tenant_id, tenant_id, platform_code, template_code),
        ).fetchone()
        if duplicate:
            raise PlatformRegistryError("PARSER_TEMPLATE_EXISTS", "A template with this code already exists", status_code=409)
        current_lock = int(template.get("lock_version") or 1)
        if expected_lock is not None and int(expected_lock) != current_lock:
            raise PlatformRegistryError("PARSER_TEMPLATE_CONFLICT", "The template changed since it was loaded; refresh before saving", status_code=409)
        next_lock = current_lock + 1
        now = _now()
        updated = conn.execute(
            """UPDATE parser_templates
               SET platform_profile_id = ?, platform_code = ?, template_code = ?, name = ?,
                   command = ?, lock_version = ?, updated_at = ?
               WHERE id = ? AND lock_version = ?""",
            (profile_id, platform_code, template_code, name, command, next_lock, now, template_id, current_lock),
        )
        if getattr(updated, "rowcount", 1) == 0:
            raise PlatformRegistryError("PARSER_TEMPLATE_CONFLICT", "The template changed since it was loaded; refresh before saving", status_code=409)
        _audit_parser_event(conn, template_id, None, "TEMPLATE_UPDATED", user, {"lock_version": next_lock})
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM parser_templates WHERE id = ?", (template_id,)).fetchone()) or {}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_TEMPLATE_UPDATE_FAILED", "Parser template could not be updated") from exc
    finally:
        conn.close()


def delete_template(template_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Delete an unused tenant template unless it has a published version."""
    conn = get_db_connection()
    try:
        template = _assert_template_access(conn, template_id, user)
        # SYSTEM is identified by its source marker, not by a nullable
        # tenant_id.  Older administrator sessions did not carry tenant
        # context when a fork was created, so valid FORKED/CUSTOM rows can
        # still have a NULL tenant_id and must remain deletable by an admin.
        if template.get("source") == "SYSTEM":
            raise PlatformRegistryError(
                "SYSTEM_TEMPLATE_IMMUTABLE",
                "SYSTEM templates cannot be deleted; create a tenant template instead",
                status_code=403,
            )
        if not template.get("tenant_id") and user.get("role") != "Administrator":
            raise PlatformRegistryError(
                "PARSER_SCOPE_DENIED",
                "A tenant-scoped parser template is required for this operation",
                status_code=403,
            )
        mapped = conn.execute(
            """SELECT COUNT(*) AS count
               FROM platform_release_actions a
               JOIN parser_template_versions v ON v.id = a.parser_template_version_id
               WHERE v.template_id = ?""",
            (template_id,),
        ).fetchone()
        if int((mapped["count"] if mapped else 0) or 0) > 0:
            raise PlatformRegistryError(
                "PARSER_TEMPLATE_IN_USE",
                "This template is referenced by a platform Release; replace the mapping before deleting it",
                status_code=409,
            )
        lifecycle = conn.execute(
            "SELECT status FROM parser_template_versions WHERE template_id = ? AND status = 'PUBLISHED' LIMIT 1",
            (template_id,),
        ).fetchone()
        if lifecycle:
            raise PlatformRegistryError(
                "PARSER_TEMPLATE_DELETE_BLOCKED",
                "Templates with published parser versions cannot be deleted",
                status_code=409,
            )
        deleted = conn.execute("DELETE FROM parser_templates WHERE id = ?", (template_id,))
        if getattr(deleted, "rowcount", 1) == 0:
            raise PlatformRegistryError("PARSER_TEMPLATE_NOT_FOUND", "Parser template not found", status_code=404)
        conn.commit()
        return {"id": template_id, "deleted": True}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_TEMPLATE_DELETE_FAILED", "Parser template could not be deleted") from exc
    finally:
        conn.close()


def fork_template(template_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Create a tenant-owned FORKED template from the latest SYSTEM version."""
    conn = get_db_connection()
    try:
        source = _row_dict(conn.execute("SELECT * FROM parser_templates WHERE id = ?", (template_id,)).fetchone())
        if not source:
            raise PlatformRegistryError("PARSER_TEMPLATE_NOT_FOUND", "Parser template not found", status_code=404)
        if source.get("source") != "SYSTEM" or source.get("tenant_id"):
            raise PlatformRegistryError("FORK_SOURCE_INVALID", "Only SYSTEM templates can be forked")
        version = _row_dict(conn.execute(
            """SELECT * FROM parser_template_versions
               WHERE template_id = ? AND status IN ('PUBLISHED', 'APPROVED', 'DRAFT')
               ORDER BY CASE status WHEN 'PUBLISHED' THEN 0 WHEN 'APPROVED' THEN 1 ELSE 2 END,
                        version_number DESC LIMIT 1""",
            (template_id,),
        ).fetchone())
        if not version:
            raise PlatformRegistryError("PARSER_VERSION_NOT_FOUND", "SYSTEM template has no version", status_code=404)
    finally:
        conn.close()

    new_template = create_template(
        {
            "platform_code": source["platform_code"],
            "template_code": payload.get("template_code"),
            "name": payload.get("name") or source.get("name") or source["template_code"],
            "source_filename": payload.get("source_filename") or source.get("source_filename") or "",
            "command": payload.get("command") or source.get("command") or "",
            "platform_profile_id": payload.get("platform_profile_id"),
        },
        user,
        _source="FORKED",
    )
    new_version = create_version(
        new_template["id"],
        {
            "content": version["content"],
            "field_contract": json.loads(version.get("field_contract_json") or "{}"),
        },
        user,
    )
    return {**new_template, "forked_from_template_id": template_id, "initial_version": new_version}


def create_version(template_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    content = str(payload.get("content") or "")
    if not content.strip():
        raise PlatformRegistryError("PARSER_CONTENT_REQUIRED", "Template content is required")
    field_contract = _validated_contract(payload.get("field_contract") or {})
    conn = get_db_connection()
    try:
        template = _assert_template_access(conn, template_id, user)
        if template.get("source") == "SYSTEM":
            raise PlatformRegistryError("SYSTEM_TEMPLATE_IMMUTABLE", "SYSTEM templates cannot be edited; create a tenant template instead", status_code=403)
        next_number = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_number FROM parser_template_versions WHERE template_id = ?",
            (template_id,),
        ).fetchone()["next_number"]
        version_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """INSERT INTO parser_template_versions
               (id, template_id, version_number, status, content, checksum,
                field_contract_json, test_summary_json, created_by, created_at, updated_at)
               VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?)""",
            (
                version_id, template_id, int(next_number), content, _checksum(content),
                json.dumps(field_contract, ensure_ascii=False),
                "{}", user.get("id") or user.get("username") or "", now, now,
            ),
        )
        _audit_parser_event(conn, template_id, version_id, "VERSION_CREATED", user, {"version_number": int(next_number)})
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()) or {}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_VERSION_CREATE_FAILED", "Parser template version could not be created") from exc
    finally:
        conn.close()


def update_version(version_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Update one mutable draft in place, with optimistic lock protection."""
    content = str(payload.get("content") or "")
    if not content.strip():
        raise PlatformRegistryError("PARSER_CONTENT_REQUIRED", "Template content is required")
    field_contract = _validated_contract(payload.get("field_contract") or {})
    expected_lock = payload.get("lock_version")
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, user)
        if row.get("status") != "DRAFT":
            raise PlatformRegistryError(
                "PARSER_VERSION_IMMUTABLE",
                "Only DRAFT parser versions can be edited in place",
                status_code=409,
            )
        if row.get("template_source") == "SYSTEM":
            raise PlatformRegistryError("SYSTEM_TEMPLATE_IMMUTABLE", "SYSTEM templates cannot be edited", status_code=403)
        current_lock = int(row.get("lock_version") or 1)
        if expected_lock is not None and int(expected_lock) != current_lock:
            raise PlatformRegistryError(
                "PARSER_VERSION_CONFLICT",
                "The draft changed since it was loaded; refresh before saving",
                status_code=409,
            )
        now = _now()
        next_lock = current_lock + 1
        updated = conn.execute(
            """UPDATE parser_template_versions
               SET content = ?, checksum = ?, field_contract_json = ?, test_summary_json = '{}',
                   lock_version = ?, updated_at = ?
               WHERE id = ? AND status = 'DRAFT' AND lock_version = ?""",
            (
                content, _checksum(content), json.dumps(field_contract, ensure_ascii=False),
                next_lock, now, version_id, current_lock,
            ),
        )
        if getattr(updated, "rowcount", 1) == 0:
            raise PlatformRegistryError("PARSER_VERSION_CONFLICT", "The draft changed since it was loaded", status_code=409)
        _audit_parser_event(conn, str(row["template_id"]), version_id, "VERSION_UPDATED", user, {"lock_version": next_lock})
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()) or {}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_VERSION_UPDATE_FAILED", "Parser draft could not be updated") from exc
    finally:
        conn.close()


def list_versions(template_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        _assert_template_access(conn, template_id, user)
        rows = conn.execute(
            "SELECT * FROM parser_template_versions WHERE template_id = ? ORDER BY version_number DESC",
            (template_id,),
        ).fetchall()
        return [_row_dict(row) or {} for row in rows]
    finally:
        conn.close()


def _parse_and_validate(content: str, sample_output: str, contract_value: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = _validated_contract(contract_value)
    try:
        records = parse_template_in_sandbox(
            content, sample_output,
            timeout_seconds=30, max_template_bytes=256_000,
            max_output_bytes=2_000_000, max_records=1_000, max_fields=128,
        )
    except TextFSMSandboxError as exc:
        raise PlatformRegistryError(exc.code, exc.message, status_code=422) from exc
    expected_fields = set(contract.get("required") or []) | set(contract.get("optional") or []) | set((contract.get("types") or {}).keys())
    normalized = _normalize_records(records, 1_000, expected_fields=expected_fields)
    _coerce_field_types(normalized, contract)
    if contract.get("required") and not normalized:
        raise PlatformRegistryError("FIELD_CONTRACT_VIOLATION", "The sample produced no records for a required field contract")
    _validate_field_contract(normalized, contract)
    return normalized, contract


def sandbox_test(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Parse editor content without requiring a persisted mutable version.

    ``persist`` only updates a DRAFT owned by the caller.  A SYSTEM/PUBLISHED
    version can therefore be tested safely with new sample text while its
    immutable record remains unchanged.
    """
    version_id = str(payload.get("version_id") or "")
    content = str(payload.get("content") or "")
    contract_value: Any = payload.get("field_contract") or {}
    conn = get_db_connection()
    try:
        row: dict[str, Any] | None = None
        if version_id:
            row = _load_version(conn, version_id, user)
            if not content:
                content = str(row.get("content") or "")
            if not contract_value:
                contract_value = row.get("field_contract_json") or "{}"
        if not content.strip():
            raise PlatformRegistryError("PARSER_CONTENT_REQUIRED", "Template content is required")
        sample_output = str(payload.get("sample_output") or "")
        if not sample_output:
            raise PlatformRegistryError("SAMPLE_OUTPUT_REQUIRED", "sample_output is required")
        started = time.perf_counter()
        records, contract = _parse_and_validate(content, sample_output, contract_value)
        summary = _summary_for_records(records, contract, round((time.perf_counter() - started) * 1000))
        persist = bool(payload.get("persist"))
        if persist:
            if not row:
                raise PlatformRegistryError("PARSER_VERSION_REQUIRED", "A draft version is required to persist a sandbox test", status_code=409)
            if row.get("status") != "DRAFT" or row.get("template_source") == "SYSTEM":
                raise PlatformRegistryError("PARSER_VERSION_IMMUTABLE", "Only tenant DRAFT versions can persist sandbox changes", status_code=409)
            expected_lock = payload.get("lock_version")
            current_lock = int(row.get("lock_version") or 1)
            if expected_lock is not None and int(expected_lock) != current_lock:
                raise PlatformRegistryError("PARSER_VERSION_CONFLICT", "The draft changed since it was loaded", status_code=409)
            next_lock = current_lock + 1
            updated = conn.execute(
                """UPDATE parser_template_versions
                   SET content = ?, checksum = ?, field_contract_json = ?, test_summary_json = ?,
                       lock_version = ?, updated_at = ?
                   WHERE id = ? AND status = 'DRAFT' AND lock_version = ?""",
                (
                    content, _checksum(content), json.dumps(contract, ensure_ascii=False),
                    json.dumps(summary, ensure_ascii=False), next_lock, _now(), version_id, current_lock,
                ),
            )
            if getattr(updated, "rowcount", 1) == 0:
                raise PlatformRegistryError("PARSER_VERSION_CONFLICT", "The draft changed since it was loaded", status_code=409)
            _audit_parser_event(conn, str(row["template_id"]), version_id, "SANDBOX_PERSISTED", user, {"record_count": len(records), "lock_version": next_lock})
        conn.commit()
        return {
            "version_id": version_id or None,
            "success": True,
            "records": records,
            "count": len(records),
            "fields": summary["fields"],
            "summary": summary,
        }
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_TEST_FAILED", "Parser template test failed") from exc
    finally:
        conn.close()


def _run_sample_regression(conn, row: dict[str, Any]) -> int:
    samples = conn.execute(
        "SELECT sample_output, sample_output_encrypted FROM parser_test_samples WHERE template_version_id = ? ORDER BY created_at",
        (row["id"],),
    ).fetchall()
    for sample in samples:
        try:
            raw_output = load_output(sample["sample_output_encrypted"], sample["sample_output"])
        except Exception as exc:
            raise PlatformRegistryError("PARSER_SAMPLE_UNAVAILABLE", "A historical parser sample could not be decrypted", status_code=409) from exc
        if not isinstance(raw_output, str):
            raise PlatformRegistryError("PARSER_SAMPLE_INVALID", "A historical parser sample is not CLI text", status_code=409)
        _parse_and_validate(row["content"], raw_output, row.get("field_contract_json"))
    return len(samples)


def run_published_version_regression(conn, version_id: str) -> dict[str, Any]:
    """Run every retained sample for a release-bound published parser version.

    This is read-only with respect to the parser version and samples.  Release
    validation uses it as a fail-closed gate before approval or publication.
    """
    row = _row_dict(conn.execute(
        "SELECT * FROM parser_template_versions WHERE id = ?",
        (version_id,),
    ).fetchone())
    if not row:
        raise PlatformRegistryError("PARSER_VERSION_NOT_FOUND", "Release parser version not found", status_code=409)
    if row.get("status") != "PUBLISHED":
        raise PlatformRegistryError("PARSER_VERSION_NOT_PUBLISHED", "Release parser version is not published", status_code=409)
    sample_count = _run_sample_regression(conn, row)
    return {
        "version_id": version_id,
        "sample_count": sample_count,
        "passed": True,
    }


def test_version(version_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    sample_output = str(payload.get("sample_output") or "")
    if not sample_output:
        raise PlatformRegistryError("SAMPLE_OUTPUT_REQUIRED", "sample_output is required")
    conn = get_db_connection()
    try:
        row = _row_dict(conn.execute(
            """SELECT v.*, t.id AS template_id, t.tenant_id, t.source
               FROM parser_template_versions v JOIN parser_templates t ON t.id = v.template_id
               WHERE v.id = ?""",
            (version_id,),
        ).fetchone())
        if not row:
            raise PlatformRegistryError("PARSER_VERSION_NOT_FOUND", "Parser template version not found", status_code=404)
        _assert_template_access(conn, str(row["template_id"]), user)
        if row.get("status") in {"PUBLISHED", "DEPRECATED"}:
            raise PlatformRegistryError("PARSER_VERSION_IMMUTABLE", "Published parser versions cannot be retested in place", status_code=409)
        started = time.perf_counter()
        records, contract = _parse_and_validate(row["content"], sample_output, row.get("field_contract_json"))
        summary = _summary_for_records(records, contract, round((time.perf_counter() - started) * 1000))
        conn.execute(
            "UPDATE parser_template_versions SET test_summary_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(summary, ensure_ascii=False), _now(), version_id),
        )
        _audit_parser_event(conn, str(row["template_id"]), version_id, "SANDBOX_TESTED", user, {"record_count": len(records)})
        conn.commit()
        return {"version_id": version_id, "success": True, "records": records, "count": len(records), "fields": summary["fields"], "summary": summary}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_TEST_FAILED", "Parser template test failed") from exc
    finally:
        conn.close()


def _transition_version(version_id: str, event: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, user)
        transitions = {
            "submit": ("DRAFT", "IN_REVIEW"),
            "withdraw": ("IN_REVIEW", "DRAFT"),
            "approve": ("IN_REVIEW", "APPROVED"),
            "reject": ("IN_REVIEW", "DRAFT"),
            "publish": ("APPROVED", "PUBLISHED"),
        }
        expected, target = transitions.get(event, ("", ""))
        if not expected:
            raise PlatformRegistryError("INVALID_PARSER_EVENT", "Unsupported parser version event")
        if row.get("status") != expected:
            raise PlatformRegistryError(
                "INVALID_PARSER_STATE",
                f"Parser version must be {expected} before {event}",
                status_code=409,
            )
        if event == "withdraw":
            actor = _actor_key(user)
            authors = {
                str(row.get("submitted_by") or ""),
                str(row.get("created_by") or ""),
            } - {""}
            if actor not in authors:
                raise PlatformRegistryError(
                    "PARSER_WITHDRAW_FORBIDDEN",
                    "Only the submitter can withdraw an in-review parser version",
                    status_code=403,
                )
        if event in {"approve", "reject", "publish"}:
            _require_administrator(user)
        if event in {"approve", "reject"} and row.get("created_by") == _actor_key(user):
            if event == "approve":
                raise PlatformRegistryError(
                    "SELF_APPROVAL_FORBIDDEN",
                    "The creator cannot approve their own parser version",
                    status_code=403,
                )
            raise PlatformRegistryError(
                "SELF_REVIEW_FORBIDDEN",
                "The creator cannot reject their own parser version",
                status_code=403,
            )
        sandbox_summary = None
        if event in {"submit", "approve", "publish"}:
            sandbox_summary = _require_sandbox_pass(row, event)
        if event == "reject":
            now = _now()
            conn.execute(
                """UPDATE parser_template_versions
                   SET status = 'DRAFT', approved_by = '',
                       lock_version = COALESCE(lock_version, 1) + 1,
                       updated_at = ? WHERE id = ?""",
                (now, version_id),
            )
            metadata = {"from": expected, "to": target}
            if str(reason or "").strip():
                metadata["reason"] = str(reason).strip()[:2000]
            _audit_parser_event(conn, str(row["template_id"]), version_id, "VERSION_REJECTED", user, metadata)
            conn.commit()
            return _row_dict(conn.execute("SELECT * FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()) or {}
        if event == "withdraw":
            now = _now()
            conn.execute(
                """UPDATE parser_template_versions
                   SET status = 'DRAFT', approved_by = '',
                       lock_version = COALESCE(lock_version, 1) + 1,
                       updated_at = ? WHERE id = ?""",
                (now, version_id),
            )
            _audit_parser_event(
                conn,
                str(row["template_id"]),
                version_id,
                "VERSION_WITHDRAWN",
                user,
                {"from": expected, "to": target},
            )
            conn.commit()
            return _row_dict(conn.execute("SELECT * FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()) or {}
        if event == "publish":
            summary = sandbox_summary or _require_sandbox_pass(row, event)
            regression_count = _run_sample_regression(conn, row)
            summary["regression_count"] = regression_count
            summary["regression_passed"] = True
            conn.execute(
                "UPDATE parser_template_versions SET test_summary_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(summary, ensure_ascii=False), _now(), version_id),
            )
            conn.execute(
                """UPDATE parser_template_versions
                   SET status = 'DEPRECATED', updated_at = ?
                   WHERE template_id = ? AND status = 'PUBLISHED' AND id <> ?""",
                (_now(), row["template_id"], version_id),
            )
            _audit_parser_event(conn, str(row["template_id"]), version_id, "VERSION_PUBLISHED_PREPARE", user, {"regression_count": regression_count})
        now = _now()
        audit_column = {
            "submit": "submitted_by",
            "approve": "approved_by",
            "publish": "published_by",
        }[event]
        conn.execute(
            f"UPDATE parser_template_versions SET status = ?, {audit_column} = ?, "
            "lock_version = COALESCE(lock_version, 1) + 1, updated_at = ? WHERE id = ?",
            (target, _actor_key(user), now, version_id),
        )
        metadata = {"from": expected, "to": target}
        if str(reason or "").strip():
            metadata["reason"] = str(reason).strip()[:2000]
        _audit_parser_event(conn, str(row["template_id"]), version_id, f"VERSION_{event.upper()}", user, metadata)
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()) or {}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_LIFECYCLE_FAILED", "Parser version lifecycle operation failed") from exc
    finally:
        conn.close()


def submit_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition_version(version_id, "submit", user)


def withdraw_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition_version(version_id, "withdraw", user)


def approve_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition_version(version_id, "approve", user)


def reject_version(version_id: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    return _transition_version(version_id, "reject", user, reason=reason)


def publish_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition_version(version_id, "publish", user)


def rollback_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Promote a previously deprecated tenant version back to PUBLISHED."""
    _release_manager_or_administrator(user)
    conn = get_db_connection()
    try:
        target = _load_version(conn, version_id, user)
        if target.get("template_source") == "SYSTEM":
            raise PlatformRegistryError("SYSTEM_TEMPLATE_IMMUTABLE", "SYSTEM parser versions cannot be rolled back", status_code=403)
        if target.get("status") != "DEPRECATED":
            raise PlatformRegistryError("INVALID_ROLLBACK_TARGET", "Only a DEPRECATED parser version can be rolled back", status_code=409)
        current = _row_dict(conn.execute(
            "SELECT * FROM parser_template_versions WHERE template_id = ? AND status = 'PUBLISHED' ORDER BY version_number DESC LIMIT 1",
            (target["template_id"],),
        ).fetchone())
        now = _now()
        if current:
            conn.execute(
                "UPDATE parser_template_versions SET status = 'DEPRECATED', updated_at = ?, lock_version = COALESCE(lock_version, 1) + 1 WHERE id = ?",
                (now, current["id"]),
            )
            _audit_parser_event(conn, str(target["template_id"]), str(current["id"]), "VERSION_DEPRECATED", user, {"reason": "rollback"})
        conn.execute(
            "UPDATE parser_template_versions SET status = 'PUBLISHED', published_by = ?, updated_at = ?, lock_version = COALESCE(lock_version, 1) + 1 WHERE id = ?",
            (_actor_key(user), now, version_id),
        )
        _audit_parser_event(conn, str(target["template_id"]), version_id, "VERSION_ROLLED_BACK", user, {"previous_version_id": current["id"] if current else None})
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()) or {}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_ROLLBACK_FAILED", "Parser version rollback failed") from exc
    finally:
        conn.close()


def deprecate_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    _release_manager_or_administrator(user)
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, user)
        if row.get("template_source") == "SYSTEM":
            raise PlatformRegistryError("SYSTEM_TEMPLATE_IMMUTABLE", "SYSTEM parser versions cannot be deprecated", status_code=403)
        if row.get("status") != "PUBLISHED":
            raise PlatformRegistryError("INVALID_PARSER_STATE", "Only a PUBLISHED parser version can be deprecated", status_code=409)
        now = _now()
        conn.execute(
            "UPDATE parser_template_versions SET status = 'DEPRECATED', updated_at = ?, lock_version = COALESCE(lock_version, 1) + 1 WHERE id = ?",
            (now, version_id),
        )
        _audit_parser_event(conn, str(row["template_id"]), version_id, "VERSION_DEPRECATED", user, {})
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()) or {}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_DEPRECATE_FAILED", "Parser version deprecation failed") from exc
    finally:
        conn.close()


def create_sample(version_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    sample_output = str(payload.get("sample_output") or "")
    if not sample_output:
        raise PlatformRegistryError("SAMPLE_OUTPUT_REQUIRED", "sample_output is required")
    expected_records = payload.get("expected_records") or []
    if not isinstance(expected_records, list):
        raise PlatformRegistryError("EXPECTED_RECORDS_INVALID", "expected_records must be a list")
    conn = get_db_connection()
    try:
        version = _load_version(conn, version_id, user)
        if version.get("status") in {"PUBLISHED", "DEPRECATED"}:
            raise PlatformRegistryError("PARSER_VERSION_IMMUTABLE", "Published parser versions cannot receive new samples", status_code=409)
        ciphertext, placeholder, expiry, encrypted = protect_output(sample_output)
        if not encrypted or not ciphertext:
            raise PlatformRegistryError(
                "OUTPUT_ENCRYPTION_UNAVAILABLE",
                "Sample output encryption is unavailable; the sample was not stored",
                status_code=503,
            )
        sample_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """INSERT INTO parser_test_samples
               (id, template_version_id, sample_name, sample_output,
                sample_output_encrypted, raw_output_expires_at,
                expected_records_json, checksum, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sample_id, version_id, str(payload.get("sample_name") or f"sample-{sample_id[:8]}"),
                placeholder, ciphertext, expiry,
                json.dumps(expected_records, ensure_ascii=False), _checksum(sample_output),
                _actor_key(user), now,
            ),
        )
        _audit_parser_event(conn, str(version["template_id"]), version_id, "SAMPLE_CREATED", user, {"sample_id": sample_id, "sample_name": str(payload.get("sample_name") or "")})
        conn.commit()
        return {
            "id": sample_id,
            "template_version_id": version_id,
            "sample_name": str(payload.get("sample_name") or f"sample-{sample_id[:8]}"),
            "checksum": _checksum(sample_output),
            "raw_output_expires_at": expiry,
            "encrypted": True,
        }
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_SAMPLE_CREATE_FAILED", "Parser test sample could not be stored") from exc
    finally:
        conn.close()


def delete_sample(sample_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _row_dict(conn.execute(
            """SELECT s.*, v.template_id, v.status AS version_status, t.source AS template_source
               FROM parser_test_samples s
               JOIN parser_template_versions v ON v.id = s.template_version_id
               JOIN parser_templates t ON t.id = v.template_id
               WHERE s.id = ?""",
            (sample_id,),
        ).fetchone())
        if not row:
            raise PlatformRegistryError("PARSER_SAMPLE_NOT_FOUND", "Parser test sample not found", status_code=404)
        _assert_template_access(conn, str(row["template_id"]), user)
        if row.get("version_status") in {"PUBLISHED", "DEPRECATED"} or row.get("template_source") == "SYSTEM":
            raise PlatformRegistryError("PARSER_VERSION_IMMUTABLE", "Published parser samples cannot be deleted", status_code=409)
        conn.execute("DELETE FROM parser_test_samples WHERE id = ?", (sample_id,))
        _audit_parser_event(conn, str(row["template_id"]), str(row["template_version_id"]), "SAMPLE_DELETED", user, {"sample_id": sample_id})
        conn.commit()
        return {"id": sample_id, "deleted": True}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_SAMPLE_DELETE_FAILED", "Parser test sample could not be deleted") from exc
    finally:
        conn.close()


def list_samples(version_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        _load_version(conn, version_id, user)
        rows = conn.execute(
            """SELECT id, template_version_id, sample_name, expected_records_json,
                      checksum, created_by, created_at, raw_output_expires_at
               FROM parser_test_samples
               WHERE template_version_id = ? ORDER BY created_at DESC""",
            (version_id,),
        ).fetchall()
        return [_row_dict(row) or {} for row in rows]
    finally:
        conn.close()


def list_audit_logs(template_id: str, user: dict[str, Any], *, limit: int = 100) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        _assert_template_access(conn, template_id, user)
        safe_limit = min(200, max(1, int(limit or 100)))
        rows = conn.execute(
            """SELECT id, template_id, version_id, event_type, actor_id, actor_username, metadata_json, created_at
               FROM parser_template_audit_logs
               WHERE template_id = ? ORDER BY created_at DESC LIMIT ?""",
            (template_id, safe_limit),
        ).fetchall()
        return [_row_dict(row) or {} for row in rows]
    finally:
        conn.close()


def list_version_mappings(version_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the release actions that currently reference one parser version.

    The parser registry owns the version, while the platform registry owns the
    command binding.  Keeping this read model here lets the TextFSM page show
    the complete relationship without exposing mappings from another tenant.
    SYSTEM profile mappings remain visible because they are global read-only
    definitions, matching the platform registry's normal read scope.
    """
    conn = get_db_connection()
    try:
        _load_version(conn, version_id, user)
        tenant_id = str(user.get("tenant_id") or "")
        scope_clause = ""
        scope_params: list[Any] = []
        if tenant_id:
            scope_clause = "AND (p.tenant_id IS NULL OR p.tenant_id = ?)"
            scope_params.append(tenant_id)
        rows = conn.execute(
            f"""SELECT a.id, a.action_code, a.command, a.parser_template_version_id,
                       a.field_contract_json, a.command_checksum,
                       t.command AS template_command, t.source_filename AS template_source_filename,
                       r.id AS release_id, r.release_number, r.status AS release_status,
                       r.validation_status AS release_validation_status,
                       p.id AS profile_id, p.platform_code, p.parser_platform,
                       p.name_zh AS profile_name_zh, p.name_en AS profile_name_en,
                       p.vendor AS profile_vendor, p.source AS profile_source,
                       p.tenant_id AS profile_tenant_id
                FROM platform_release_actions a
                JOIN platform_releases r ON r.id = a.release_id
                JOIN platform_profiles p ON p.id = r.profile_id
                JOIN parser_template_versions pv ON pv.id = a.parser_template_version_id
                JOIN parser_templates t ON t.id = pv.template_id
                WHERE a.parser_template_version_id = ?
                  AND p.status <> 'ARCHIVED'
                  {scope_clause}
                ORDER BY CASE r.status WHEN 'PUBLISHED' THEN 0 WHEN 'APPROVED' THEN 1
                                      WHEN 'IN_REVIEW' THEN 2 WHEN 'DRAFT' THEN 3 ELSE 4 END,
                         p.platform_code, r.release_number DESC, a.action_code""",
            [version_id, *scope_params],
        ).fetchall()
        return [_row_dict(row) or {} for row in rows]
    finally:
        conn.close()


def template_impact(template_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Summarize downstream release/device references before lifecycle changes."""
    conn = get_db_connection()
    try:
        template = _assert_template_access(conn, template_id, user)
        version_ids = [str(row[0]) for row in conn.execute(
            "SELECT id FROM parser_template_versions WHERE template_id = ?", (template_id,)
        ).fetchall()]
        if not version_ids:
            return {
                "template_id": template_id, "template_code": template.get("template_code"),
                "version_count": 0, "action_count": 0, "release_count": 0,
                "profile_count": 0, "device_count": 0, "playbook_count": 0,
            }
        placeholders = ",".join("?" for _ in version_ids)
        action_row = conn.execute(
            f"""SELECT COUNT(*) AS action_count,
                       COUNT(DISTINCT a.release_id) AS release_count,
                       COUNT(DISTINCT r.profile_id) AS profile_count
                FROM platform_release_actions a
                JOIN platform_releases r ON r.id = a.release_id
                WHERE a.parser_template_version_id IN ({placeholders})""",
            version_ids,
        ).fetchone()
        device_count = 0
        try:
            device_row = conn.execute(
                f"SELECT COUNT(DISTINCT d.id) AS device_count FROM devices d WHERE d.platform_release_id IN (SELECT release_id FROM platform_release_actions WHERE parser_template_version_id IN ({placeholders}))",
                version_ids,
            ).fetchone()
            device_count = int((device_row["device_count"] if device_row else 0) or 0)
        except Exception:
            # Older installations do not have a release binding column on devices.
            device_count = 0
        playbook_count = 0
        try:
            playbook_row = conn.execute(
                f"SELECT COUNT(DISTINCT platform_release_id) AS playbook_count FROM playbook_versions WHERE platform_release_id IN (SELECT release_id FROM platform_release_actions WHERE parser_template_version_id IN ({placeholders}))",
                version_ids,
            ).fetchone()
            playbook_count = int((playbook_row["playbook_count"] if playbook_row else 0) or 0)
        except Exception:
            playbook_count = 0
        return {
            "template_id": template_id,
            "template_code": template.get("template_code"),
            "version_count": len(version_ids),
            "action_count": int((action_row["action_count"] if action_row else 0) or 0),
            "release_count": int((action_row["release_count"] if action_row else 0) or 0),
            "profile_count": int((action_row["profile_count"] if action_row else 0) or 0),
            "device_count": device_count,
            "playbook_count": playbook_count,
        }
    finally:
        conn.close()


def regression_test_template(template_id: str, user: dict[str, Any], *, version_id: str = "") -> dict[str, Any]:
    """Run every encrypted historical sample against one mutable template version.

    This is intentionally read-only with respect to samples and version content;
    it provides an explicit pre-submit/pre-publish gate for UI and CI callers.
    """
    conn = get_db_connection()
    try:
        template = _assert_template_access(conn, template_id, user)
        if version_id:
            row = _row_dict(conn.execute(
                "SELECT * FROM parser_template_versions WHERE id = ? AND template_id = ?",
                (version_id, template_id),
            ).fetchone())
        else:
            row = _row_dict(conn.execute(
                "SELECT * FROM parser_template_versions WHERE template_id = ? "
                "ORDER BY CASE status WHEN 'DRAFT' THEN 0 WHEN 'IN_REVIEW' THEN 1 "
                "WHEN 'APPROVED' THEN 2 WHEN 'PUBLISHED' THEN 3 ELSE 4 END, version_number DESC LIMIT 1",
                (template_id,),
            ).fetchone())
        if not row:
            raise PlatformRegistryError("PARSER_VERSION_NOT_FOUND", "Parser template version not found", status_code=404)
        if row.get("status") in {"PUBLISHED", "DEPRECATED"}:
            raise PlatformRegistryError(
                "PARSER_VERSION_IMMUTABLE",
                "Published parser versions cannot be regression-tested in place",
                status_code=409,
            )
        count = _run_sample_regression(conn, row)
        return {
            "template_id": template_id,
            "version_id": row["id"],
            "version_number": row.get("version_number"),
            "status": row.get("status"),
            "sample_count": count,
            "passed": True,
        }
    finally:
        conn.close()
