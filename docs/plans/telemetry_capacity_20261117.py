"""Offline payload measurements and arithmetic; no sockets, DB or device access.

Run from repository root: python docs/plans/telemetry_capacity_20261117.py
Numbers are synthetic payload sizes, NOT collector throughput benchmarks.
"""
from pathlib import Path
import json
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from services.snmp_hardware_inventory_service import render_hardware_metrics

LIMIT = 64 * 1024**2
fixture = runpy.run_path(str(ROOT / "backend/tests/snmp/test_snmp_hardware_renderer_labels.py"))
sensors = []
for index in range(300):
    sensor = fixture["_full_sensor"](
        component_class="wireless_radio", measurement_type="wireless_sensor_value",
        sensor_key=f"synthetic-sensor-{index:06d}",
    )
    sensor["last_success"] = "2026-11-17T00:00:00+00:00"
    sensors.append(sensor)
hardware = render_hardware_metrics(sensors, fixture["DEVICE_LABELS"])
hardware_lines = [line for line in hardware.splitlines() if line and not line.startswith("#")]
hardware_headers = [line for line in hardware.splitlines() if line.startswith("#")]
hardware_data_bytes = sum(len((line + "\n").encode()) for line in hardware_lines)
hardware_header_bytes = sum(len((line + "\n").encode()) for line in hardware_headers)

def snapshot(devices):
    total = 0
    for device in range(devices):
        for port in range(48):
            labels = (
                f'asset_id="00000000-0000-4000-8000-{device:012d}",'
                f'hostname="core-switch-{device:06d}",site_id="site-0001",'
                f'tenant_id="tenant-0001",vendor="h3c",platform="hp_comware",'
                f'ifName="Ten-GigabitEthernet1/0/{port+1}",ifIndex="{port+1}",'
                'source_type="telemetry"'
            )
            for metric in range(10):
                line = f'nexora_interface_counter_{metric:02d}{{{labels}}} 123456789012345\n'
                total += len(line.encode())
        # 20 device-level metrics, same size budget as an interface sample.
        total += 20 * len(line.encode())
    return total

per_device = snapshot(1)
rows = []
for devices in (10, 50, 100, 300, 500, 1000):
    series = devices * 500
    body_bytes = snapshot(devices)
    rows.append({
        "devices": devices, "series": series,
        "samples_per_second_5s": series / 5,
        "samples_per_day_5s": series * 86400 // 5,
        "fleet_snapshot_bytes": body_bytes,
        "fleet_snapshot_mib": round(body_bytes / 1024**2, 3),
        "exceeds_64mib": body_bytes >= LIMIT,
    })
result = {
    "scope": "offline synthetic UTF-8 payload measurement and capacity arithmetic only",
    "interface_model": {"interfaces_per_device": 48, "metrics_per_interface": 10,
                        "device_metrics": 20, "labels_per_interface_sample": 9,
                        "per_device_bytes": per_device,
                        "devices_at_32mib": (LIMIT//2)//per_device,
                        "devices_at_64mib": LIMIT//per_device},
    "scenarios": rows,
    "existing_hardware_renderer": {
        "synthetic_sensors_per_device": 300,
        "samples_per_device": len(hardware_lines),
        "body_bytes_one_device": len(hardware.encode()),
        "data_bytes_one_device": hardware_data_bytes,
        "headers_bytes": hardware_header_bytes,
        "devices_at_32mib_data_only": (LIMIT//2)//hardware_data_bytes,
        "devices_at_64mib_data_only": LIMIT//hardware_data_bytes,
        "fleet_100_devices_mib_data_only": round(hardware_data_bytes*100/1024**2, 3),
        "fleet_300_devices_mib_data_only": round(hardware_data_bytes*300/1024**2, 3),
        "note": "Synthetic rich wireless fixture, no capability series; not production inventory.",
    },
    "storage_5s_30d_gib_at_2_to_10_bytes_per_sample": {
        str(row["devices"]): [round(row["samples_per_day_5s"]*30*b/1024**3, 2) for b in (2,10)]
        for row in rows
    },
    "queue_example": {"sample_rate": 5000, "assumed_queue_bytes_per_sample": 100,
                      "configured_1GB_nominal_seconds": 1_000_000_000/(5000*100),
                      "one_GiB_seconds": round(1024**3/(5000*100), 2),
                      "one_hour_GiB": round(5000*100*3600/1024**3, 3)},
}
target = Path(__file__).with_name("telemetry_capacity_20261117.json")
target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
