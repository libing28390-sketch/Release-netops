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


def _run_selection(tmp_path: Path, newline: bytes, enabled: str) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_bytes(
        newline.join(
            [
                b"STORAGE_BACKEND=local",
                b"NETOPS_REDIS_ENABLED=0",
                b"NETOPS_REMOTE_DESKTOP_ENABLED=" + enabled.encode(),
                b"",
            ]
        )
    )
    harness = f"""
source {shlex.quote(SCRIPT.as_posix())}
COMPOSE_PROJECT_NAME=nexora
COMPOSE_FILES=()
printf 'enabled=%s\\n' "$(remote_desktop_is_enabled && printf yes || printf no)"
printf 'services_begin\\n'
compose_service_args
printf 'services_end\\n'
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
    return {
        "enabled": next(line.split("=", 1)[1] for line in lines if line.startswith("enabled=")),
        "services": lines[start:end],
        "docker_call": next(line for line in lines if line.startswith("docker_call")),
    }


def test_guacamole_services_are_opt_in_and_dotenv_line_endings_are_normalized(tmp_path):
    for newline in (b"\n", b"\r\n"):
        enabled = _run_selection(tmp_path / f"enabled-{len(newline)}", newline, "1")
        assert enabled["enabled"] == "yes"
        assert {"guacamole", "guacd"} <= set(enabled["services"])
        assert "--profile" in enabled["docker_call"]
        assert "remote-desktop" in enabled["docker_call"]

        disabled = _run_selection(tmp_path / f"disabled-{len(newline)}", newline, "0")
        assert disabled["enabled"] == "no"
        assert "guacamole" not in disabled["services"]
        assert "guacd" not in disabled["services"]
        assert "remote-desktop" not in disabled["docker_call"]


def test_compose_limits_guacamole_networks_and_keeps_recordings_shared():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    guacamole = services["guacamole"]
    guacd = services["guacd"]

    assert guacamole["profiles"] == ["remote-desktop"]
    assert guacd["profiles"] == ["remote-desktop"]
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


def test_deploy_script_generates_separate_json_key_only_when_opted_in():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'openssl rand -hex 16' in source
    assert 'if remote_desktop_is_enabled; then' in source
    assert 'guacamole/guacamole:1.6.0' in source
    assert 'guacamole/guacd:1.6.0' in source
    assert "stop_disabled_remote_desktop" in source
