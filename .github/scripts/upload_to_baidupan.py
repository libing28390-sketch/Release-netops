"""Baidu Netdisk (百度网盘) Automated Release Upload Script.

Reads BYPY_TOKEN_CONTENT from environment, sets up bypy authentication,
and uploads built zip packages (Windows and Linux) to Baidu Netdisk release directories.
Supports raw JSON, base64-encoded JSON, and single-line JSON strings.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
from pathlib import Path

try:
    from bypy import ByPy
except ImportError:
    print("[ERROR] bypy is not installed. Please run: pip install bypy", file=sys.stderr)
    sys.exit(1)


def parse_token_data(raw_input: str) -> dict:
    """Parse token data from raw JSON or Base64 encoded string."""
    cleaned = raw_input.strip()
    if not cleaned:
        raise ValueError("Token content is completely empty.")

    # 1. Try direct JSON parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "access_token" in data:
            return data
    except Exception:
        pass

    # 2. Try Base64 decode
    try:
        decoded_bytes = base64.b64decode(cleaned)
        data = json.loads(decoded_bytes.decode("utf-8", errors="replace"))
        if isinstance(data, dict) and "access_token" in data:
            return data
    except Exception:
        pass

    # 3. Try unescaping quotes if wrapped
    try:
        unescaped = cleaned.encode().decode("unicode_escape").strip("\"'")
        data = json.loads(unescaped)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    prefix = cleaned[:10] if len(cleaned) >= 10 else cleaned
    raise ValueError(
        f"Invalid token format (length={len(cleaned)}, prefix='{prefix}...'). "
        f"Expected valid JSON dictionary containing 'access_token' or Base64 string."
    )


def main():
    raw_token = os.environ.get("BYPY_TOKEN_CONTENT", "").strip()
    if not raw_token:
        print("[INFO] BYPY_TOKEN_CONTENT is empty. Skipping Baidu Pan upload.")
        return

    try:
        token_data = parse_token_data(raw_token)
    except Exception as exc:
        print(f"[ERROR] Failed to parse BYPY_TOKEN_CONTENT: {exc}", file=sys.stderr)
        sys.exit(1)

    # 1. Write bypy.json to Home Config directory
    home_bypy = Path.home() / ".bypy"
    home_bypy.mkdir(parents=True, exist_ok=True)
    token_file = home_bypy / "bypy.json"
    token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    print(f"[BaiduPan] Token loaded successfully (keys: {list(token_data.keys())})")

    # 2. Initialize ByPy client with 500MB slice size to enable direct non-slicing stream upload
    client = ByPy(configdir=str(home_bypy), slice_size=500 * 1024 * 1024, timeout=600, retry=3)

    # Test connection
    print("[BaiduPan] Testing quota & connection...")
    quota_res = client.info()
    if quota_res != 0:
        print(f"[ERROR] Failed to connect to Baidu Pan (exit code {quota_res})", file=sys.stderr)
        sys.exit(1)

    # 3. Determine version name and artifacts to upload
    tag_name = os.environ.get("GITHUB_REF_NAME", "latest").strip()
    date_str = os.environ.get("BUILD_DATE", "").strip()
    if not date_str:
        import datetime
        date_str = datetime.datetime.now().strftime("%Y%m%d")

    work_dir = Path("dist_baidupan").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    artifacts = [
        ("NetOps-Windows.zip", f"NetOps-Windows_{tag_name}_{date_str}.zip", "NetOps-Windows-Latest.zip"),
        ("NetOps-Linux-Ubuntu.zip", f"NetOps-Linux-Ubuntu_{tag_name}_{date_str}.zip", "NetOps-Linux-Ubuntu-Latest.zip"),
        ("NetOps.exe", f"NetOps_{tag_name}_{date_str}.exe", "NetOps-Windows-Latest.exe"),
        ("NexoraTerminalAgent.exe", f"NexoraTerminalAgent_{tag_name}_{date_str}.exe", "NexoraTerminalAgent-Latest.exe"),
    ]

    for local_src, versioned_name, latest_name in artifacts:
        src_path = Path(local_src)
        if not src_path.exists():
            continue

        file_size_mb = round(src_path.stat().st_size / (1024 * 1024), 2)
        print(f"\n[BaiduPan] === Uploading {local_src} ({file_size_mb} MB) ===", flush=True)

        latest_file = work_dir / latest_name
        versioned_file = work_dir / versioned_name
        shutil.copy2(src_path, latest_file)
        shutil.copy2(src_path, versioned_file)

        # Upload to latest directory (use pure ASCII path)
        print(f"[BaiduPan] -> NetOps_Release/latest/{latest_name} ...", flush=True)
        res1 = client.upload(str(latest_file), "NetOps_Release/latest/")
        print(f"[BaiduPan] -> latest upload finished (code {res1})", flush=True)

        # Upload to archive directory
        print(f"[BaiduPan] -> NetOps_Release/archive/{tag_name}/{versioned_name} ...", flush=True)
        res2 = client.upload(str(versioned_file), f"NetOps_Release/archive/{tag_name}/")
        print(f"[BaiduPan] -> archive upload finished (code {res2})", flush=True)

    # Clean up local temporary copies
    shutil.rmtree(work_dir, ignore_errors=True)
    print("\n[BaiduPan] All available artifacts uploaded successfully to Baidu Netdisk!", flush=True)


if __name__ == "__main__":
    main()
