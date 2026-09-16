"""Preflight checks for the Monitoring V1 PoC environment.

Static checks are intentionally runnable on a developer machine without
Docker.  ``--require-runtime`` turns the missing Docker daemon into a failure
for a deployment/acceptance workstation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _check_static() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8")) or {}
        services = compose.get("services") or {}
        expected_images = {
            "victoriametrics": "victoriametrics/victoria-metrics:v1.103.0",
            "vmagent": "victoriametrics/vmagent:v1.103.0",
            "snmp-exporter": "prom/snmp-exporter:v0.26.0",
        }
        for service, image in expected_images.items():
            if (services.get(service) or {}).get("image") != image:
                errors.append(f"compose image mismatch: {service}")
        vmagent = services.get("vmagent") or {}
        command = " ".join(str(item) for item in vmagent.get("command") or [])
        for marker in ("-remoteWrite.tmpDataPath=", "-remoteWrite.maxDiskUsagePerURL="):
            if marker not in command:
                errors.append(f"vmagent queue flag missing: {marker}")
        if not any("nexora-vmagent-queue" in str(item) for item in vmagent.get("volumes") or []):
            errors.append("vmagent queue volume missing")
        scrape = yaml.safe_load((ROOT / "monitoring" / "vmagent" / "scrape.yml").read_text(encoding="utf-8")) or {}
        relabel = scrape["scrape_configs"][0]["relabel_configs"]
        labels = {item.get("target_label") for item in relabel}
        for label in ("__param_target", "__param_module", "__param_auth", "__scrape_interval__", "__scrape_timeout__", "asset_id", "tenant_id"):
            if label not in labels:
                errors.append(f"vmagent relabel missing: {label}")
        exporter = yaml.safe_load((ROOT / "monitoring" / "snmp-exporter" / "snmp.yml").read_text(encoding="utf-8")) or {}
        modules = exporter.get("modules") or {}
        if "generic_ifmib_interface_std" not in modules or "generic_system_std" not in modules:
            errors.append("generic SNMP modules missing")
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"static configuration unreadable: {exc}")
    if shutil.which("docker") is None:
        warnings.append("Docker CLI is not installed; runtime Gate-01..Gate-07 cannot run here")
    return errors, warnings


def _check_runtime() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    docker = shutil.which("docker")
    if docker is None:
        errors.append("Docker CLI not found")
        return errors, warnings
    try:
        version = subprocess.run([docker, "compose", "version"], cwd=ROOT, capture_output=True, text=True, timeout=15)
        if version.returncode != 0:
            errors.append((version.stderr or version.stdout or "docker compose unavailable").strip())
            return errors, warnings
        config = subprocess.run([docker, "compose", "config", "--quiet"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if config.returncode != 0:
            errors.append((config.stderr or config.stdout or "docker compose config failed").strip())
            return errors, warnings
        ps = subprocess.run([docker, "compose", "ps", "--format", "json"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if ps.returncode != 0:
            warnings.append((ps.stderr or ps.stdout or "compose services are not running").strip())
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"Docker runtime check failed: {exc}")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-runtime", action="store_true", help="fail when Docker runtime is unavailable")
    args = parser.parse_args()
    errors, warnings = _check_static()
    if args.require_runtime:
        runtime_errors, runtime_warnings = _check_runtime()
        errors.extend(runtime_errors)
        warnings.extend(runtime_warnings)
    result: dict[str, Any] = {"ok": not errors, "errors": errors, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
