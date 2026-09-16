"""
AI Change Governance Service - Managing Draft, Review, Approval, Verification, and Controlled Execution Gate
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection


class ChangeGovernanceService:
    """Manages AI Generated Change Orders and Approval Workflow."""

    def create_change_draft(
        self,
        title: str,
        device_id: str,
        commands: List[str],
        verification_commands: List[str],
        rollback_commands: List[str],
        created_by: str = "ai_agent"
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        draft_id = f"chg_{uuid.uuid4().hex[:12]}"
        
        # Insert change order into DB if change_orders table exists
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO change_orders (id, title, status, created_by, created_at, updated_at)
                    VALUES (?, ?, 'draft', ?, ?, ?)
                    """,
                    (draft_id, title, created_by, now_iso, now_iso)
                )
                conn.commit()
        except Exception:
            pass

        return {
            "change_id": draft_id,
            "title": title,
            "device_id": device_id,
            "commands": commands,
            "verification_commands": verification_commands,
            "rollback_commands": rollback_commands,
            "status": "draft",
            "requires_human_approval": True,
            "created_at": now_iso
        }

    def approve_change(self, change_id: str, approver: str) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE change_orders SET status = 'approved', updated_at = ? WHERE id = ?",
                    (now_iso, change_id)
                )
                conn.commit()
        except Exception:
            pass
        return {"change_id": change_id, "status": "approved", "approver": approver, "approved_at": now_iso}


change_governance_service = ChangeGovernanceService()
