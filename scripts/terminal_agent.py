#!/usr/bin/env python3
"""Nexora local Terminal Agent.

The web application runs in Docker or on a remote Ubuntu server, while the
terminal program runs on the operator's workstation.  Browsers cannot start
an arbitrary executable directly, so this small loopback-only service accepts
one-time session tokens and launches the configured SSH client locally.

The agent deliberately does not receive or persist passwords.  It exchanges a
single-use token with the Nexora backend and keeps the returned credentials in
memory only for the duration of the process launch.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


AGENT_VERSION = "1.0.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17890
MAX_BODY_BYTES = 64 * 1024


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _allowed_origins() -> set[str]:
    raw = os.environ.get("NEXORA_AGENT_ALLOWED_ORIGINS", "")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def _resolve_executable(client: str, configured_path: str) -> str | None:
    configured_path = (configured_path or "").strip().strip('"').strip("'")
    names = {
        "xshell": "Xshell.exe",
        "putty": "putty.exe",
        "securecrt": "SecureCRT.exe",
        "mobaxterm": "MobaXterm.exe",
    }

    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_dir() and client in names:
            candidate = candidate / names[client]
        if candidate.is_file():
            return str(candidate)

    if client == "standard":
        return shutil.which("ssh") or shutil.which("ssh.exe")

    windows_paths = {
        "xshell": [
            r"C:\Program Files (x86)\NetSarang\Xshell 8\Xshell.exe",
            r"C:\Program Files (x86)\NetSarang\Xshell 7\Xshell.exe",
            r"C:\Program Files\NetSarang\Xshell 8\Xshell.exe",
            r"C:\Program Files\NetSarang\Xshell 7\Xshell.exe",
        ],
        "putty": [
            r"C:\Program Files\PuTTY\putty.exe",
            r"C:\Program Files (x86)\PuTTY\putty.exe",
        ],
        "securecrt": [
            r"C:\Program Files\VanDyke Software\SecureCRT\SecureCRT.exe",
            r"C:\Program Files (x86)\VanDyke Software\SecureCRT\SecureCRT.exe",
        ],
        "mobaxterm": [
            r"C:\Program Files\Mobatek\MobaXterm\MobaXterm.exe",
            r"C:\Program Files (x86)\Mobatek\MobaXterm\MobaXterm.exe",
        ],
    }
    for item in windows_paths.get(client, []):
        if os.path.isfile(item):
            return item
    return shutil.which(names.get(client, "")) if names.get(client) else None


def _exchange_token(backend_url: str, token: str) -> dict[str, Any]:
    parsed = urlparse(backend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("backend_url must be an http(s) origin")
    if parsed.username or parsed.password:
        raise ValueError("backend_url must not contain credentials")

    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = _allowed_origins()
    if allowed and origin.rstrip("/") not in allowed:
        raise PermissionError("backend origin is not allowed by NEXORA_AGENT_ALLOWED_ORIGINS")

    url = f"{origin}/api/system/exchange-token?token={quote(token, safe='')}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": f"NexoraTerminalAgent/{AGENT_VERSION}"})
    tls_verify = os.environ.get("NEXORA_AGENT_TLS_VERIFY", "0") == "1"
    context = ssl.create_default_context() if tls_verify else ssl._create_unverified_context()
    with urlopen(request, timeout=8, context=context) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Token exchange failed")
    return result


def _launch_client(client: str, executable: str, details: dict[str, Any]) -> None:
    host = str(details.get("ip") or "")
    user = str(details.get("user") or "")
    port = int(details.get("port") or 22)
    password = str(details.get("password") or "")
    if not host or not user:
        raise ValueError("Token exchange returned incomplete connection details")

    if client == "standard":
        args = [executable, "-p", str(port), f"{user}@{host}"]
    elif client == "xshell":
        target = f"ssh://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}" if password else f"ssh://{quote(user, safe='')}@{host}:{port}"
        args = [executable, "-url", target]
    elif client == "putty":
        args = [executable, "-ssh", f"{user}@{host}", "-P", str(port)]
        if password:
            args += ["-pw", password]
    elif client == "securecrt":
        args = [executable, "/SSH2", "/L", user, "/P", str(port)]
        if password:
            args += ["/PASSWORD", password]
        args.append(host)
    elif client == "mobaxterm":
        target = f"ssh://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}" if password else f"ssh://{quote(user, safe='')}@{host}:{port}"
        args = [executable, target]
    else:
        raise ValueError(f"Unsupported terminal client: {client}")

    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, **kwargs)


class AgentHandler(BaseHTTPRequestHandler):
    server_version = f"NexoraTerminalAgent/{AGENT_VERSION}"

    def _origin(self) -> str:
        return self.headers.get("Origin", "")

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self._origin()
        if origin and (not _allowed_origins() or origin.rstrip("/") in _allowed_origins()):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        origin = self._origin()
        if origin and (not _allowed_origins() or origin.rstrip("/") in _allowed_origins()):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._send(200, {"success": True, "service": "nexora-terminal-agent", "version": AGENT_VERSION})
            return
        self._send(404, {"success": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/terminal/launch":
            self._send(404, {"success": False, "error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            backend_url = str(payload.get("backend_url") or "")
            token = str(payload.get("session_token") or "")
            client = str(payload.get("client") or "standard").lower()
            configured_path = str(payload.get("path") or "")
            if not token:
                raise ValueError("session_token is required")
            if client not in {"standard", "xshell", "putty", "securecrt", "mobaxterm"}:
                raise ValueError("Unsupported terminal client")
            details = _exchange_token(backend_url, token)
            executable = _resolve_executable(client, configured_path)
            if not executable:
                raise FileNotFoundError(f"Terminal executable not found for {client}")
            _launch_client(client, executable, details)
            self._send(200, {"success": True, "client": client})
        except Exception as exc:
            self._send(400, {"success": False, "error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep credentials and token-bearing URLs out of stdout/logs.
        print(f"[TerminalAgent] {self.address_string()} - {fmt % args}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nexora local Terminal Agent")
    parser.add_argument("--host", default=os.environ.get("NEXORA_AGENT_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NEXORA_AGENT_PORT", DEFAULT_PORT)))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("The Terminal Agent must listen on loopback only")
    server = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    print(f"Nexora Terminal Agent listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
