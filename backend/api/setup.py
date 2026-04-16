"""
Initial setup wizard API.

GET  /setup/status          — Is setup completed?
POST /setup/complete        — Mark setup as completed
POST /setup/change-password — Change current user's password during setup
POST /setup/platform        — Save platform basic settings (name, timezone)
POST /setup/notification-test — Test a notification webhook
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.rbac import require_role
from database import get_db_connection
from services.notification_service import send_feishu, send_dingtalk, send_wechat

router = APIRouter(tags=["setup"])
logger = logging.getLogger(__name__)


# ── helpers ────────────────────────────────────────────────────────
def _get_setting(key: str) -> str | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def _set_setting(key: str, value: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO system_settings (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                              updated_at = excluded.updated_at""",
            (key, value, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


# ── schemas ────────────────────────────────────────────────────────
class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class PlatformSettingsBody(BaseModel):
    system_name: str = ""
    timezone: str = ""
    preferred_language: str = ""


class NotificationTestBody(BaseModel):
    platform: str  # feishu | dingtalk | wechat
    webhook_url: str
    secret: str = ""


# ── endpoints ──────────────────────────────────────────────────────
@router.get("/setup/status")
def get_setup_status(user=require_role("Viewer")):
    """Return whether initial setup has been completed."""
    completed = _get_setting("setup_completed") == "true"
    platform = json.loads(_get_setting("platform_settings") or "{}")
    return {
        "setup_completed": completed,
        "platform_settings": platform,
    }


@router.post("/setup/complete")
def mark_setup_complete(user=require_role("Administrator")):
    _set_setting("setup_completed", "true")
    logger.info("Initial setup wizard completed by %s", user["username"])
    return {"success": True, "message": "Setup completed"}


@router.post("/setup/change-password")
def setup_change_password(
    body: ChangePasswordBody,
    user=require_role("Viewer"),
):
    """Change logged-in user's password (used by setup wizard step 1)."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, password FROM users WHERE id = ?", (user["user_id"],)
        ).fetchone()
        if not row:
            raise HTTPException(404, "User not found")

        # Support both bcrypt hash and legacy plaintext passwords
        stored_pwd = row["password"]
        is_valid = False
        if stored_pwd.startswith('$2b$') or stored_pwd.startswith('$2a$'):
            # Bcrypt hash
            is_valid = bcrypt.checkpw(body.current_password.encode(), stored_pwd.encode())
        else:
            # Legacy plaintext
            is_valid = body.current_password == stored_pwd
        
        if not is_valid:
            raise HTTPException(400, "Current password is incorrect")

        # Strength check
        pwd = body.new_password
        checks = [
            any(c.isupper() for c in pwd),
            any(c.islower() for c in pwd),
            any(c.isdigit() for c in pwd),
            any(not c.isalnum() for c in pwd),
        ]
        if not all(checks):
            raise HTTPException(
                400,
                "Password must contain uppercase, lowercase, digit, and special character",
            )

        hashed = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "UPDATE users SET password = ? WHERE id = ?", (hashed, row["id"])
        )
        conn.commit()
        logger.info("Password changed via setup wizard for user %s", user["username"])
        return {"success": True}
    finally:
        conn.close()


@router.post("/setup/platform")
def save_platform_settings(
    body: PlatformSettingsBody,
    user=require_role("Administrator"),
):
    _set_setting("platform_settings", body.model_dump_json())
    logger.info("Platform settings saved by %s", user["username"])
    return {"success": True}


@router.post("/setup/notification-test")
def test_notification(
    body: NotificationTestBody,
    user=require_role("Administrator"),
):
    """Send a test alert message to the given webhook."""
    test_alert = {
        "title": "Nexora 测试通知",
        "object_name": "Setup Wizard",
        "ip_address": "127.0.0.1",
        "status": "active",
        "severity": "info",
        "message": "This is a test notification from Nexora setup wizard. 这是来自 Nexora 初始化向导的测试通知。",
        "first_occurrence": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_occurrence": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lang": "zh",
    }

    try:
        if body.platform == "feishu":
            send_feishu(body.webhook_url, test_alert)
        elif body.platform == "dingtalk":
            send_dingtalk(body.webhook_url, test_alert, secret=body.secret or '')
        elif body.platform == "wechat":
            send_wechat(body.webhook_url, test_alert)
        else:
            raise HTTPException(400, f"Unsupported platform: {body.platform}")
    except Exception as exc:
        logger.warning("Notification test failed for %s: %s", body.platform, exc)
        raise HTTPException(502, f"Send failed: {exc}") from exc

    return {"success": True, "platform": body.platform, "message": "Test message sent"}
