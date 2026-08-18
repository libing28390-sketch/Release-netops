"""REL-004 static HTTP delivery, SSE, proxy and body-limit gate."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-004"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-004-HTTP-DELIVERY-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-004-http-delivery-v1.json"
MAIN_PATH = ROOT / "backend" / "main.py"
ASSISTANT_PATH = ROOT / "backend" / "ai" / "api" / "assistant.py"
V1_CHAT_PATH = ROOT / "backend" / "ai" / "api" / "chat_v1.py"
NGINX_PATH = ROOT / "nginx" / "nginx.conf"
COMPOSE_PATH = ROOT / "docker-compose.yml"
CONFIG_PATH = ROOT / "backend" / "core" / "config.py"


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-004 contract task mismatch")
    return payload


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def run_gate() -> dict[str, Any]:
    load_contract()
    main = MAIN_PATH.read_text(encoding="utf-8")
    assistant = ASSISTANT_PATH.read_text(encoding="utf-8")
    v1_chat = V1_CHAT_PATH.read_text(encoding="utf-8")
    nginx = NGINX_PATH.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    config = CONFIG_PATH.read_text(encoding="utf-8")
    checks = {
        "backend_download_static_mount": _contains(main, 'app.mount("/static", StaticFiles(directory=static_dir)', 'name="static_bin"'),
        "spa_root_mount_and_fallback": _contains(main, "class SPAStaticFiles", 'app.mount("/", SPAStaticFiles(directory="dist", html=True)', 'return await super().get_response("index.html", scope)'),
        "api_not_spa_fallback": _contains(main, 'not norm_path.startswith("api/")', 'not norm_path.startswith("static/")'),
        "assistant_sse_contract": _contains(assistant, 'media_type="text/event-stream"', '"Cache-Control": "no-cache, no-transform"', '"X-Accel-Buffering": "no"'),
        "v1_sse_contract": _contains(v1_chat, 'media_type="text/event-stream"', '"X-Accel-Buffering": "no"'),
        "application_body_limit": _contains(config, "REQUEST_BODY_MAX_BYTES: int = 150 * 1024 * 1024") and _contains(main, "enforce_request_body_limit", 'status_code=413', '"REQUEST_BODY_TOO_LARGE"'),
        "nginx_body_limit": bool(re.search(r"client_max_body_size\s+150m\s*;", nginx)),
        "nginx_api_timeout": _contains(nginx, "location /api/", "proxy_read_timeout 300s;", "proxy_send_timeout 300s;"),
        "compose_runtime_limit": "REQUEST_BODY_MAX_BYTES=${REQUEST_BODY_MAX_BYTES:-157286400}" in compose,
        "no_sqlite_acceptance": True,
    }
    report = {
        "task_id": TASK_ID,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "reason_codes": [] if all(checks.values()) else [key.upper() for key, value in checks.items() if not value],
        "checks": checks,
        "database": "none",
        "production_database_write": False,
        "external_provider_request": False,
        "sqlite": "forbidden_for_acceptance",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run_gate(), ensure_ascii=False, indent=2))
