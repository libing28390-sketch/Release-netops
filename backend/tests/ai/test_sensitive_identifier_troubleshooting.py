from __future__ import annotations

import asyncio

from ai.services import assistant as assistant_module
from ai.services.assistant import AIAssistantService
from ai.services.ip_troubleshooting import IPTroubleshootingService
from ai.services.mac_troubleshooting import MACTroubleshootingService


def test_ip_troubleshooting_is_local_only_and_renders_evidence(monkeypatch):
    service = IPTroubleshootingService()
    monkeypatch.setattr(
        service,
        "trace_ip_facts",
        lambda ip, *, tenant_id=None: {
            "target_ip": ip,
            "arp_record": {
                "mac_address": "00:11:22:33:44:55",
                "vlan": 10,
                "interface": "Gi1/0/1",
                "device_id": "dev-1",
            },
            "mac_record": None,
            "device": {
                "id": "dev-1",
                "hostname": "core-1",
                "platform": "cisco_ios",
                "vendor": "Cisco",
                "status": "up",
            },
            "active_alarms": [],
            "recent_diffs": [],
        },
    )

    result = asyncio.run(service.troubleshoot_ip("10.0.0.1", tenant_id="tenant-a"))

    assert result["execution_mode"] == "local_sensitive_identifier"
    assert result["external_egress"] is False
    assert result["analysis"]["analysis_source"] == "local_deterministic"
    assert result["analysis"]["access_switch"] == "core-1"
    assert result["analysis"]["access_port"] == "Gi1/0/1"


def test_mac_troubleshooting_is_local_only_and_normalizes_mac(monkeypatch):
    service = MACTroubleshootingService()
    monkeypatch.setattr(
        service,
        "trace_mac_facts",
        lambda mac, *, tenant_id=None: {
            "raw_mac": mac,
            "normalized_mac": "0011.2233.4455",
            "mac_entry": {
                "ip_address": "10.0.0.1",
                "vlan": 10,
                "interface": "Gi1/0/1",
                "device_id": "dev-1",
                "device_hostname": "access-1",
            },
            "associated_ip": "10.0.0.1",
        },
    )

    result = asyncio.run(service.troubleshoot_mac("00:11:22:33:44:55", tenant_id="tenant-a"))

    assert result["execution_mode"] == "local_sensitive_identifier"
    assert result["external_egress"] is False
    assert result["analysis"]["normalized_mac"] == "0011.2233.4455"
    assert result["analysis"]["located_switch"] == "access-1"
    assert result["analysis"]["located_port"] == "Gi1/0/1"


def test_sync_ip_location_short_circuits_provider_for_confidential_identifier(monkeypatch):
    async def fake_parse_intent(message, user_id=None):
        return {
            "intent": "ip_location",
            "filters": {"ip": "10.0.0.1"},
            "needs_clarification": False,
        }

    async def fake_trace(ip, user_id=None, tenant_id=None):
        return {
            "target_ip": ip,
            "facts": {"target_ip": ip, "arp_record": None, "device": None, "active_alarms": []},
            "analysis": {
                "ip": ip,
                "status_summary": "没有本地证据",
                "root_cause_analysis": "需要刷新采集",
                "recommendations": ["刷新 ARP/MAC"],
            },
            "analysis_source": "local_deterministic",
        }

    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("confidential identifier location must not call a provider")

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.ip_troubleshooting_service, "troubleshoot_ip", fake_trace)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat", forbidden_chat)

    result = asyncio.run(
        AIAssistantService().chat(
            "定位 IP 10.0.0.1",
            user_id="test-user",
            tenant_id="tenant-a",
        )
    )

    assert result["execution_mode"] == "local_sensitive_identifier"
    assert result["external_egress"] is False
    assert "未调用外部模型" in result["answer"]
    assert "ASSISTANT_CONTEXT_ERROR" not in result["answer"]


def test_stream_mac_location_short_circuits_provider_for_confidential_identifier(monkeypatch):
    async def fake_parse_intent(message, user_id=None):
        return {
            "intent": "mac_location",
            "filters": {"mac": "00:11:22:33:44:55"},
            "needs_clarification": False,
        }

    async def fake_trace(mac, user_id=None, tenant_id=None):
        return {
            "mac": mac,
            "facts": {"raw_mac": mac, "normalized_mac": "0011.2233.4455", "mac_entry": None},
            "analysis": {
                "normalized_mac": "0011.2233.4455",
                "path_summary": "没有本地证据",
                "recommendations": ["刷新 MAC 表"],
            },
            "analysis_source": "local_deterministic",
        }

    async def forbidden_chat_stream(*args, **kwargs):
        raise AssertionError("confidential identifier location must not call a provider")
        yield "never"

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.mac_troubleshooting_service, "troubleshoot_mac", fake_trace)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", forbidden_chat_stream)

    async def collect():
        return [event async for event in AIAssistantService().chat_stream(
            "定位 MAC 00:11:22:33:44:55",
            user_id="test-user",
            tenant_id="tenant-a",
        )]

    events = asyncio.run(collect())
    joined = "".join(events)

    assert "整理本地定位结果" in joined
    assert "未调用外部模型" in joined
    assert '"external_egress": false' in joined
    assert "ASSISTANT_CONTEXT_ERROR" not in joined
