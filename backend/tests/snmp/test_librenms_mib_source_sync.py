from __future__ import annotations

import subprocess

from services import librenms_mib_service


def test_existing_librenms_checkout_expands_sparse_paths_before_safe_fetch(tmp_path, monkeypatch):
    repo = tmp_path / "librenms"
    (repo / ".git").mkdir(parents=True)
    (repo / "mibs").mkdir()
    (repo / "resources" / "definitions" / "os_detection").mkdir(parents=True)
    (repo / "resources" / "definitions" / "os_discovery").mkdir(parents=True)
    calls = []

    def run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(librenms_mib_service.subprocess, "run", run)

    assert librenms_mib_service.fetch_librenms_sources(repo)
    assert calls[0] == [
        "git", "sparse-checkout", "set", "--no-cone",
        *librenms_mib_service.LIBRENMS_SPARSE_PATHS,
    ]
    assert calls[1] == ["git", "status", "--porcelain", "--untracked-files=no"]
    assert calls[2] == ["git", "fetch", "--depth", "1", "origin", "master"]
    assert calls[3] == ["git", "checkout", "--detach", "FETCH_HEAD"]
