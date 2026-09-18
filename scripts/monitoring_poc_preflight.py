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
            "grafana": "grafana/grafana:12.1.0",
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
        if not any("nexora-monitoring-artifacts:/etc/nexora-collector" in str(item) for item in vmagent.get("volumes") or []):
            errors.append("vmagent shared monitoring artifact volume missing")
        exporter = services.get("snmp-exporter") or {}
        if not any("nexora-monitoring-artifacts:/etc/snmp_exporter" in str(item) for item in exporter.get("volumes") or []):
            errors.append("snmp-exporter shared monitoring artifact volume missing")
        if "runtime/vmagent/scrape.yml" not in command:
            errors.append("vmagent runtime scrape config path missing")
        if "runtime/snmp_exporter/snmp.yml" not in " ".join(str(item) for item in exporter.get("command") or []):
            errors.append("snmp-exporter runtime config path missing")
        grafana = services.get("grafana") or {}
        if not (grafana.get("volumes") and any("monitoring/grafana/provisioning" in str(item) for item in grafana.get("volumes") or [])):
            errors.append("grafana provisioning volume missing")
        if not (grafana.get("volumes") and any("monitoring/grafana/dashboards" in str(item) for item in grafana.get("volumes") or [])):
            errors.append("grafana dashboard volume missing")
        scrape = yaml.safe_load((ROOT / "monitoring" / "vmagent" / "scrape.yml").read_text(encoding="utf-8")) or {}
        relabel = scrape["scrape_configs"][0]["relabel_configs"]
        labels = {item.get("target_label") for item in relabel}
        for label in ("__param_target", "__param_module", "__param_auth", "__scrape_interval__", "__scrape_timeout__", "asset_id", "tenant_id"):
            if label not in labels:
                errors.append(f"vmagent relabel missing: {label}")
        exporter = yaml.safe_load((ROOT / "monitoring" / "snmp-exporter" / "snmp.yml").read_text(encoding="utf-8")) or {}
        auths = exporter.get("auths") or {}
        if not auths:
            errors.append("SNMP bootstrap auth definition missing")
        modules = exporter.get("modules") or {}
        required_modules = {
            "generic_ifmib_interface_std",
            "generic_system_std",
            "h3c_common_std",
            "huawei_common_std",
            "cisco_common_std",
        }
        missing_modules = sorted(required_modules - set(modules))
        if missing_modules:
            errors.append(f"SNMP OID modules missing: {','.join(missing_modules)}")
        for module_key in sorted(required_modules & set(modules)):
            if not (modules[module_key] or {}).get("metrics"):
                errors.append(f"SNMP OID module has no metrics: {module_key}")
        dashboard = json.loads((ROOT / "monitoring" / "grafana" / "dashboards" / "nexora-network-overview.json").read_text(encoding="utf-8"))
        dashboard_titles = {str(panel.get("title") or "") for panel in dashboard.get("panels") or []}
        for title in ("设备 CPU 使用率", "设备内存使用率", "设备温度"):
            if title not in dashboard_titles:
                errors.append(f"Grafana dashboard panel missing: {title}")
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
