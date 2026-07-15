from __future__ import annotations

from pathlib import Path

import desktop.update_service as update_service


def test_version_comparison_handles_windows_release_tags():
    assert update_service.parse_version("v1.2.3-windows") == (1, 2, 3)
    assert update_service.is_newer_version("v1.2.4-windows", "1.2.3")
    assert not update_service.is_newer_version("v1.2.3-windows", "1.2.3")
    assert not update_service.is_newer_version("v1.2.2-windows", "1.2.3")


def test_find_latest_windows_release_filters_non_windows_assets(monkeypatch):
    payload = [
        {
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-07-10T00:00:00Z",
            "html_url": "https://github.com/example/release",
            "assets": [{"name": "checksums.txt", "browser_download_url": "https://example/checksums"}],
        },
        {
            "tag_name": "v1.2.2-windows",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-07-09T00:00:00Z",
            "html_url": "https://github.com/example/windows",
            "body": "Windows fixes",
            "assets": [{"name": "NetOps.exe", "browser_download_url": "https://example/NetOps.exe"}],
        },
        {
            "tag_name": "v1.2.4-windows",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-07-11T00:00:00Z",
            "html_url": "https://github.com/example/windows-2",
            "body": "Latest Windows build",
            "assets": [{"name": "NetOps.exe", "browser_download_url": "https://example/NetOps.exe.2"}],
        },
    ]
    monkeypatch.setattr(update_service, "_request_json", lambda *_args: payload)

    result = update_service.find_latest_windows_release()

    assert result is not None
    assert result.version == "1.2.4"
    assert result.tag_name == "v1.2.4-windows"
    assert result.asset_url.endswith("NetOps.exe.2")


def test_create_windows_updater_contains_wait_replace_and_restart(tmp_path):
    source = tmp_path / "download.exe"
    target = tmp_path / "NetOps.exe"
    source.write_bytes(b"update")

    script = update_service.create_windows_updater(target, source, 1234)
    content = script.read_text(encoding="utf-8")

    assert ":wait_for_client" in content
    assert "PID=1234" in content
    assert "move /Y" in content
    assert 'start "" "%TARGET%"' in content

    script.unlink(missing_ok=True)
