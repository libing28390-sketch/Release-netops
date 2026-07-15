"""Online update helpers for the Windows desktop release.

The public Windows release is published as a ``NetOps.exe`` asset on GitHub.
This module deliberately contains no Qt code so it can be tested independently
and reused by the desktop UI without blocking the GUI thread.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable
from urllib.request import Request, urlopen


RELEASES_API_URL = (
    "https://api.github.com/repos/libing28390-sketch/Release-netops/releases"
    "?per_page=30"
)
WINDOWS_ASSET_NAME = "NetOps.exe"
USER_AGENT = "NetOps-Agent-Updater"


class UpdateError(RuntimeError):
    """Raised when the update endpoint or downloaded asset is invalid."""


@dataclass(frozen=True)
class WindowsRelease:
    version: str
    tag_name: str
    asset_url: str
    release_url: str
    notes: str = ""
    published_at: str = ""


def parse_version(value: str) -> tuple[int, ...]:
    """Extract a comparable numeric version from ``v1.2.3-windows``."""

    match = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)", value or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(latest: str, current: str) -> bool:
    """Return whether a release version is newer than the installed version."""

    latest_parts = parse_version(latest)
    current_parts = parse_version(current)
    if not latest_parts or not current_parts:
        return False
    width = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (width - len(latest_parts)) > current_parts + (
        0,
    ) * (width - len(current_parts))


def _request_json(url: str, timeout: float) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # urllib errors vary by platform and proxy setup.
        raise UpdateError(f"Unable to contact the release service: {exc}") from exc


def find_latest_windows_release(timeout: float = 10.0) -> WindowsRelease | None:
    """Find the newest non-draft Windows release containing ``NetOps.exe``."""

    payload = _request_json(RELEASES_API_URL, timeout)
    if not isinstance(payload, list):
        raise UpdateError("The release service returned an unexpected response")

    candidates: list[WindowsRelease] = []
    for release in payload:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag_name = str(release.get("tag_name") or "")
        version_parts = parse_version(tag_name)
        if not version_parts:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        asset = next(
            (
                item
                for item in assets
                if isinstance(item, dict) and item.get("name") == WINDOWS_ASSET_NAME
            ),
            None,
        )
        if not isinstance(asset, dict) or not asset.get("browser_download_url"):
            continue
        candidates.append(
            WindowsRelease(
                version=".".join(str(part) for part in version_parts),
                tag_name=tag_name,
                asset_url=str(asset["browser_download_url"]),
                release_url=str(release.get("html_url") or ""),
                notes=str(release.get("body") or "").strip(),
                published_at=str(release.get("published_at") or ""),
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: (parse_version(item.version), item.published_at))


def download_windows_release(
    release: WindowsRelease,
    destination: str | os.PathLike[str],
    progress: Callable[[int], None] | None = None,
    timeout: float = 120.0,
) -> Path:
    """Download a release asset to ``destination`` and return its path."""

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(release.asset_url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response, target.open("wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if progress and total:
                    progress(min(100, int(downloaded * 100 / total)))
    except Exception as exc:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise UpdateError(f"Unable to download the Windows update: {exc}") from exc

    if target.stat().st_size < 1024 * 1024:
        target.unlink(missing_ok=True)
        raise UpdateError("The downloaded update is unexpectedly small")
    if progress:
        progress(100)
    return target


def create_windows_updater(
    target_exe: str | os.PathLike[str],
    downloaded_exe: str | os.PathLike[str],
    process_id: int,
) -> Path:
    """Create a temporary cmd updater that replaces and restarts ``target_exe``."""

    target = str(Path(target_exe).resolve())
    downloaded = str(Path(downloaded_exe).resolve())
    fd, script_name = tempfile.mkstemp(prefix="netops-update-", suffix=".cmd")
    os.close(fd)
    script = f'''@echo off
setlocal
set "PID={int(process_id)}"
set "SOURCE={downloaded}"
set "TARGET={target}"

:wait_for_client
tasklist /FI "PID eq %PID%" /NH | findstr /C:"%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_for_client
)

set ATTEMPTS=0
:replace_file
move /Y "%SOURCE%" "%TARGET%" >nul 2>&1
if not errorlevel 1 goto launch_client
copy /Y "%SOURCE%" "%TARGET%" >nul 2>&1
if not errorlevel 1 goto remove_source
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 60 goto failed
timeout /t 1 /nobreak >nul
goto replace_file

:remove_source
del /q "%SOURCE%" >nul 2>&1
:launch_client
start "" "%TARGET%"
del /q "%~f0" >nul 2>&1
exit /b 0

:failed
del /q "%SOURCE%" >nul 2>&1
del /q "%~f0" >nul 2>&1
exit /b 1
'''
    Path(script_name).write_text(script, encoding="utf-8")
    return Path(script_name)
