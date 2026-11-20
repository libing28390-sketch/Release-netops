from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "nginx/docker-entrypoint.d/40-configure-workers.sh"
BASH = Path(r"C:\Program Files\Git\bin\bash.exe") if Path(r"C:\Program Files\Git\bin\bash.exe").exists() else Path("bash")


def _run_hook(tmp_path, config: bytes, workers: str | None):
    config_path = tmp_path / "nginx.conf"
    config_path.write_bytes(config)
    source = HOOK.read_text(encoding="utf-8")
    # Run the actual function against a disposable main config, never /etc.
    source, footer = source.rsplit("\nconfigure_nginx_workers /etc/nginx/nginx.conf", 1)
    assert not footer.strip()
    environment = os.environ.copy()
    environment.pop("NGINX_WORKER_PROCESSES", None)
    if workers is not None:
        environment["NGINX_WORKER_PROCESSES"] = workers
    result = subprocess.run(
        [str(BASH), "-c", source + "\nconfigure_nginx_workers nginx.conf\n"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10,
    )
    return result, config_path.read_bytes()


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
@pytest.mark.parametrize("workers, expected", [(None, "1"), ("2", "2"), ("8", "8")])
def test_worker_setting_updates_only_the_main_directive(tmp_path, line_ending, workers, expected):
    config = line_ending.join([
        "user nginx;",
        "worker_processes  auto; # image default",
        "events { worker_connections 1024; }",
        "http { include /etc/nginx/conf.d/*.conf; }",
        "# worker_processes auto; commented example",
        "",
    ]).encode()
    result, updated = _run_hook(tmp_path, config, workers)
    assert result.returncode == 0, result.stderr
    expected_config = config.replace(b"worker_processes  auto; # image default", f"worker_processes  {expected}; # image default".encode())
    # Git Bash sed may normalize CRLF; both forms are valid Nginx whitespace.
    assert updated.replace(b"\r\n", b"\n") == expected_config.replace(b"\r\n", b"\n")

    # A later container start with the same explicit setting is stable.
    again, repeated = _run_hook(tmp_path, updated, workers)
    assert again.returncode == 0, again.stderr
    assert repeated == updated


@pytest.mark.parametrize("workers", ["0", "-1", "auto", "1.5", "9", "1025", "9999999999999999999", "1; echo injected", "1\r"])
def test_invalid_worker_values_fail_without_changing_config(tmp_path, workers):
    config = b"worker_processes auto;\nevents { worker_connections 1024; }\n"
    result, updated = _run_hook(tmp_path, config, workers)
    assert result.returncode != 0
    assert "must be an integer" in result.stderr
    assert updated == config


@pytest.mark.parametrize("config", [b"events {}\n", b"worker_processes auto;\nworker_processes 2;\n"])
def test_ambiguous_main_config_fails_before_rewrite(tmp_path, config):
    result, updated = _run_hook(tmp_path, config, None)
    assert result.returncode != 0
    assert "Expected one worker_processes directive" in result.stderr
    assert updated == config
