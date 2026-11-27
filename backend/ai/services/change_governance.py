"""
AI Change Governance Service - Managing Draft, Review, Approval, Verification, and Controlled Execution Gate
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection
from services.change_order_service import create_change_order

logger = logging.getLogger(__name__)


class ChangeGovernanceService:
    """Manages AI Generated Change Orders and Approval Workflow."""

    def create_change_draft(
        self,
        title: str,
        device_id: str,
        commands: List[str],
        verification_commands: List[str],
        rollback_commands: List[str],
        created_by: str = "",
        requester_id: str = "",
        tenant_id: str = "",
    ) -> Dict[str, Any]:
        if not str(created_by or "").strip() or not str(requester_id or created_by or "").strip():
            # Every draft has an accountable human requester; there is no
            # anonymous "ai_agent" requester that bypasses separation of duties.
            raise ValueError("A change draft requires an authenticated requester")
        rollback_plan = "\n".join(str(cmd) for cmd in (rollback_commands or []) if str(cmd).strip())
        target_devices = [{"device_id": str(device_id)}] if device_id else []
        description = (
            f"AI-generated change order draft for device '{device_id}'. "
            f"Contains {len(commands or [])} change command(s), "
            f"{len(verification_commands or [])} verification command(s), "
            f"and {len(rollback_commands or [])} rollback command(s)."
        )

        with get_db_connection() as conn:
            conn.execute("LOCK TABLE change_orders IN SHARE ROW EXCLUSIVE MODE")
            order = create_change_order(
                conn,
                title=title,
                description=description,
                order_type="config_change",
                priority="medium",
                status="draft",
                requester_id=str(requester_id or created_by),
                requester_username=str(created_by),
                tenant_id=str(tenant_id or ""),
                command_template={
                    "source": "ai_governance",
                    "verification_commands": list(verification_commands or []),
                    "rollback_commands": list(rollback_commands or []),
                },
                target_devices=target_devices,
                commands=list(commands or []),
                rollback_plan=rollback_plan,
                risk_level="medium",
                commit=True,
            )

        return {
            "change_id": order["id"],
            "order_number": order.get("order_number"),
            "title": order.get("title", title),
            "device_id": device_id,
            "commands": list(commands or []),
            "verification_commands": list(verification_commands or []),
            "rollback_commands": list(rollback_commands or []),
            "status": order.get("status", "draft"),
            "requires_human_approval": True,
            "created_at": order.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }

    def approve_change(
        self,
        change_id: str,
        approver: str,
        *,
        approver_id: str = "",
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT id, status, tenant_id, requester_username, requester_id
                FROM change_orders
                WHERE id = ?
                FOR UPDATE
                """,
                (change_id,),
            ).fetchone()
            if not row:
                raise LookupError(f"Change order '{change_id}' not found")
            row_tenant = str(row[2] or "").strip()
            # Tenants must match exactly; a missing tenant on either side no
            # longer skips the check.
            if row_tenant != str(tenant_id or "").strip():
                raise LookupError(f"Change order '{change_id}' not found")
            current_status = str(row[1] or "")
            if current_status not in {"draft", "initial_review", "final_review"}:
                raise ValueError(f"Change order in status '{current_status}' cannot be approved")
            requester_username = str(row[3] or "").strip()
            requester_id = str(row[4] or "").strip()
            same_id = bool(requester_id) and requester_id == str(approver_id or "").strip()
            same_name = bool(requester_username) and requester_username == str(approver or "").strip()
            if same_id or same_name:
                raise PermissionError("Separation of duties violation: requester cannot approve their own change order")

            conn.execute(
                """
                UPDATE change_orders
                SET status = 'approved',
                    approver_id = ?,
                    approver_username = ?,
                    final_approver_id = ?,
                    final_approver_username = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (str(approver_id or approver), approver, str(approver_id or approver), approver, now_iso, change_id),
            )
            conn.commit()

        return {
            "change_id": change_id,
            "status": "approved",
            "approver": approver,
            "approved_at": now_iso,
        }


change_governance_service = ChangeGovernanceService()
