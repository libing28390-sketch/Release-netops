#!/usr/bin/env python3
"""Nexora local Terminal Agent.

The web application runs in Docker or on a remote Ubuntu server, while the
terminal program runs on the operator's workstation.  Browsers cannot start
an arbitrary executable directly, so this small loopback-only service accepts
one-time session tokens and launches the configured SSH client or system
browser locally.

The agent deliberately does not receive or persist Web PAM passwords. It
exchanges a single-use token with the Nexora backend; terminal credentials, if
needed for an SSH client, remain in memory only for the duration of launch.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
import zlib
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


AGENT_VERSION = "1.2.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17890
AUTOSTART_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_REGISTRY_VALUE = "NexoraTerminalAgent"
MANAGED_START_FLAG = "--managed-start"
MAX_BODY_BYTES = 64 * 1024
AGENT_ID = os.environ.get("NEXORA_AGENT_ID", "").strip() or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
MAX_WEB_RECORDING_BYTES = 50 * 1024 * 1024
WEB_RECORDING_INTERVAL_SECONDS = 2.0
WEB_HEARTBEAT_INTERVAL_SECONDS = 15.0
WEB_RECORDING_MAX_FRAMES = 120
WEB_SESSION_MAX_SECONDS = max(300, int(os.environ.get("NEXORA_WEB_SESSION_MAX_SECONDS", "43200")))
_WEB_BROWSER_AVAILABLE: bool | None = None


def _autostart_command(port: int) -> str:
    """Build the command stored in the current user's Windows startup key."""
    if getattr(sys, "frozen", False):
        executable = str(Path(sys.executable).resolve())
        command = [executable, MANAGED_START_FLAG, "--host", DEFAULT_HOST, "--port", str(port)]
    else:
        python_executable = Path(sys.executable).resolve()
        if python_executable.name.lower() == "python.exe":
            pythonw = python_executable.with_name("pythonw.exe")
            if pythonw.is_file():
                python_executable = pythonw
        command = [
            str(python_executable),
            str(Path(__file__).resolve()),
            MANAGED_START_FLAG,
            "--host",
            DEFAULT_HOST,
            "--port",
            str(port),
        ]
    return subprocess.list2cmdline(command)


def _register_windows_autostart(port: int) -> None:
    """Register the agent for the current user's logon without elevation."""
    if sys.platform != "win32":
        return
    import winreg

    command = _autostart_command(port)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REGISTRY_KEY) as key:
        winreg.SetValueEx(key, AUTOSTART_REGISTRY_VALUE, 0, winreg.REG_SZ, command)


def _unregister_windows_autostart() -> None:
    """Remove the agent's current-user startup entry when it exists."""
    if sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, AUTOSTART_REGISTRY_VALUE)
    except FileNotFoundError:
        pass


def _show_windows_warning(message: str) -> None:
    if sys.platform != "win32":
        print(message, file=sys.stderr, flush=True)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "Nexora Terminal Agent", 0x30)
    except Exception:
        print(message, file=sys.stderr, flush=True)


def _ensure_windows_autostart(port: int) -> None:
    """Keep direct launches convenient while preserving an explicit escape hatch."""
    if sys.platform != "win32":
        return
    try:
        _register_windows_autostart(port)
    except Exception as exc:
        _show_windows_warning(
            "Agent 已启动，但无法设置 Windows 开机自启。\n\n"
            f"原因：{exc}\n\n"
            "可使用 --no-autostart 跳过，或检查当前用户的启动项权限。"
        )


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _allowed_origins() -> set[str]:
    raw = os.environ.get("NEXORA_AGENT_ALLOWED_ORIGINS", "")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def _backend_origin(backend_url: str) -> str:
    parsed = urlparse(backend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("backend_url must be an http(s) origin")
    if parsed.username or parsed.password:
        raise ValueError("backend_url must not contain credentials")

    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = _allowed_origins()
    if allowed and origin.rstrip("/") not in allowed:
        raise PermissionError("backend origin is not allowed by NEXORA_AGENT_ALLOWED_ORIGINS")
    return origin


def _resolve_system_browser() -> str | None:
    """Find an installed browser executable so its lifetime can be monitored."""
    configured = os.environ.get("NEXORA_BROWSER_PATH", "").strip().strip('"').strip("'")
    candidates = [configured] if configured else []
    candidates.extend(
        [
            shutil.which("msedge"),
            shutil.which("msedge.exe"),
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            shutil.which("brave"),
            shutil.which("brave.exe"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("firefox"),
            shutil.which("firefox.exe"),
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def _web_browser_available() -> bool:
    """Return whether a system browser can open the Web PAM target URL."""
    global _WEB_BROWSER_AVAILABLE
    if _WEB_BROWSER_AVAILABLE is not None:
        return _WEB_BROWSER_AVAILABLE
    if _resolve_system_browser():
        _WEB_BROWSER_AVAILABLE = True
        return True
    try:
        webbrowser.get()
    except Exception:
        _WEB_BROWSER_AVAILABLE = False
    else:
        _WEB_BROWSER_AVAILABLE = True
    return _WEB_BROWSER_AVAILABLE


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
    origin = _backend_origin(backend_url)

    url = f"{origin}/api/system/exchange-token?token={quote(token, safe='')}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": f"NexoraTerminalAgent/{AGENT_VERSION}"})
    tls_verify = os.environ.get("NEXORA_AGENT_TLS_VERIFY", "0") == "1"
    context = ssl.create_default_context() if tls_verify else ssl._create_unverified_context()
    with urlopen(request, timeout=8, context=context) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Token exchange failed")
    return result


def _web_json_request(url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"NexoraWebAgent/{AGENT_VERSION}",
        },
    )
    tls_verify = os.environ.get("NEXORA_AGENT_TLS_VERIFY", "0") == "1"
    context = ssl.create_default_context() if tls_verify else ssl._create_unverified_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("Backend returned an invalid JSON response")
    return result


def _exchange_web_session(backend_url: str, session_token: str, agent_id: str) -> dict[str, Any]:
    origin = _backend_origin(backend_url)
    result = _web_json_request(
        f"{origin}/api/pam/web-sessions/exchange",
        {"session_token": session_token, "agent_id": agent_id},
    )
    if not result.get("success"):
        raise RuntimeError(str(result.get("detail") or result.get("error") or "Web session exchange failed"))
    for required in ("session_id", "callback_token", "target_url"):
        if not result.get(required):
            raise RuntimeError(f"Backend response is missing {required}")
    return result


def _post_web_status(
    backend_url: str,
    details: dict[str, Any],
    agent_id: str,
    status: str,
    recording_status: str,
    reason: str = "",
) -> None:
    try:
        origin = _backend_origin(backend_url)
        _web_json_request(
            f"{origin}/api/pam/web-sessions/{details['session_id']}/status",
            {
                "callback_token": details["callback_token"],
                "agent_id": agent_id,
                "status": status,
                "reason": reason,
                "recording_status": recording_status,
            },
            timeout=5,
        )
    except Exception:
        # The browser must still be usable when the backend is temporarily
        # unreachable; the session expiry remains the final safety net.
        pass


def _multipart_body(fields: dict[str, str], filename: str, content_type: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"----NexoraWebRecording{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("ascii"),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _upload_web_recording(backend_url: str, details: dict[str, Any], agent_id: str, artifact: Path) -> None:
    content = artifact.read_bytes()
    if len(content) > MAX_WEB_RECORDING_BYTES:
        raise ValueError("Web recording is larger than the 50 MB upload limit")
    body, content_type = _multipart_body(
        {"callback_token": str(details["callback_token"]), "agent_id": agent_id},
        artifact.name,
        "application/zip",
        content,
    )
    origin = _backend_origin(backend_url)
    request = Request(
        f"{origin}/api/pam/web-sessions/{details['session_id']}/recording",
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": content_type, "User-Agent": f"NexoraWebAgent/{AGENT_VERSION}"},
    )
    tls_verify = os.environ.get("NEXORA_AGENT_TLS_VERIFY", "0") == "1"
    context = ssl.create_default_context() if tls_verify else ssl._create_unverified_context()
    with urlopen(request, timeout=20, context=context) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(str((result or {}).get("detail") or (result or {}).get("error") or "Recording upload failed"))


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _encode_png(width: int, height: int, rgb: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgb[row * width * 3 : (row + 1) * width * 3] for row in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 6))
        + _png_chunk(b"IEND", b"")
    )


def _find_browser_window(pid: int) -> tuple[int, int, int] | None:
    if sys.platform != "win32" or not pid:
        return None
    import ctypes
    from ctypes import wintypes

    class Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    found: list[tuple[int, int, int]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if int(process_id.value) != int(pid):
            return True
        rect = Rect()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            width = max(0, int(rect.right - rect.left))
            height = max(0, int(rect.bottom - rect.top))
            if width >= 240 and height >= 160:
                found.append((int(hwnd), width, height))
                return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def _capture_browser_png(window: tuple[int, int, int]) -> bytes | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    hwnd, width, height = window
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None
    memdc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
    if not memdc or not bitmap:
        if memdc:
            gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, hdc)
        return None
    previous = gdi32.SelectObject(memdc, bitmap)
    try:
        captured = user32.PrintWindow(hwnd, memdc, 2)
        if not captured:
            captured = gdi32.BitBlt(memdc, 0, 0, width, height, hdc, 0, 0, 0x00CC0020)
        if not captured:
            return None

        class Header(ctypes.Structure):
            _fields_ = [
                ("size", ctypes.c_uint32), ("width", ctypes.c_int32), ("height", ctypes.c_int32),
                ("planes", ctypes.c_uint16), ("bits", ctypes.c_uint16), ("compression", ctypes.c_uint32),
                ("image_size", ctypes.c_uint32), ("xppm", ctypes.c_int32), ("yppm", ctypes.c_int32),
                ("colors", ctypes.c_uint32), ("important", ctypes.c_uint32),
            ]

        class Info(ctypes.Structure):
            _fields_ = [("header", Header), ("colors", ctypes.c_uint32 * 3)]

        info = Info()
        info.header.size = ctypes.sizeof(Header)
        info.header.width = width
        info.header.height = -height
        info.header.planes = 1
        info.header.bits = 32
        info.header.compression = 0
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        lines = gdi32.GetDIBits(memdc, bitmap, 0, height, ctypes.cast(buffer, ctypes.c_void_p), ctypes.byref(info), 0)
        if lines != height:
            return None
        raw = bytes(buffer)
        rgb = bytearray(width * height * 3)
        for source in range(0, len(raw), 4):
            target = (source // 4) * 3
            rgb[target : target + 3] = bytes((raw[source + 2], raw[source + 1], raw[source]))
        return _encode_png(width, height, bytes(rgb))
    finally:
        gdi32.SelectObject(memdc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, hdc)


class _BrowserRecorder:
    def __init__(self, pid: int):
        self.pid = pid
        self.root = Path(tempfile.mkdtemp(prefix="nexora-web-recording-"))
        self.frames: list[Path] = []

    def capture(self) -> None:
        if len(self.frames) >= WEB_RECORDING_MAX_FRAMES:
            return
        window = _find_browser_window(self.pid)
        if not window:
            return
        try:
            png = _capture_browser_png(window)
            if png:
                path = self.root / f"frame-{len(self.frames):06d}.png"
                path.write_bytes(png)
                self.frames.append(path)
        except Exception:
            pass

    def window_is_open(self) -> bool:
        return _find_browser_window(self.pid) is not None

    def finalize(self) -> Path | None:
        if not self.frames:
            self.cleanup()
            return None
        archive_path = self.root / "recording-frames.zip"
        stride = 1
        while stride <= len(self.frames):
            selected = self.frames[::stride]
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "format": "png-frames",
                            "fps": 1 / WEB_RECORDING_INTERVAL_SECONDS / stride,
                            "frame_count": len(selected),
                            "sample_stride": stride,
                        },
                        indent=2,
                    ),
                )
                for frame in selected:
                    archive.write(frame, frame.name)
            if archive_path.stat().st_size <= MAX_WEB_RECORDING_BYTES:
                return archive_path
            stride *= 2
        return None

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _start_system_browser(target_url: str) -> tuple[subprocess.Popen[Any] | None, str | None]:
    browser = _resolve_system_browser()
    if browser:
        profile_dir = tempfile.mkdtemp(prefix="nexora-web-profile-")
        browser_name = Path(browser).name.lower()
        if "firefox" in browser_name:
            args = [browser, "-no-remote", "-new-instance", "-profile", profile_dir, "-new-window", target_url]
        else:
            args = [
                browser,
                f"--app={target_url}",
                "--new-window",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-extensions",
            ]
        kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(args, **kwargs), profile_dir
        except Exception:
            shutil.rmtree(profile_dir, ignore_errors=True)
            raise
    if webbrowser.open_new(target_url):
        return None, None
    raise RuntimeError("No system browser was found")


def _monitor_web_session(backend_url: str, details: dict[str, Any], agent_id: str, process: subprocess.Popen[Any] | None, profile_dir: str | None) -> None:
    recorder = _BrowserRecorder(process.pid) if process is not None and sys.platform == "win32" else None
    _post_web_status(backend_url, details, agent_id, "active", "recording" if recorder else "not_started")
    started = time.monotonic()
    reason = "window_closed"
    browser_window_seen = False
    missing_window_cycles = 0
    close_grace_cycles = max(3, int(10 / WEB_RECORDING_INTERVAL_SECONDS))
    last_heartbeat = started
    while time.monotonic() - started < WEB_SESSION_MAX_SECONDS:
        if recorder:
            if recorder.window_is_open():
                browser_window_seen = True
                missing_window_cycles = 0
            elif browser_window_seen:
                missing_window_cycles += 1
                if missing_window_cycles >= close_grace_cycles:
                    break
            recorder.capture()
        if process is None:
            _post_web_status(backend_url, details, agent_id, "active", "not_started")
            time.sleep(15)
            continue
        if process.poll() is not None:
            break
        if time.monotonic() - last_heartbeat >= WEB_HEARTBEAT_INTERVAL_SECONDS:
            _post_web_status(backend_url, details, agent_id, "active", "recording" if recorder else "not_started")
            last_heartbeat = time.monotonic()
        time.sleep(WEB_RECORDING_INTERVAL_SECONDS)
    else:
        reason = "session_timeout"
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass

    if recorder:
        recorder.capture()
        _post_web_status(backend_url, details, agent_id, "closed", "uploading", reason)
        artifact = recorder.finalize()
        recording_status = "not_started"
        if artifact is not None:
            try:
                _upload_web_recording(backend_url, details, agent_id, artifact)
                recording_status = "uploaded"
            except Exception:
                recording_status = "upload_failed"
        _post_web_status(backend_url, details, agent_id, "closed", recording_status, reason)
        recorder.cleanup()
    else:
        _post_web_status(backend_url, details, agent_id, "closed", "not_started", reason)
    if profile_dir:
        shutil.rmtree(profile_dir, ignore_errors=True)


def _launch_web_window(backend_url: str, session_token: str, agent_id: str) -> None:
    """Open the target URL in an isolated system-browser app window."""
    _backend_origin(backend_url)
    if not _web_browser_available():
        raise RuntimeError("No system browser is available for Web PAM")
    details = _exchange_web_session(backend_url, session_token, agent_id)
    try:
        process, profile_dir = _start_system_browser(str(details["target_url"]))
    except Exception:
        _post_web_status(backend_url, details, agent_id, "error", "not_started", "browser_launch_failed")
        raise
    threading.Thread(
        target=_monitor_web_session,
        args=(backend_url, details, agent_id, process, profile_dir),
        name="nexora-web-session",
        daemon=True,
    ).start()


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
            capabilities = ["terminal"]
            if _web_browser_available():
                capabilities.append("web_access")
            self._send(
                200,
                {
                    "success": True,
                    "service": "nexora-terminal-agent",
                    "version": AGENT_VERSION,
                    "agent_id": AGENT_ID,
                    "capabilities": capabilities,
                },
            )
            return
        self._send(404, {"success": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path not in {"/v1/terminal/launch", "/v1/web/launch"}:
            self._send(404, {"success": False, "error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            backend_url = str(payload.get("backend_url") or "")
            token = str(payload.get("session_token") or "")
            if path == "/v1/web/launch":
                if not token:
                    raise ValueError("session_token is required")
                requested_origin = _backend_origin(backend_url)
                request_origin = self._origin().rstrip("/")
                if request_origin and request_origin != requested_origin.rstrip("/"):
                    raise PermissionError("Web launch origin does not match backend_url")
                _launch_web_window(backend_url, token, AGENT_ID)
                self._send(
                    200,
                    {
                        "success": True,
                        "session_kind": "device_web",
                        "agent_id": AGENT_ID,
                    },
                )
                return

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
    parser.add_argument(
        MANAGED_START_FLAG,
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="Run once without registering Windows logon startup.",
    )
    parser.add_argument(
        "--unregister-autostart",
        action="store_true",
        help="Remove the current user's Windows logon startup entry and exit.",
    )
    parser.add_argument(
        "--register-autostart",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("The Terminal Agent must listen on loopback only")
    if args.unregister_autostart:
        _unregister_windows_autostart()
        return 0
    if args.register_autostart:
        _register_windows_autostart(args.port)
        return 0
    if sys.platform == "win32" and not args.managed_start and not args.no_autostart:
        _ensure_windows_autostart(args.port)
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
