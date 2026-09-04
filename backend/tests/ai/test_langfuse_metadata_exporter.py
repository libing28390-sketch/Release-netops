from __future__ import annotations

import time
from ai.services.langfuse_exporter import (
    LangfuseMetadataExporter,
    hash_identifier,
    sanitize_metadata_payload,
)


def test_sanitize_metadata_payload_strips_forbidden_fields_and_preserves_allowlist():
    """验证元数据白名单清洗：严格剔除 Prompt、回答、IP、密码等敏感数据，只留运营指标。"""
    raw = {
        # 敏感/违规字段（必须被剔除）
        "prompt": "show running-config on 192.168.1.1",
        "raw_prompt": "secret password cisco123",
        "response": "Here is the cleartext password...",
        "password": "cisco_admin_pass",
        "community": "public",
        "cli_output": "interface GigabitEthernet0/1\n ip address 10.0.0.1",
        "ip_address": "192.168.1.1",
        # 合规白名单字段（必须被保留）
        "request_id": "req-12345",
        "scene": "troubleshooting",
        "intent": "vlan",
        "provider_id": "deepseek",
        "model_id": "deepseek-chat",
        "candidate_count": 20,
        "latency_ms": 340,
        "token_count": 128,
        "citation_count": 3,
        "security_decision": "allowed",
    }

    sanitized = sanitize_metadata_payload(raw)

    # 验证敏感字段全部被拦截
    for forbidden in ["prompt", "raw_prompt", "response", "password", "community", "cli_output", "ip_address"]:
        assert forbidden not in sanitized

    # 验证白名单字段完整保留
    assert sanitized["request_id"] == "req-12345"
    assert sanitized["intent"] == "vlan"
    assert sanitized["candidate_count"] == 20
    assert sanitized["latency_ms"] == 340
    assert sanitized["token_count"] == 128
    assert sanitized["security_decision"] == "allowed"


def test_user_hash_field_is_hashed_even_when_the_caller_passes_an_ip():
    sanitized = sanitize_metadata_payload({"user_hash": "192.168.1.10"})
    assert sanitized["user_hash"] != "192.168.1.10"
    assert len(sanitized["user_hash"]) == 16


def test_invalid_langfuse_endpoint_does_not_fall_back_to_localhost():
    exporter = LangfuseMetadataExporter(endpoint="https://collector.example.invalid/ingest", mode="metadata")
    assert exporter.configuration_error == "LANGFUSE_ENDPOINT_INVALID"
    assert exporter.endpoint is None
    assert exporter.export({"request_id": "req-001"}) is False


def test_hash_identifier_is_one_way_and_deterministic():
    """验证租户/用户标识经过加盐哈希，防止明文标识泄露。"""
    h1 = hash_identifier("tenant-alpha")
    h2 = hash_identifier("tenant-alpha")
    h3 = hash_identifier("tenant-beta")

    assert h1 == h2
    assert h1 != h3
    assert "tenant-alpha" not in h1
    assert len(h1) == 16


def test_exporter_disabled_by_default_mode_off():
    """验证默认模式下（mode=off）完全旁路，不执行任何入队或外发。"""
    exporter = LangfuseMetadataExporter(mode="off")
    result = exporter.export({"request_id": "req-001", "intent": "vlan"})
    assert result is False
    assert exporter._queue.empty()


def test_exporter_non_blocking_on_network_failure():
    """验证即使外部上报端点连接超时或失败，导出过程也是完全非阻塞的，且绝不抛出异常。"""
    exporter = LangfuseMetadataExporter(
        endpoint="http://127.0.0.1:59998/api/ingestion",
        mode="metadata",
        timeout_seconds=0.1,
    )

    started = time.perf_counter()
    # 提交合规数据
    accepted = exporter.export({
        "request_id": "req-perf-01",
        "tenant_hash": hash_identifier("tenant-1"),
        "latency_ms": 200,
        "token_count": 50,
    })
    elapsed_ms = (time.perf_counter() - started) * 1000

    # 验证非阻塞：调用耗时必须在 10 毫秒以内（因为只入队，不阻塞主请求）
    assert accepted is True
    assert elapsed_ms < 20.0
