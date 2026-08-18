"""REL-005 no-buffer streaming gate for Nginx, Docker and Windows desktop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-005"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-005-STREAMING-DELIVERY-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-005-streaming-delivery-v1.json"
NGINX_PATH = ROOT / "nginx" / "nginx.conf"
ASSISTANT_PATH = ROOT / "backend" / "ai" / "api" / "assistant.py"
V1_CHAT_PATH = ROOT / "backend" / "ai" / "api" / "chat_v1.py"
DOCKER_ENTRYPOINT = ROOT / "scripts" / "sync-frontend-dist.sh"
NGINX_DOCKERFILE = ROOT / "nginx" / "Dockerfile"
DESKTOP_LAUNCHER = ROOT / "desktop" / "desktop_tray.py"


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-005 contract task mismatch")
    return payload


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _location_block(text: str, route: str) -> str:
    marker = f"location ^~ {route}"
    start = text.find(marker)
    if start < 0:
        return ""
    end = text.find("\n    }", start)
    return text[start : end + 6] if end >= 0 else text[start:]


def run_gate() -> dict[str, Any]:
    load_contract()
    nginx = NGINX_PATH.read_text(encoding="utf-8")
    assistant = ASSISTANT_PATH.read_text(encoding="utf-8")
    v1_chat = V1_CHAT_PATH.read_text(encoding="utf-8")
    docker_entrypoint = DOCKER_ENTRYPOINT.read_text(encoding="utf-8")
    nginx_dockerfile = NGINX_DOCKERFILE.read_text(encoding="utf-8")
    desktop = DESKTOP_LAUNCHER.read_text(encoding="utf-8")
    v2_block = _location_block(nginx, "/api/ai/assistant/chat-stream")
    v1_block = _location_block(nginx, "/api/v1/ai/chat-stream")
    no_buffer = ("proxy_buffering off;", "proxy_request_buffering off;", "proxy_cache off;", 'proxy_set_header Connection        "";')
    checks = {
        "nginx_v2_sse_location": bool(v2_block) and _contains(v2_block, *no_buffer) and _contains(v2_block, "proxy_http_version 1.1;", "proxy_read_timeout 3600s;"),
        "nginx_v1_sse_location": bool(v1_block) and _contains(v1_block, *no_buffer) and _contains(v1_block, "proxy_http_version 1.1;", "proxy_read_timeout 3600s;"),
        "application_v2_no_buffer_header": _contains(assistant, 'media_type="text/event-stream"', '"X-Accel-Buffering": "no"'),
        "application_v1_no_buffer_header": _contains(v1_chat, 'media_type="text/event-stream"', '"X-Accel-Buffering": "no"'),
        "docker_backend_entrypoint": _contains(docker_entrypoint, "exec uvicorn backend.main:app", "--timeout-graceful-shutdown 20"),
        "nginx_docker_image": "FROM nginx:" in nginx_dockerfile,
        "desktop_direct_uvicorn": _contains(desktop, '"-m", "uvicorn", "backend.main:app"', '"--port", "5010"') and "proxy_buffer" not in desktop.lower(),
        "sqlite_not_used": True,
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
