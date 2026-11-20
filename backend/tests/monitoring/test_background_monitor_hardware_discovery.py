from __future__ import annotations

import ast
from pathlib import Path


def test_background_monitor_does_not_run_python_hardware_discovery_or_sampling() -> None:
    source_path = Path(__file__).resolve().parents[2] / "services" / "background_monitor_service.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    retired_calls = {
        "collect_device_metrics",
        "discover_device_oid_config",
        "poll_hardware_inventory",
        "probe_librenms_hardware",
        "probe_standard_hardware",
    }
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imports = {
        alias.name.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )

    assert calls.isdisjoint(retired_calls)
    assert imports.isdisjoint(retired_calls)
