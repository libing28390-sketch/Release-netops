"""Baidu Netdisk (百度网盘) Automated Release Upload Script.

Reads BYPY_TOKEN_CONTENT from environment, sets up bypy authentication,
and uploads built binaries to Baidu Netdisk release directories.
"""

from __future__ import annotations

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


def main():
    token_content = os.environ.get("BYPY_TOKEN_CONTENT", "").strip()
    if not token_content:
        print("[INFO] BYPY_TOKEN_CONTENT is empty. Skipping Baidu Pan upload.")
        return

    # Ensure valid JSON format
    try:
        token_data = json.loads(token_content)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Failed to parse BYPY_TOKEN_CONTENT as JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    # 1. Write bypy.json to Home Config directory
    home_bypy = Path.home() / ".bypy"
    home_bypy.mkdir(parents=True, exist_ok=True)
    token_file = home_bypy / "bypy.json"
    token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    print(f"[BaiduPan] Token configured successfully in {token_file}")

    # 2. Initialize ByPy client
    client = ByPy(configdir=str(home_bypy))

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
        ("NetOps.exe", f"NetOps_{tag_name}_{date_str}.exe", "NetOps-Windows-Latest.exe"),
        ("NexoraTerminalAgent.exe", f"NexoraTerminalAgent_{tag_name}_{date_str}.exe", "NexoraTerminalAgent-Latest.exe"),
    ]

    for local_src, versioned_name, latest_name in artifacts:
        src_path = Path(local_src)
        if not src_path.exists():
            print(f"[WARN] Local artifact {local_src} not found, skipping.")
            continue

        file_size_mb = round(src_path.stat().st_size / (1024 * 1024), 2)
        print(f"\n[BaiduPan] === Uploading {local_src} ({file_size_mb} MB) ===")

        latest_file = work_dir / latest_name
        versioned_file = work_dir / versioned_name
        shutil.copy2(src_path, latest_file)
        shutil.copy2(src_path, versioned_file)

        # Upload to latest directory (use pure ASCII path to prevent cp1252 issues)
        print(f"[BaiduPan] -> NetOps_Release/latest/{latest_name}")
        client.upload(str(latest_file), "NetOps_Release/latest/")

        # Upload to archive directory
        print(f"[BaiduPan] -> NetOps_Release/archive/{tag_name}/{versioned_name}")
        client.upload(str(versioned_file), f"NetOps_Release/archive/{tag_name}/")

    # Clean up local temporary copies
    shutil.rmtree(work_dir, ignore_errors=True)
    print("\n[BaiduPan] All artifacts uploaded successfully to Baidu Netdisk!")


if __name__ == "__main__":
    main()
