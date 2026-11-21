from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy-docker.sh"
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
BASH = Path(r"C:\Program Files\Git\bin\bash.exe") if Path(r"C:\Program Files\Git\bin\bash.exe").exists() else Path("bash")


def _run_selection(tmp_path: Path, newline: bytes, guacamole_key: bytes | None) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    env_lines = [
        b"STORAGE_BACKEND=local",
        b"NETOPS_REDIS_ENABLED=0",
        b"NETOPS_REMOTE_DESKTOP_ENABLED=1",
        # Keep initialize_env independent of the Linux-only `hostname -I`
        # fallback when this contract runs under Windows Git Bash.
        b"TLS_COMMON_NAME=nexora.test",
    ]
    if guacamole_key is not None:
        env_lines.append(b"GUACAMOLE_JSON_SECRET_KEY=" + guacamole_key)
    env_lines.append(b"")
    (tmp_path / ".env").write_bytes(newline.join(env_lines))
    harness = f"""
source {shlex.quote(SCRIPT.as_posix())}
COMPOSE_PROJECT_NAME=nexora
COMPOSE_FILES=()
initialize_env
printf 'legacy_switch_present=%s\\n' "$(grep -c '^NETOPS_REMOTE_DESKTOP_ENABLED=' .env || true)"
printf 'services_begin\\n'
compose_service_args
printf 'services_end\\n'
printf 'images_begin\\n'
required_images
printf 'images_end\\n'
docker() {{ printf 'docker_call'; printf ' <%s>' "$@"; printf '\\n'; }}
compose config --quiet
"""
    environment = os.environ.copy()
    environment.pop("NETOPS_REMOTE_DESKTOP_ENABLED", None)
    environment["NETOPS_DOCKER_SCRIPT_SOURCE_ONLY"] = "1"
    result = subprocess.run(
        [str(BASH), "-c", harness, "remote-desktop-contract"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    start = lines.index("services_begin") + 1
    end = lines.index("services_end")
    images_start = lines.index("images_begin") + 1
    images_end = lines.index("images_end")
    return {
        "services": lines[start:end],
        "images": lines[images_start:images_end],
        "docker_call": next(line for line in lines if line.startswith("docker_call")),
        "legacy_switch_present": next(
            line.split("=", 1)[1]
            for line in lines
            if line.startswith("legacy_switch_present=")
        ),
        "env": (tmp_path / ".env").read_bytes(),
    }


def test_guacamole_services_are_default_and_legacy_switch_is_removed_for_lf_and_crlf(tmp_path):
    for newline in (b"\n", b"\r\n"):
        deployment = _run_selection(
            tmp_path / f"deployment-{len(newline)}", newline, b"0123456789abcdef0123456789abcdef"
        )
        assert {"guacamole", "guacd"} <= set(deployment["services"])
        assert {
            "guacamole/guacamole:1.6.0",
            "guacamole/guacd:1.6.0",
        } <= set(deployment["images"])
        assert "--profile" not in deployment["docker_call"]
        assert "remote-desktop" not in deployment["docker_call"]
        assert deployment["legacy_switch_present"] == "0"
        assert b"NETOPS_REMOTE_DESKTOP_ENABLED=" not in deployment["env"]
        assert b"GUACAMOLE_JSON_SECRET_KEY=0123456789abcdef0123456789abcdef" in deployment["env"]


def test_compose_limits_guacamole_networks_and_keeps_recordings_shared():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    guacamole = services["guacamole"]
    guacd = services["guacd"]

    assert "profiles" not in guacamole
    assert "profiles" not in guacd
    assert guacamole["image"] == guacd["image"].replace("guacd", "guacamole")
    assert "ports" not in guacamole and "ports" not in guacd
    assert guacamole["expose"] == ["8080"]
    assert guacd["expose"] == ["4822"]
    assert guacd["user"] == "1000:1000"
    assert guacd["depends_on"]["netops"]["condition"] == "service_started"
    assert set(guacamole["networks"]) == {"remote_desktop_api", "remote_desktop_protocol"}
    assert set(guacd["networks"]) == {"remote_desktop_protocol", "remote_desktop_egress"}
    assert guacd["volumes"] == ["nexora-remote-desktop-recordings:/recordings"]
    assert "nexora-remote-desktop-recordings:/app/data/remote_desktop_recordings" in services["netops"]["volumes"]
    assert services["netops"]["environment"]
    assert "GUACAMOLE_JSON_SECRET_KEY" in ENV_EXAMPLE.read_text(encoding="utf-8")


def test_deploy_script_always_initializes_separate_json_key_and_archives_guacamole_images(tmp_path):
    generated = _run_selection(tmp_path / "generated-key", b"\r\n", None)
    key_lines = [
        line
        for line in generated["env"].splitlines()
        if line.startswith(b"GUACAMOLE_JSON_SECRET_KEY=")
    ]
    assert len(key_lines) == 1
    generated_key = key_lines[0].split(b"=", 1)[1]
    assert len(generated_key) == 32
    assert all(byte in b"0123456789abcdefABCDEF" for byte in generated_key)

    malformed = _run_selection(tmp_path / "malformed-key", b"\n", b"not-hex")
    repaired_lines = [
        line
        for line in malformed["env"].splitlines()
        if line.startswith(b"GUACAMOLE_JSON_SECRET_KEY=")
    ]
    assert len(repaired_lines) == 1
    repaired_key = repaired_lines[0].split(b"=", 1)[1]
    assert len(repaired_key) == 32
    assert all(byte in b"0123456789abcdefABCDEF" for byte in repaired_key)

    source = SCRIPT.read_text(encoding="utf-8")
    assert 'openssl rand -hex 16' in source
    assert 'if [[ ! "$guacamole_key" =~ ^[[:xdigit:]]{32}$ ]]; then' in source
    assert "remote_desktop_is_enabled" not in source
    assert "stop_disabled_remote_desktop" not in source
    assert 'guacamole/guacamole:1.6.0' in source
    assert 'guacamole/guacd:1.6.0' in source
    assert "NETOPS_REMOTE_DESKTOP_ENABLED=" in source  # Only the legacy .env cleanup remains.
    assert "NETOPS_REMOTE_DESKTOP_ENABLED=" not in ENV_EXAMPLE.read_text(encoding="utf-8")
