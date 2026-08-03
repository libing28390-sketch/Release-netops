"""Playbook version lifecycle and scope rules.

The service owns the immutable definition and status transitions.  HTTP
routes only translate the service errors into the public API contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection


class PlaybookVersionError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_PLAYBOOK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _registry_enabled() -> bool:
    return os.environ.get("PLATFORM_REGISTRY_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _row(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _actor_key(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("username") or "")


def _assert_playbook_id(playbook_id: str) -> str:
    value = str(playbook_id or "").strip()
    if not _PLAYBOOK_ID_RE.fullmatch(value):
        raise PlaybookVersionError("INVALID_PLAYBOOK_ID", "Invalid playbook id")
    return value


def _assert_scope(row: dict[str, Any], user: dict[str, Any]) -> None:
    row_tenant = str(row.get("tenant_id") or "")
    user_tenant = str(user.get("tenant_id") or "")
    if row_tenant and row_tenant != user_tenant and user.get("role") != "Administrator":
        raise PlaybookVersionError("PLAYBOOK_SCOPE_DENIED", "Playbook version is outside the current tenant scope", status_code=403)
    if not row_tenant and user.get("role") != "Administrator" and not user_tenant:
        raise PlaybookVersionError("PLAYBOOK_SCOPE_DENIED", "A tenant-scoped user is required", status_code=403)


def _release_lock_suffix() -> str:
    import database as database_module
    return " FOR UPDATE" if database_module._USE_PG else ""


def _load_version(conn, version_id: str, *, lock: bool = False) -> dict[str, Any]:
    suffix = _release_lock_suffix() if lock else ""
    row = _row(conn.execute(f"SELECT * FROM playbook_versions WHERE id = ?{suffix}", (version_id,)).fetchone())
    if not row:
        raise PlaybookVersionError("PLAYBOOK_VERSION_NOT_FOUND", "Playbook version not found", status_code=404)
    return row


def _definition_from_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("definition_json") or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise PlaybookVersionError("INVALID_PLAYBOOK_DEFINITION", "Playbook definition is not valid JSON") from exc
    if not isinstance(value, dict):
        raise PlaybookVersionError("INVALID_PLAYBOOK_DEFINITION", "Playbook definition must be an object")
    return value


def _validate_definition(definition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(definition, dict):
        raise PlaybookVersionError("INVALID_PLAYBOOK_DEFINITION", "Playbook definition must be an object")
    normalized = dict(definition)
    if "phases" not in normalized and isinstance(normalized.get("platform_phases"), dict):
        normalized["phases"] = normalized["platform_phases"]
    phases = normalized.get("phases")
    if not isinstance(phases, dict):
        raise PlaybookVersionError("INVALID_PLAYBOOK_DEFINITION", "Playbook definition must include phases")
    if _registry_enabled():
        from api.playbooks.scenarios import validate_controlled_phases
        errors = validate_controlled_phases(phases)
        if errors:
            raise PlaybookVersionError(
                str(errors[0].get("code") or "INVALID_PLAYBOOK_DEFINITION"),
                "Platform registry is enabled; Playbook steps must use bounded published action definitions",
            )
    return normalized


def _audit(conn, row: dict[str, Any], event: str, user: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    conn.execute(
        """INSERT INTO playbook_release_audit_logs
           (id, playbook_id, playbook_version_id, event_type, actor_id, actor_username,
            platform_release_ids_json, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?)""",
        (
            str(uuid.uuid4()),
            row.get("playbook_id"),
            row.get("id"),
            event,
            user.get("id"),
            user.get("username"),
            _json(metadata or {}),
            _now(),
        ),
    )


def list_versions(playbook_id: str, user: dict[str, Any], *, include_snapshots: bool = False) -> list[dict[str, Any]]:
    playbook_id = _assert_playbook_id(playbook_id)
    conn = get_db_connection()
    try:
        params: list[Any] = [playbook_id]
        where = "playbook_id = ?"
        if user.get("role") != "Administrator":
            tenant_id = str(user.get("tenant_id") or "")
            if not tenant_id:
                raise PlaybookVersionError("PLAYBOOK_SCOPE_DENIED", "A tenant-scoped user is required", status_code=403)
            where += " AND (tenant_id IS NULL OR tenant_id = ?)"
            params.append(tenant_id)
        if not include_snapshots:
            where += " AND status <> 'SNAPSHOT'"
        rows = conn.execute(f"SELECT * FROM playbook_versions WHERE {where} ORDER BY version_number DESC", params).fetchall()
        result = []
        for item in rows:
            value = dict(item)
            try:
                value["definition"] = json.loads(value.pop("definition_json") or "{}")
                value["validation_result"] = json.loads(value.pop("validation_result_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                value["definition"] = {}
                value["validation_result"] = {}
            result.append(value)
        return result
    finally:
        conn.close()


def get_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id)
        _assert_scope(row, user)
        value = dict(row)
        value["definition"] = _definition_from_row(row)
        try:
            value["validation_result"] = json.loads(row.get("validation_result_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            value["validation_result"] = {}
        value.pop("definition_json", None)
        value.pop("validation_result_json", None)
        return value
    finally:
        conn.close()


def create_version(playbook_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    playbook_id = _assert_playbook_id(playbook_id)
    definition = _validate_definition(payload.get("definition") or payload)
    name = str(payload.get("name") or definition.get("name") or playbook_id).strip()[:200]
    if not name:
        raise PlaybookVersionError("INVALID_PLAYBOOK_NAME", "Playbook version name is required")
    tenant_id = str(user.get("tenant_id") or "") or None
    if user.get("role") != "Administrator" and not tenant_id:
        raise PlaybookVersionError("PLAYBOOK_SCOPE_DENIED", "A tenant-scoped user is required", status_code=403)
    conn = get_db_connection()
    try:
        next_row = conn.execute("SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version FROM playbook_versions WHERE playbook_id = ?", (playbook_id,)).fetchone()
        version_number = int(next_row["next_version"] if next_row else 1)
        now = _now()
        row = {
            "id": str(uuid.uuid4()),
            "playbook_id": playbook_id,
            "tenant_id": tenant_id,
            "version_number": version_number,
            "status": "DRAFT",
            "name": name,
            "definition_json": _json(definition),
            "checksum": _checksum(definition),
            "created_by": _actor_key(user),
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """INSERT INTO playbook_versions
               (id, playbook_id, tenant_id, version_number, status, name, definition_json,
                checksum, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?)""",
            (row["id"], playbook_id, tenant_id, version_number, name, row["definition_json"], row["checksum"], row["created_by"], now, now),
        )
        _audit(conn, row, "CREATE", user, {"version_number": version_number})
        conn.commit()
        return get_version(row["id"], user)
    except PlaybookVersionError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_version(version_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Update an editable DRAFT in place and invalidate its prior validation."""
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, lock=True)
        _assert_scope(row, user)
        if row.get("status") != "DRAFT":
            raise PlaybookVersionError("PLAYBOOK_VERSION_IMMUTABLE", "Only DRAFT Playbook versions can be edited", status_code=409)
        if not isinstance(payload, dict):
            raise PlaybookVersionError("INVALID_PLAYBOOK_DEFINITION", "Playbook version payload must be an object")
        definition = _validate_definition(payload.get("definition") if "definition" in payload else payload)
        name = str(payload.get("name") or row.get("name") or row.get("playbook_id") or "").strip()[:200]
        if not name:
            raise PlaybookVersionError("INVALID_PLAYBOOK_NAME", "Playbook version name is required")
        now = _now()
        next_lock_version = int(row.get("lock_version") or 0) + 1
        result = conn.execute(
            """UPDATE playbook_versions
               SET name = ?, definition_json = ?, checksum = ?, validation_status = 'PENDING',
                   validation_result_json = '{}', updated_at = ?, lock_version = ?
               WHERE id = ? AND status = 'DRAFT' AND lock_version = ?""",
            (name, _json(definition), _checksum(definition), now, next_lock_version, version_id, int(row.get("lock_version") or 0)),
        )
        if getattr(result, "rowcount", 1) != 1:
            raise PlaybookVersionError("PLAYBOOK_VERSION_CONFLICT", "Playbook version changed; reload before editing", status_code=409)
        row.update({
            "name": name,
            "definition_json": _json(definition),
            "checksum": _checksum(definition),
            "validation_status": "PENDING",
            "validation_result_json": "{}",
            "updated_at": now,
            "lock_version": next_lock_version,
        })
        _audit(conn, row, "UPDATE", user, {"version_number": row.get("version_number"), "lock_version": next_lock_version})
        conn.commit()
        return get_version(version_id, user)
    except PlaybookVersionError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, lock=True)
        _assert_scope(row, user)
        if row.get("status") == "SNAPSHOT":
            raise PlaybookVersionError("PLAYBOOK_VERSION_IMMUTABLE", "Execution snapshots cannot be validated")
        definition = _definition_from_row(row)
        errors: list[dict[str, Any]] = []
        try:
            _validate_definition(definition)
        except PlaybookVersionError as exc:
            errors.append({"code": exc.code, "message": exc.message})
        result = {"valid": not errors, "errors": errors, "checksum": row.get("checksum")}
        conn.execute("UPDATE playbook_versions SET validation_status = ?, validation_result_json = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?", ("PASSED" if not errors else "FAILED", _json(result), _now(), version_id))
        _audit(conn, row, "VALIDATE", user, result)
        conn.commit()
        row.update({"validation_status": "PASSED" if not errors else "FAILED", "validation_result_json": _json(result)})
        return {"version_id": version_id, **result}
    finally:
        conn.close()


def _transition(version_id: str, event: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, lock=True)
        _assert_scope(row, user)
        if row.get("status") == "SNAPSHOT":
            raise PlaybookVersionError("PLAYBOOK_VERSION_IMMUTABLE", "Execution snapshots cannot change state")
        if event == "submit":
            expected, target = "DRAFT", "IN_REVIEW"
        elif event == "approve":
            expected, target = "IN_REVIEW", "APPROVED"
        elif event == "publish":
            expected, target = "APPROVED", "PUBLISHED"
        else:
            raise PlaybookVersionError("INVALID_PLAYBOOK_EVENT", "Unsupported Playbook version event")
        if row.get("status") != expected:
            raise PlaybookVersionError("INVALID_PLAYBOOK_STATE", f"Version must be {expected} before {event}")
        if event == "submit" and row.get("validation_status") != "PASSED":
            raise PlaybookVersionError("PLAYBOOK_VALIDATION_REQUIRED", "Playbook version must pass validation before submit")
        if event == "approve" and row.get("created_by") == _actor_key(user):
            raise PlaybookVersionError("SELF_APPROVAL_FORBIDDEN", "The creator cannot approve their own Playbook version", status_code=403)
        now = _now()
        if event == "publish":
            if row.get("tenant_id") is None:
                conn.execute("UPDATE playbook_versions SET status = 'DEPRECATED', updated_at = ? WHERE playbook_id = ? AND tenant_id IS NULL AND status = 'PUBLISHED' AND id <> ?", (now, row["playbook_id"], version_id))
            else:
                conn.execute("UPDATE playbook_versions SET status = 'DEPRECATED', updated_at = ? WHERE playbook_id = ? AND tenant_id = ? AND status = 'PUBLISHED' AND id <> ?", (now, row["playbook_id"], row["tenant_id"], version_id))
        fields = ["status = ?", "updated_at = ?", "lock_version = lock_version + 1"]
        params: list[Any] = [target, now]
        if event == "submit":
            fields.append("submitted_by = ?")
            params.append(_actor_key(user))
        elif event == "approve":
            fields.append("approved_by = ?")
            params.append(_actor_key(user))
        else:
            fields.extend(["published_by = ?", "published_at = ?"])
            params.extend([_actor_key(user), now])
        params.append(version_id)
        conn.execute(f"UPDATE playbook_versions SET {', '.join(fields)} WHERE id = ?", params)
        row.update({"status": target, "updated_at": now})
        _audit(conn, row, event.upper(), user, {"from": expected, "to": target})
        conn.commit()
        return get_version(version_id, user)
    except PlaybookVersionError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def submit_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition(version_id, "submit", user)


def approve_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition(version_id, "approve", user)


def publish_version(version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return _transition(version_id, "publish", user)


def rollback_version(playbook_id: str, version_id: str, user: dict[str, Any]) -> dict[str, Any]:
    playbook_id = _assert_playbook_id(playbook_id)
    conn = get_db_connection()
    try:
        row = _load_version(conn, version_id, lock=True)
        _assert_scope(row, user)
        if row.get("playbook_id") != playbook_id or row.get("status") not in {"PUBLISHED", "DEPRECATED"}:
            raise PlaybookVersionError("INVALID_ROLLBACK_TARGET", "Rollback target must be a published version of this Playbook")
        now = _now()
        if row.get("tenant_id") is None:
            conn.execute("UPDATE playbook_versions SET status = 'DEPRECATED', updated_at = ? WHERE playbook_id = ? AND tenant_id IS NULL AND status = 'PUBLISHED'", (now, playbook_id))
        else:
            conn.execute("UPDATE playbook_versions SET status = 'DEPRECATED', updated_at = ? WHERE playbook_id = ? AND tenant_id = ? AND status = 'PUBLISHED'", (now, playbook_id, row["tenant_id"]))
        conn.execute("UPDATE playbook_versions SET status = 'PUBLISHED', published_by = ?, published_at = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?", (_actor_key(user), now, now, version_id))
        row.update({"status": "PUBLISHED", "published_by": _actor_key(user), "published_at": now, "updated_at": now})
        _audit(conn, row, "ROLLBACK", user, {"playbook_id": playbook_id, "version_id": version_id})
        conn.commit()
        return get_version(version_id, user)
    except PlaybookVersionError:
        conn.rollback()
        raise
    finally:
        conn.close()
