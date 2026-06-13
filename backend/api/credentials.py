"""
credentials.py — Credential Vault API

REST endpoints for managing the CMDB credential vault (`credentials` table).
Secrets are encrypted at rest (AES-256-GCM) and never returned in plaintext;
read responses expose only `has_*` presence flags.
"""

import logging
from fastapi import APIRouter, HTTPException
from database import get_db_connection
from core.rbac import require_role
from schemas.schemas import CredentialCreate, CredentialUpdate
from services import credential_service
from services.audit_service import log_audit_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/credentials")
def api_list_credentials(_user=require_role("Operator")):
    conn = get_db_connection()
    try:
        data = credential_service.list_credentials(conn)
        return {"success": True, "data": data, "message": ""}
    finally:
        conn.close()


@router.get("/credentials/{cred_id}")
def api_get_credential(cred_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        cred = credential_service.get_credential(conn, cred_id)
        cred["devices"] = credential_service.list_devices_using(conn, cred_id)
        return {"success": True, "data": cred, "message": ""}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.post("/credentials", status_code=201)
def api_create_credential(body: CredentialCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        cred = credential_service.create_credential(conn, **body.model_dump())
        log_audit_event(
            event_type="credential.create",
            category="configuration",
            severity="info",
            status="success",
            summary=f"Created credential '{body.credential_name}'",
            actor_username=user.get("username") if isinstance(user, dict) else None,
            actor_role=user.get("role") if isinstance(user, dict) else None,
            target_type="credential",
            target_id=cred.get("id"),
            target_name=body.credential_name,
        )
        return {"success": True, "data": cred, "message": "Credential created"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/credentials/{cred_id}")
def api_update_credential(cred_id: str, body: CredentialUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        cred = credential_service.update_credential(
            conn, cred_id, **body.model_dump(exclude_unset=True)
        )
        log_audit_event(
            event_type="credential.update",
            category="configuration",
            severity="info",
            status="success",
            summary=f"Updated credential {cred_id}",
            actor_username=user.get("username") if isinstance(user, dict) else None,
            actor_role=user.get("role") if isinstance(user, dict) else None,
            target_type="credential",
            target_id=cred_id,
            target_name=cred.get("credential_name"),
        )
        return {"success": True, "data": cred, "message": "Credential updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/credentials/{cred_id}")
def api_delete_credential(cred_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        credential_service.delete_credential(conn, cred_id)
        log_audit_event(
            event_type="credential.delete",
            category="configuration",
            severity="warning",
            status="success",
            summary=f"Deleted credential {cred_id}",
            actor_username=user.get("username") if isinstance(user, dict) else None,
            actor_role=user.get("role") if isinstance(user, dict) else None,
            target_type="credential",
            target_id=cred_id,
        )
        return {"success": True, "data": None, "message": "Credential deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
