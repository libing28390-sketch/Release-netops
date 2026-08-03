"""Tenant-scoped parser template development services for P1."""

from __future__ import annotations

import hashlib
import json
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
    normalize_platform_code,
    validate_platform_code,
    validate_template_code,
)
from services.textfsm_sandbox_service import TextFSMSandboxError, parse_template_in_sandbox


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _actor_key(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("username") or "")


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


def list_templates(user: dict[str, Any], *, platform_code: str = "") -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        tenant_id = str(user.get("tenant_id") or "")
        clauses = ["status <> 'ARCHIVED'"]
        params: list[Any] = []
        if user.get("role") != "Administrator" or tenant_id:
            clauses.insert(0, "(tenant_id IS NULL OR tenant_id = ?)")
            params.append(tenant_id)
        if platform_code:
            clauses.append("platform_code = ?")
            params.append(normalize_platform_code(platform_code))
        rows = conn.execute(
            "SELECT * FROM parser_templates WHERE " + " AND ".join(clauses) + " ORDER BY source, platform_code, template_code",
            params,
        ).fetchall()
        return [_row_dict(row) or {} for row in rows]
    finally:
        conn.close()


def create_template(payload: dict[str, Any], user: dict[str, Any], *, _source: str = "CUSTOM") -> dict[str, Any]:
    platform_code = validate_platform_code(payload.get("platform_code"))
    template_code = validate_template_code(payload.get("template_code"))
    tenant_id = str(user.get("tenant_id") or "")
    if not tenant_id and user.get("role") != "Administrator":
        raise PlatformRegistryError("TENANT_REQUIRED", "Tenant users must create tenant-scoped templates")
    template_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        profile_id = payload.get("platform_profile_id") or None
        if profile_id:
            profile = _row_dict(conn.execute("SELECT id, tenant_id, platform_code FROM platform_profiles WHERE id = ?", (profile_id,)).fetchone())
            if not profile:
                raise PlatformRegistryError("PLATFORM_NOT_FOUND", "Platform profile not found", status_code=404)
            if profile.get("platform_code") != platform_code:
                raise PlatformRegistryError("PARSER_PLATFORM_MISMATCH", "Template platform does not match the selected profile")
            if profile.get("tenant_id") and profile.get("tenant_id") != tenant_id and user.get("role") != "Administrator":
                raise PlatformRegistryError("PARSER_SCOPE_DENIED", "Platform profile is outside the current tenant scope", status_code=403)
        source = _source if _source in {"CUSTOM", "FORKED"} else "CUSTOM"
        conn.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, name, source, status, created_by, created_at, updated_at, lock_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, 1)""",
            (
                template_id, tenant_id or None, profile_id, platform_code, template_code,
                str(payload.get("source_filename") or ""), str(payload.get("name") or template_code),
                source, user.get("id") or user.get("username") or "", now, now,
            ),
        )
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
        records, contract = _parse_and_validate(row["content"], sample_output, row.get("field_contract_json"))
        fields = sorted({str(key) for record in records for key in record})
        coverage = {
            field: sum(1 for record in records if record.get(field) not in (None, "")) / len(records)
            if records else 0
            for field in sorted(set(contract.get("required") or []) | set(contract.get("optional") or []) | set((contract.get("types") or {}).keys()))
        }
        summary = {
            "passed": True, "record_count": len(records), "fields": fields,
            "field_coverage": coverage, "field_contract": contract, "tested_at": _now(),
        }
        conn.execute(
            "UPDATE parser_template_versions SET test_summary_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(summary, ensure_ascii=False), _now(), version_id),
        )
        conn.commit()
        return {"version_id": version_id, "success": True, "records": records, "count": len(records), "fields": fields, "summary": summary}
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PARSER_TEST_FAILED", "Parser template test failed") from exc
    finally:
        conn.close()


def _transition_version(version_id: str, event: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, user)
        transitions = {
            "submit": ("DRAFT", "IN_REVIEW"),
            "approve": ("IN_REVIEW", "APPROVED"),
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
        if event in {"approve", "publish"}:
            _require_administrator(user)
        if event == "approve" and row.get("created_by") == _actor_key(user):
            raise PlatformRegistryError(
                "SELF_APPROVAL_FORBIDDEN",
                "The creator cannot approve their own parser version",
                status_code=403,
            )
        if event == "publish":
            try:
                summary = json.loads(row.get("test_summary_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                summary = {}
            if summary.get("passed") is not True:
                raise PlatformRegistryError(
                    "PARSER_TEST_REQUIRED",
                    "Parser version must pass a sandbox test before publication",
                    status_code=409,
                )
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


def approve_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition_version(version_id, "approve", user)


def publish_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition_version(version_id, "publish", user)


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
