#!/usr/bin/env python3
"""Dedicated local Web PAM window.

The browser UI never receives a device username or password from Nexora.  A
short-lived PAM token is exchanged by this local process for the target URL,
then the operator logs in manually inside an off-the-record Qt WebEngine
profile.  The window has no address bar or browser context menu, blocks copy
shortcuts/clipboard permissions, reports heartbeats, and uploads a local
screen recording when it closes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


AGENT_VERSION = "1.1.0"
MAX_RECORDING_BYTES = 50 * 1024 * 1024
FRAME_INTERVAL_MS = 1000
MAX_FRAMES = 3600
MAX_GIF_FRAMES = 300
GIF_MAX_WIDTH = 640


def _origin(backend_url: str) -> str:
    parsed = urlparse(str(backend_url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("backend_url must be an http(s) origin")
    if parsed.username or parsed.password:
        raise ValueError("backend_url must not contain credentials")
    return f"{parsed.scheme}://{parsed.netloc}"


def _tls_context() -> ssl.SSLContext:
    # Existing Nexora deployments may use an internal/self-signed HTTPS
    # certificate.  Operators can opt into strict verification explicitly.
    if os.environ.get("NEXORA_AGENT_TLS_VERIFY", "0") == "1":
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def _json_request(url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
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
    with urlopen(request, timeout=timeout, context=_tls_context()) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("Backend returned an invalid JSON response")
    return result


def exchange_web_session(backend_url: str, session_token: str, agent_id: str) -> dict[str, Any]:
    origin = _origin(backend_url)
    if not session_token:
        raise ValueError("session_token is required")
    result = _json_request(
        f"{origin}/api/pam/web-sessions/exchange",
        {"session_token": session_token, "agent_id": agent_id},
    )
    if not result.get("success"):
        raise RuntimeError(str(result.get("detail") or result.get("error") or "Web session exchange failed"))
    for required in ("session_id", "callback_token", "target_url"):
        if not result.get(required):
            raise RuntimeError(f"Backend response is missing {required}")
    return result


def _multipart_body(fields: dict[str, str], filename: str, content_type: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"----NexoraWebRecording{hashlib.sha256(os.urandom(16)).hexdigest()[:24]}"
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


def upload_recording(
    backend_url: str,
    session_id: str,
    callback_token: str,
    agent_id: str,
    artifact: "RecordingArtifact",
) -> dict[str, Any]:
    origin = _origin(backend_url)
    content = artifact.path.read_bytes()
    if len(content) > MAX_RECORDING_BYTES:
        raise ValueError("Web recording is larger than the 50 MB upload limit")
    body, content_type = _multipart_body(
        {
            "callback_token": callback_token,
            "agent_id": agent_id,
        },
        artifact.filename,
        artifact.content_type,
        content,
    )
    request = Request(
        f"{origin}/api/pam/web-sessions/{session_id}/recording",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "User-Agent": f"NexoraWebAgent/{AGENT_VERSION}",
        },
    )
    with urlopen(request, timeout=20, context=_tls_context()) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(str((result or {}).get("detail") or (result or {}).get("error") or "Recording upload failed"))
    return result


def post_status(
    backend_url: str,
    session_id: str,
    callback_token: str,
    agent_id: str,
    status: str,
    recording_status: str,
    reason: str = "",
) -> dict[str, Any] | None:
    try:
        origin = _origin(backend_url)
        return _json_request(
            f"{origin}/api/pam/web-sessions/{session_id}/status",
            {
                "callback_token": callback_token,
                "agent_id": agent_id,
                "status": status,
                "reason": reason,
                "recording_status": recording_status,
            },
            timeout=5,
        )
    except Exception:
        # The local window must still close even if the backend is temporarily
        # unreachable. The best-effort callback is retried on the next timer.
        return None


@dataclass
class RecordingArtifact:
    path: Path
    filename: str
    content_type: str


class FrameRecorder:
    """Capture one WebView frame per second and assemble a viewable artifact."""

    def __init__(self, session_id: str):
        safe_id = "".join(char for char in str(session_id) if char.isalnum() or char in {"-", "_"})[:80]
        self.root = Path(tempfile.mkdtemp(prefix=f"nexora-web-{safe_id}-"))
        self.frames: list[Path] = []
        self.started_at = time.time()

    def capture(self, pixmap: Any) -> None:
        if len(self.frames) >= MAX_FRAMES or pixmap is None or pixmap.isNull():
            return
        image = pixmap.toImage()
        try:
            from PySide6.QtCore import Qt

            if image.width() > 1280:
                image = image.scaledToWidth(1280, Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass
        path = self.root / f"frame-{len(self.frames):06d}.jpg"
        if image.save(str(path), "JPG", 78):
            self.frames.append(path)

    def finalize(self) -> RecordingArtifact | None:
        if not self.frames:
            self.cleanup()
            return None
        gif_path = self.root / "recording.gif"
        sample_step = max(1, (len(self.frames) + MAX_GIF_FRAMES - 1) // MAX_GIF_FRAMES)
        try:
            from PIL import Image

            images = []
            sampled_frames = self.frames[::sample_step]
            for frame_path in sampled_frames:
                with Image.open(frame_path) as frame:
                    image = frame.convert("RGB")
                    if image.width > GIF_MAX_WIDTH:
                        image = image.resize(
                            (GIF_MAX_WIDTH, max(1, round(image.height * GIF_MAX_WIDTH / image.width))),
                            Image.Resampling.LANCZOS,
                        )
                    # Quantizing before writing keeps long recordings bounded
                    # while preserving the full-resolution JPEG frames for the
                    # ZIP fallback below.
                    images.append(image.quantize(colors=128, method=Image.Quantize.FASTOCTREE))
            first, rest = images[0], images[1:]
            first.save(
                gif_path,
                format="GIF",
                save_all=True,
                append_images=rest,
                duration=FRAME_INTERVAL_MS * sample_step,
                loop=0,
                optimize=True,
            )
            for image in images:
                image.close()
            if gif_path.is_file() and gif_path.stat().st_size <= MAX_RECORDING_BYTES:
                return RecordingArtifact(gif_path, "recording.gif", "image/gif")
        except Exception:
            pass

        # Pillow is bundled by the desktop launcher, but keep a portable
        # fallback so the recording is not silently discarded on a minimal
        # workstation runtime.
        zip_path = self.root / "recording-frames.zip"
        zip_step = sample_step
        while zip_step <= MAX_FRAMES * 2:
            try:
                if zip_path.exists():
                    zip_path.unlink()
                sampled_frames = self.frames[::zip_step]
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(
                        "manifest.json",
                        json.dumps(
                            {
                                "format": "jpeg-frames",
                                "fps": 1 / zip_step,
                                "started_at": self.started_at,
                                "frame_count": len(self.frames),
                                "sampled_frame_count": len(sampled_frames),
                                "sample_step": zip_step,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                    for frame in sampled_frames:
                        archive.write(frame, frame.name)
                if zip_path.stat().st_size <= MAX_RECORDING_BYTES:
                    return RecordingArtifact(zip_path, "recording-frames.zip", "application/zip")
            except Exception:
                pass
            zip_step *= 2
        return None

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _read_bootstrap() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(64 * 1024)
    if not raw:
        raise ValueError("Web session bootstrap payload is empty")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Web session bootstrap payload is invalid")
    return payload


def _load_qt():
    try:
        from PySide6.QtCore import QCloseEvent, QTimer, Qt, QUrl
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication, QMainWindow
    except Exception as exc:  # pragma: no cover - exercised on workstation runtime
        raise RuntimeError("Qt WebEngine is not installed; install PySide6 WebEngine Addons") from exc
    return {
        "QCloseEvent": QCloseEvent,
        "QTimer": QTimer,
        "Qt": Qt,
        "QUrl": QUrl,
        "QKeySequence": QKeySequence,
        "QWebEnginePage": QWebEnginePage,
        "QWebEngineProfile": QWebEngineProfile,
        "QWebEngineSettings": QWebEngineSettings,
        "QWebEngineView": QWebEngineView,
        "QApplication": QApplication,
        "QMainWindow": QMainWindow,
    }


def run_qt_window(details: dict[str, Any], backend_url: str, agent_id: str) -> int:
    qt = _load_qt()
    QMainWindow = qt["QMainWindow"]
    QWebEngineView = qt["QWebEngineView"]
    QWebEnginePage = qt["QWebEnginePage"]
    QWebEngineProfile = qt["QWebEngineProfile"]
    QWebEngineSettings = qt["QWebEngineSettings"]
    QTimer = qt["QTimer"]
    QUrl = qt["QUrl"]
    Qt = qt["Qt"]
    QCloseEvent = qt["QCloseEvent"]
    QApplication = qt["QApplication"]

    class LockedWebView(QWebEngineView):
        def contextMenuEvent(self, event):  # noqa: N802
            event.accept()

        def keyPressEvent(self, event):  # noqa: N802
            modifiers = event.modifiers()
            command_modifier = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
            if command_modifier and event.key() in {
                Qt.Key.Key_C,
                Qt.Key.Key_X,
                Qt.Key.Key_Insert,
            }:
                event.accept()
                return
            if event.key() == Qt.Key.Key_F12 or (
                command_modifier and bool(modifiers & Qt.KeyboardModifier.ShiftModifier) and event.key() == Qt.Key.Key_I
            ):
                event.accept()
                return
            super().keyPressEvent(event)

    class WebSessionWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.session_id = str(details["session_id"])
            self.callback_token = str(details["callback_token"])
            self.agent_id = agent_id
            self.backend_url = backend_url
            self.recorder = FrameRecorder(self.session_id)
            self.finalized = False

            self.setWindowTitle(f"Nexora Web PAM · {details.get('display_name') or 'Web management'}")
            self.resize(1360, 900)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

            self.view = LockedWebView(self)
            self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            profile = QWebEngineProfile(self)
            try:
                profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
                profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
            except Exception:
                pass
            page = QWebEnginePage(profile, self.view)
            self.view.setPage(page)
            self.setCentralWidget(self.view)

            settings = page.settings()
            for attribute_name in ("JavascriptCanAccessClipboard", "DeveloperExtrasEnabled"):
                try:
                    settings.setAttribute(getattr(QWebEngineSettings.WebAttribute, attribute_name), False)
                except Exception:
                    pass
            try:
                page.featurePermissionRequested.connect(self._deny_feature)
            except Exception:
                pass
            self.view.loadFinished.connect(self._on_load_finished)
            self.view.setUrl(QUrl(str(details["target_url"])))

            self.heartbeat_timer = QTimer(self)
            self.heartbeat_timer.setInterval(15_000)
            self.heartbeat_timer.timeout.connect(self._heartbeat)
            self.heartbeat_timer.start()

            self.record_timer = QTimer(self)
            self.record_timer.setInterval(FRAME_INTERVAL_MS)
            self.record_timer.timeout.connect(self._capture_frame)
            self.record_timer.start()

        def _deny_feature(self, origin, feature):
            try:
                self.view.page().setFeaturePermission(
                    origin,
                    feature,
                    QWebEnginePage.PermissionPolicy.Deny,
                )
            except Exception:
                pass

        def _on_load_finished(self, ok: bool):
            if ok:
                self._disable_page_copy()
                post_status(self.backend_url, self.session_id, self.callback_token, self.agent_id, "active", "recording")
            else:
                post_status(
                    self.backend_url,
                    self.session_id,
                    self.callback_token,
                    self.agent_id,
                    "error",
                    "recording",
                    "web_page_load_failed",
                )

        def _disable_page_copy(self):
            script = """
                (() => {
                    const stop = (event) => event.preventDefault();
                    document.addEventListener('copy', stop, true);
                    document.addEventListener('cut', stop, true);
                    try { navigator.clipboard.writeText = () => Promise.reject(new Error('Clipboard disabled')); } catch (_) {}
                })();
            """
            try:
                self.view.page().runJavaScript(script)
            except Exception:
                pass

        def _capture_frame(self):
            if not self.finalized:
                self.recorder.capture(self.view.grab())

        def _heartbeat(self):
            if not self.finalized:
                post_status(
                    self.backend_url,
                    self.session_id,
                    self.callback_token,
                    self.agent_id,
                    "active",
                    "recording",
                )

        def closeEvent(self, event: "QCloseEvent"):  # noqa: N802
            if self.finalized:
                event.accept()
                return
            self.finalized = True
            self.heartbeat_timer.stop()
            self.record_timer.stop()
            self.recorder.capture(self.view.grab())
            post_status(
                self.backend_url,
                self.session_id,
                self.callback_token,
                self.agent_id,
                "closed",
                "uploading",
                "window_closed",
            )
            artifact = self.recorder.finalize()
            recording_status = "not_started"
            if artifact is not None:
                try:
                    upload_recording(
                        self.backend_url,
                        self.session_id,
                        self.callback_token,
                        self.agent_id,
                        artifact,
                    )
                    recording_status = "uploaded"
                except Exception:
                    recording_status = "upload_failed"
            post_status(
                self.backend_url,
                self.session_id,
                self.callback_token,
                self.agent_id,
                "closed",
                recording_status,
                "window_closed",
            )
            self.recorder.cleanup()
            event.accept()

    app = QApplication.instance() or QApplication(sys.argv)
    window = WebSessionWindow()
    window.show()
    return int(app.exec())


def main() -> int:
    payload: dict[str, Any] | None = None
    details: dict[str, Any] | None = None
    backend_url = ""
    agent_id = ""
    try:
        payload = _read_bootstrap()
        backend_url = str(payload.get("backend_url") or "")
        agent_id = str(payload.get("agent_id") or "")[:128]
        details = exchange_web_session(backend_url, str(payload.get("session_token") or ""), agent_id)
    except Exception:
        # Do not print bootstrap tokens, target URLs, or page details. The
        # parent Agent records only the accepted launch request.
        return 1
    try:
        return run_qt_window(details, backend_url, agent_id)
    except Exception:
        # If the token was exchanged but Qt could not start, close the PAM
        # session instead of leaving it indefinitely in ``connecting`` state.
        if details:
            post_status(
                backend_url,
                str(details.get("session_id") or ""),
                str(details.get("callback_token") or ""),
                agent_id,
                "error",
                "not_started",
                "agent_start_failed",
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
