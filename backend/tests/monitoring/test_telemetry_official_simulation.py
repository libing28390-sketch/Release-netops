"""Official Huawei VRP (CloudEngine) and H3C Comware V7 Telemetry simulation tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid

from collectors.telemetry.normalizer import normalize_message
from collectors.telemetry.server import ReceiverState
from collectors.telemetry.wire import (
    decode_h3c_v2_dialout,
    decode_h3c_v3_json,
    decode_huawei_service_args,
)
from database import get_db_connection
from services import telemetry_config_service as svc
from schemas.telemetry import TelemetryDeviceConfigUpsert, TelemetrySubscriptionCreate


def test_huawei_cloudengine_official_protobuf_and_json_normalization():
    """Verify official Huawei serviceArgs(packed_data_json) protobuf wire frame and YANG path normalization."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    mappings = svc._official_huawei_mappings()
    paths = list(dict.fromkeys(m["source_path"] for m in mappings))

    records = [svc._build_official_sample_document(p, "CE6850-CORE-01", now_ms) for p in paths]
    packed_json = json.dumps({"telemetry": records}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raw_pb = svc._pb_field_varint(1, 1001) + svc._pb_field_bytes(6, packed_json)

    encoding, decoded_bytes = decode_huawei_service_args(raw_pb)
    assert encoding == "packed_data_json"
    parsed = json.loads(decoded_bytes.decode("utf-8"))
    assert len(parsed["telemetry"]) == len(paths)
    assert len(paths) >= 9

    device_ctx = {
        "tenant_id": "tenant-default",
        "asset_id": "asset-hw-01",
        "device_id": "dev-hw-01",
        "hostname": "CE6850-CORE-01",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
    }
    sub_ctx = {"id": "sub-hw-01", "metric_mappings": mappings, "interval_seconds": 10, "reserved_series": 100, "reserved_sample_rate": 50.0}

    all_samples: list[str] = []
    for rec in parsed["telemetry"]:
        samples = normalize_message(
            payload=json.dumps(rec).encode("utf-8"),
            source_path=rec["sensor_path"],
            source_timestamp=rec["msg_timestamp"],
            device=device_ctx,
            subscription=sub_ctx,
        )
        all_samples.extend(samples)

    assert len(all_samples) >= 20
    assert any("nexora_telemetry_huawei_cpu_system_usage" in s and 'cpu_position="0"' in s for s in all_samples)
    assert any("nexora_telemetry_huawei_memory_os_usage" in s and " 44 " in s for s in all_samples)
    assert any("nexora_telemetry_huawei_interface_rx_bytes" in s and 'interface_name="10GE1/0/1"' in s for s in all_samples)
    assert any("nexora_telemetry_huawei_interface_tx_bytes" in s and 'interface_name="10GE1/0/2"' in s for s in all_samples)
    assert any("nexora_telemetry_huawei_optical_rx_power_dbm" in s for s in all_samples)
    assert any("nexora_telemetry_huawei_board_temperature_celsius" in s for s in all_samples)
    assert any("nexora_telemetry_huawei_qos_queue_discarded_packets" in s for s in all_samples)
    assert any("nexora_telemetry_huawei_pfc_rx_pause_frames" in s for s in all_samples)

    state = ReceiverState()
    accepted = state.accept_samples(sub_ctx, all_samples)
    assert len(accepted) == len(all_samples)


def test_h3c_comware_v7_v2_and_v3_official_protobuf_and_json_normalization():
    """Verify official H3C Comware V7 DialoutMsg (2-layer) and TelemetryPacked (3-layer) wire frames."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    mappings = svc._official_h3c_mappings()
    paths = list(dict.fromkeys(m["source_path"] for m in mappings))

    device_ctx = {
        "tenant_id": "tenant-default",
        "asset_id": "asset-h3c-01",
        "device_id": "dev-h3c-01",
        "hostname": "S6850-6",
        "vendor": "H3C",
        "platform": "h3c_comware",
    }
    sub_ctx = {"id": "sub-h3c-01", "metric_mappings": mappings}

    # 1. H3C v2 (2-layer JSON DialoutMsg)
    v2_samples: list[str] = []
    dev_msg_pb = svc._pb_field_bytes(1, b"H3C") + svc._pb_field_bytes(2, b"S6850-6")
    for spath in paths:
        doc = svc._build_official_sample_document(spath, "S6850-6", now_ms)
        doc_bytes = json.dumps(doc).encode("utf-8")
        raw_pb = svc._pb_field_bytes(1, dev_msg_pb) + svc._pb_field_bytes(2, spath.encode("utf-8")) + svc._pb_field_bytes(3, doc_bytes)
        producer, dev_name, decoded_path, decoded_body = decode_h3c_v2_dialout(raw_pb)
        assert producer == "H3C"
        assert dev_name == "S6850-6"
        assert decoded_path == spath
        v2_samples.extend(
            normalize_message(
                payload=decoded_body,
                source_path=decoded_path,
                source_timestamp=now_ms,
                device=device_ctx,
                subscription=sub_ctx,
            )
        )
    assert len(v2_samples) >= 20
    assert any("nexora_telemetry_h3c_cpu_usage_percent" in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_memory_usage_percent" in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_interface_in_octets" in s and 'interface_name="FortyGigE1/0/53"' in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_optical_rx_power_dbm" in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_board_temperature_celsius" in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_qos_buffer_used_bytes" in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_pfc_headroom_used_bytes" in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_device_max_mtu" in s and " 9216 " in s for s in v2_samples)
    assert any("nexora_telemetry_h3c_syslog_buffer_size" in s and " 512 " in s for s in v2_samples)

    # 2. H3C v3 (3-layer JSON DialoutV3Args / TelemetryPacked)
    packed_records = bytearray()
    for spath in paths:
        doc = svc._build_official_sample_document(spath, "S6850-6", now_ms)
        doc_bytes = json.dumps(doc).encode("utf-8")
        rec_pb = svc._pb_field_bytes(16, spath.encode("utf-8")) + svc._pb_field_varint(19, now_ms) + svc._pb_field_bytes(24, doc_bytes)
        packed_records.extend(svc._pb_field_bytes(1, rec_pb))
    raw_v3_pb = svc._pb_field_varint(1, 3001) + svc._pb_field_bytes(2, bytes(packed_records))
    req_id, _total, decoded_records = decode_h3c_v3_json(raw_v3_pb)
    assert req_id == 3001
    assert len(decoded_records) == len(paths)

    v3_samples: list[str] = []
    for spath, ts, rec_bytes in decoded_records:
        v3_samples.extend(
            normalize_message(
                payload=rec_bytes,
                source_path=spath,
                source_timestamp=ts,
                device=device_ctx,
                subscription=sub_ctx,
            )
        )
    assert len(v3_samples) == len(v2_samples)


def test_end_to_end_control_plane_provisioning_and_simulation():
    """Verify no-TLS provisioning, template seeding, and end-to-end simulation on PostgreSQL."""
    admin_user = {"id": "user-admin", "username": "admin", "role": "Administrator", "tenant_id": "tenant-default"}
    profiles = svc.list_profiles()["items"]
    assert len(profiles) >= 6
    assert all(len(p.get("paths") or []) > 0 for p in profiles)

    templates = svc.list_templates(admin_user)["items"]
    published = [t for t in templates if t["status"] == "PUBLISHED"]
    assert len(published) >= 6

    with get_db_connection() as conn:
        h3c_dev = conn.execute(
            "SELECT id, ip_address FROM devices WHERE LOWER(vendor) = 'h3c' AND asset_id IS NOT NULL LIMIT 1"
        ).fetchone()
    assert h3c_dev is not None
    device_id = str(h3c_dev["id"])
    device_ip = str(h3c_dev["ip_address"] or "10.254.0.6")

    h3c_profile = next(p for p in profiles if p["profile_key"] == "h3c_grpc_dialout_json_v2_s6850_r6717")
    h3c_template = next(t for t in published if t["profile_id"] == h3c_profile["id"])

    existing_cfg = svc.get_device_config(device_id, admin_user)
    rev = int(existing_cfg["revision"]) if existing_cfg else 1

    saved_cfg = svc.upsert_device_config(
        device_id,
        TelemetryDeviceConfigUpsert(
            profile_id=h3c_profile["id"],
            collector_id="telemetry-collector-local",
            device_source_address=device_ip,
            allowed_sources=[device_ip],
            tls_profile_id=None,
            enabled=True,
            revision=rev,
        ),
        admin_user,
    )
    assert saved_cfg["enabled"] is True

    sub_name = f"官方标准遥测仿真_{uuid.uuid4().hex[:6]}"
    created_sub = svc.create_subscription(
        device_id,
        TelemetrySubscriptionCreate(
            name=sub_name,
            template_id=h3c_template["id"],
            template_version=int(h3c_template["version"]),
            interval_seconds=10,
            path_filters=[],
        ),
        admin_user,
    )
    try:
        sim_result = svc.simulate_subscription_push(created_sub["id"], admin_user)
        assert sim_result["active_series"] >= 1
        assert sim_result["runtime"]["connection_state"] == "CONNECTED"
        assert sim_result["runtime"]["data_state"] == "FRESH"
        assert len(sim_result["normalized_samples"]) == sim_result["active_series"]
    finally:
        svc.delete_subscription(created_sub["id"], admin_user)


def test_comprehensive_vendor_and_model_coverage_including_h3c_s5135s():
    """Verify every official H3C and Huawei switch, firewall, AC, and router model is MATCHED."""
    from services.official_product_catalog_service import model_aliases, vendor_models

    h3c_rows = vendor_models("H3C")
    huawei_rows = vendor_models("Huawei")
    assert len(h3c_rows) >= 50
    assert len(huawei_rows) >= 50

    h3c_catalog_models = {row["model"] for row in h3c_rows}
    assert "S5135S-24P4S-EI" in h3c_catalog_models
    assert "S5135S-48T4S-EI-Q" in h3c_catalog_models

    profiles_list = svc.list_profiles()["items"]
    profiles = {p["profile_key"]: p for p in profiles_list}
    assert len(profiles) >= 8

    # 1. Verify every H3C campus and datacenter model in MODEL_CATALOG["H3C"] matches at least one H3C profile.
    h3c_profiles = [p for p in profiles_list if p["vendor"].lower() == "h3c"]
    for row in h3c_rows:
        sku = row["model"]
        matched = False
        for prof in h3c_profiles:
            try:
                state = svc._validate_profile_known_scope(
                    prof,
                    {"vendor": "H3C", "model": sku, "version": "7.1.070, Release 6717P01"},
                )
                if state == "MATCHED":
                    matched = True
                    break
            except svc.TelemetryServiceError:
                continue
        assert matched, f"H3C catalog model {sku} did not match any H3C Telemetry profile"

    # 2. Verify every Huawei campus and datacenter model (and bare hardware alias) matches at least one Huawei profile.
    huawei_profiles = [p for p in profiles_list if p["vendor"].lower() == "huawei"]
    for row in huawei_rows:
        for alias in model_aliases(row):
            matched = False
            for prof in huawei_profiles:
                try:
                    state = svc._validate_profile_known_scope(
                        prof,
                        {"vendor": "Huawei", "model": alias, "version": "V600R024C10SPC500"},
                    )
                    if state == "MATCHED":
                        matched = True
                        break
                except svc.TelemetryServiceError:
                    continue
            assert matched, f"Huawei catalog model/alias {alias} did not match any Huawei Telemetry profile"

    # 3. Verify H3C & Huawei security/wireless/router models also match cleanly.
    sec_profile = profiles["h3c_grpc_dialout_json_v2_sec_wlan"]
    for sku in ("F1060", "F1090", "F5040", "M9000", "WX3520H", "WX5500E", "WX5540H-HCL", "SR6608", "MSR3620", "MSR5660", "CR16000"):
        state = svc._validate_profile_known_scope(
            sec_profile,
            {"vendor": "H3C", "model": sku, "version": "7.1.064"},
        )
        assert state == "MATCHED", f"Expected MATCHED for H3C {sku}, got {state}"

    hw_campus_profile = profiles["huawei_grpc_dialout_json"]
    for sku in ("NE40E-X8A", "NetEngine 8000 M8", "NetEngine AR6280", "HiSecEngine USG6630E", "AirEngine 9700-M1", "AC6805"):
        state = svc._validate_profile_known_scope(
            hw_campus_profile,
            {"vendor": "Huawei", "model": sku, "version": "V800R021C10SPC500"},
        )
        assert state == "MATCHED", f"Expected MATCHED for Huawei {sku}, got {state}"

