#!/usr/bin/env python3
"""
License Issuer Server — 开发者专用签发工具
============================================
⚠️  此工具仅在开发者本地运行，用于给客户签发 License 文件。
    绝对不能部署到客户环境中（因为包含私钥操作）。

用法:
    cd d:/netsops/tools/license_issuer
    python issuer_server.py

    然后浏览器打开 http://localhost:18888
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add paths
_TOOL_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TOOL_DIR.parent.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

from license_auth.crypto import (
    generate_key_pair,
    load_private_key_from_file,
    sign_payload,
    verify_signature,
    load_public_key_from_file,
)
from license_auth.models import LicenseFile, LicensePayload, LicenseType

# ── Config ────────────────────────────────────────────────────────────

KEYS_DIR = _BACKEND_DIR / "license_auth" / "keys"
PRIVATE_KEY_PATH = KEYS_DIR / "private.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public.pem"
ISSUED_DIR = _TOOL_DIR / "issued"  # Archive of all issued licenses
ISSUED_DIR.mkdir(parents=True, exist_ok=True)

# ── Feature definitions ──────────────────────────────────────────────

FEATURE_CATALOG = {
    "automation":        "自动化执行 / Automation",
    "config_management": "配置管理 / Config Management",
    "monitoring":        "监控中心 / Monitoring",
    "alerting":          "告警系统 / Alerting",
    "rbac":              "角色权限 / RBAC",
    "change_orders":     "变更工单 / Change Orders",
    "inspections":       "巡检管理 / Inspections",
    "topology":          "拓扑发现 / Topology",
    "ipam":              "IP管理 / IPAM",
    "capacity":          "容量规划 / Capacity",
    "compliance":        "合规检查 / Compliance",
    "reports":           "报表导出 / Reports",
    "api_access":        "API接口 / API Access",
    "scheduled_jobs":    "定时任务 / Scheduled Jobs",
    "password_rotation": "密码轮换 / Password Rotation",
}

# Preset feature bundles
FEATURE_PRESETS = {
    "trial": ["automation", "monitoring", "config_management"],
    "standard": ["automation", "monitoring", "config_management", "alerting", "rbac", "topology"],
    "professional": [
        "automation", "monitoring", "config_management", "alerting", "rbac",
        "topology", "change_orders", "inspections", "ipam", "compliance", "reports",
    ],
    "enterprise": list(FEATURE_CATALOG.keys()),
}

# ── Models ────────────────────────────────────────────────────────────

class IssueRequest(BaseModel):
    company: str
    license_type: str = "standard"
    expire_at: str  # ISO-8601 date string
    device_limit: int = 50
    server_limit: int = 50
    features: List[str] = []
    machine_id: Optional[str] = None
    notes: Optional[str] = None  # Internal notes, not included in license


class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ── App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Nexora License Issuer", docs_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Issue registry (in-memory + file-based)
_issue_registry: list[dict] = []

def _load_registry():
    """Load existing issue records from disk."""
    global _issue_registry
    registry_file = ISSUED_DIR / "registry.json"
    if registry_file.exists():
        try:
            _issue_registry = json.loads(registry_file.read_text(encoding="utf-8"))
        except Exception:
            _issue_registry = []

def _save_registry():
    """Save issue records to disk."""
    registry_file = ISSUED_DIR / "registry.json"
    registry_file.write_text(
        json.dumps(_issue_registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

_load_registry()


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the issuer web UI."""
    html_path = _TOOL_DIR / "issuer_ui.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>issuer_ui.html not found</h1>", status_code=404)


def get_credentials():
    cred_file = _TOOL_DIR / "credentials.json"
    if cred_file.exists():
        try:
            return json.loads(cred_file.read_text(encoding="utf-8"))
        except:
            pass
    return {"username": "admin", "password": "admin"}

def save_credentials(username, password):
    cred_file = _TOOL_DIR / "credentials.json"
    cred_file.write_text(json.dumps({"username": username, "password": password}), encoding="utf-8")

@app.post("/api/login")
async def login(req: LoginRequest):
    creds = get_credentials()
    if req.username == creds["username"] and req.password == creds["password"]:
        return {"token": "issuer_local_dev_token_2026"}
    raise HTTPException(status_code=401, detail="用户名或密码错误")

@app.post("/api/password")
async def change_password(req: ChangePasswordRequest, request: Request):
    check_auth(request)
    creds = get_credentials()
    if req.old_password != creds["password"]:
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="新密码长度不能少于4位")
    save_credentials(creds["username"], req.new_password)
    return {"success": True}


def check_auth(request: Request):
    auth = request.headers.get("Authorization")
    if not auth:
        token = request.query_params.get("token")
        if token:
            auth = f"Bearer {token}"
            
    if auth == "Bearer issuer_local_dev_token_2026":
        return True
    raise HTTPException(status_code=401, detail="未授权，请先登录")


@app.get("/api/features")
async def get_features(request: Request):
    check_auth(request)
    """Return the full feature catalog and presets."""
    return {
        "catalog": FEATURE_CATALOG,
        "presets": FEATURE_PRESETS,
    }


@app.get("/api/history")
async def get_history(request: Request):
    check_auth(request)
    """Return all issued license records."""
    return {"records": list(reversed(_issue_registry))}


@app.post("/api/issue")
async def issue_license(req: IssueRequest, request: Request):
    check_auth(request)
    """
    Sign and generate a new license file.
    
    Returns the license JSON for download.
    """
    # Validate private key exists
    if not PRIVATE_KEY_PATH.exists():
        raise HTTPException(500, "Private key not found. Run key generation first.")

    private_key_pem = load_private_key_from_file(str(PRIVATE_KEY_PATH))

    # Build payload
    license_id = str(uuid.uuid4())
    payload = LicensePayload(
        license_id=license_id,
        company=req.company,
        license_type=LicenseType(req.license_type),
        issued_at=datetime.now(timezone.utc).isoformat(),
        expire_at=req.expire_at,
        device_limit=req.device_limit,
        server_limit=req.server_limit,
        features=req.features,
        machine_id=req.machine_id,
    )

    # Sign
    payload_dict = payload.model_dump(mode="json")
    signature = sign_payload(payload_dict, private_key_pem)

    # Build license file
    license_file = LicenseFile(payload=payload, signature=signature)
    license_json = json.dumps(
        license_file.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    )

    # Archive
    safe_company = "".join(c if c.isalnum() or c in "-_ " else "" for c in req.company).strip().replace(" ", "_")
    filename = f"license_{safe_company}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    archive_path = ISSUED_DIR / filename
    archive_path.write_text(license_json, encoding="utf-8")

    # Register
    record = {
        "license_id": license_id,
        "company": req.company,
        "license_type": req.license_type,
        "issued_at": payload.issued_at,
        "expire_at": req.expire_at,
        "device_limit": req.device_limit,
        "server_limit": req.server_limit,
        "features": req.features,
        "machine_id": req.machine_id,
        "notes": req.notes,
        "filename": filename,
    }
    _issue_registry.append(record)
    _save_registry()

    return {
        "success": True,
        "license_id": license_id,
        "filename": filename,
        "license_content": json.loads(license_json),
    }


@app.get("/api/download/{filename}")
async def download_license(filename: str, request: Request):
    check_auth(request)
    """Download a previously issued license file."""
    file_path = ISSUED_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(
        str(file_path),
        media_type="application/json",
        filename=filename,
    )


@app.post("/api/verify")
async def verify_uploaded_license(request: Request):
    check_auth(request)
    """Verify any license.json content against our public key."""
    if not PUBLIC_KEY_PATH.exists():
        raise HTTPException(500, "Public key not found.")

    body = await request.json()
    public_key_pem = load_public_key_from_file(str(PUBLIC_KEY_PATH))

    try:
        license_file = LicenseFile(**body)
    except Exception as e:
        return {"valid": False, "error": f"Invalid format: {e}"}

    payload_dict = license_file.payload.model_dump(mode="json")
    sig_ok = verify_signature(payload_dict, license_file.signature, public_key_pem)

    payload = license_file.payload
    expire_dt = datetime.fromisoformat(payload.expire_at)
    if expire_dt.tzinfo is None:
        expire_dt = expire_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days_remaining = (expire_dt - now).days

    return {
        "valid": sig_ok,
        "expired": days_remaining < 0,
        "days_remaining": days_remaining,
        "payload": payload_dict,
    }


if __name__ == "__main__":
    print("\n" + "=" * 56)
    print("  [KEY] Nexora License Issuer - Developer Only")
    print("=" * 56)
    print(f"  Private key: {PRIVATE_KEY_PATH}")
    print(f"  Public key:  {PUBLIC_KEY_PATH}")
    print(f"  Archive dir: {ISSUED_DIR}")
    print(f"  UI:          http://localhost:18888")
    print("=" * 56 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=18888, log_level="info")
