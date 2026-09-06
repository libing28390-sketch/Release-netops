"""Pure tests for deterministic CMDB asset analysis routing and rendering.

These tests intentionally do not create SQLite fixtures or connect to a
database. PostgreSQL behavior is verified separately against the configured
PG runtime.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from ai.services.intent_parser import (
    extract_asset_filters,
    intent_parser,
    is_alert_aggregation_query,
    is_asset_analysis_query,
)
from ai.services.natural_query import natural_query_service, render_alert_analysis, render_asset_analysis


def test_inventory_distribution_query_uses_deterministic_intent():
    query = (
        "\u57fa\u4e8e Nexora CMDB \u7edf\u8ba1 20 \u53f0\u7eb3\u7ba1\u8bbe\u5907\u7684\u5382\u5546\u3001\u89d2\u8272\u3001\u7c7b\u578b\u548c\u533a\u57df\u5206\u5e03"
    )

    assert is_asset_analysis_query(query) is True
    intent = asyncio.run(intent_parser.parse_intent(query))
    assert intent["intent"] == "asset_analysis"


def test_inventory_count_query_does_not_depend_on_llm_intent_parsing():
    query = "我们现在有多少台设备"

    assert is_asset_analysis_query(query) is True
    intent = asyncio.run(intent_parser.parse_intent(query))
    assert intent["intent"] == "asset_analysis"


def test_alert_aggregate_query_uses_deterministic_intent(monkeypatch):
    query = "当前未恢复告警数量和最近24小时新增告警"

    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("alert aggregate intent must not call the cloud parser")

    monkeypatch.setattr("ai.services.intent_parser.llm_gateway.chat", forbidden_chat)

    assert is_alert_aggregation_query(query) is True
    intent = asyncio.run(intent_parser.parse_intent(query))
    assert intent["intent"] == "alarm_search"
    assert intent["parse_status"] == "deterministic"
    assert intent["needs_clarification"] is False


def test_plain_recent_alert_request_still_requires_scope():
    assert is_alert_aggregation_query("查询最近的告警") is False


def test_rendered_alert_report_is_metadata_only():
    report = render_alert_analysis(
        "password=NeverEchoThis 查询告警",
        {
            "alerts": {
                "total_count": 2,
                "active_count": 1,
                "recent_24h_count": 2,
                "active_by_severity": {"critical": 1},
                "recent_24h_by_severity": {"critical": 1, "warning": 1},
            },
        },
    )

    assert "当前未恢复告警：**1** 条" in report
    assert "最近 24 小时新增告警：**2** 条" in report
    assert "NeverEchoThis" not in report
    assert "password" not in report


def test_alert_aggregation_is_tenant_scoped_and_keeps_records_out_of_result(isolated_db):
    from database import get_db_connection

    connection = get_db_connection()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    recent = now - timedelta(hours=2)
    old = now - timedelta(days=3)
    try:
        connection.executemany(
            "INSERT INTO devices (id, hostname, tenant_id, site) VALUES (?, ?, ?, ?)",
            [
                ("alert-device-a", "edge-a", "tenant-a", "HQ"),
                ("alert-device-b", "edge-b", "tenant-b", "HQ"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id,
                 created_at, resolved_at, workflow_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("alert-a-active", "key-a-active", "test", "critical", "down", "x", "alert-device-a", recent.isoformat(), None, "open"),
                ("alert-a-resolved", "key-a-resolved", "test", "warning", "recovered", "x", "alert-device-a", recent.isoformat(), (recent + timedelta(minutes=10)).isoformat(), "resolved"),
                ("alert-a-old", "key-a-old", "test", "major", "old", "x", "alert-device-a", old.isoformat(), None, "open"),
                ("alert-b-active", "key-b-active", "test", "critical", "other", "x", "alert-device-b", recent.isoformat(), None, "open"),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    result = asyncio.run(
        natural_query_service.execute_alert_analysis(
            "当前未恢复告警数量和最近24小时新增告警",
            tenant_id="tenant-a",
        )
    )

    assert result["matched_count"] == 3
    assert result["data"] == []
    assert result["analysis"]["alerts"] == {
        "total_count": 3,
        "active_count": 2,
        "recent_24h_count": 2,
        "active_by_severity": {"critical": 1, "major": 1},
        "recent_24h_by_severity": {"critical": 1, "warning": 1},
    }
    assert "alert-device-b" not in result["summary"]


def test_link_aggregation_configuration_is_not_asset_analysis():
    query = (
        "请仅基于本地知识库回答：H3C Comware 7、S5130 的链路聚合 "
        "link-aggregation group 1 mode dynamic 配置、验证和回滚；不要执行设备操作。"
    )

    assert is_asset_analysis_query(query) is False
    intent = asyncio.run(intent_parser.parse_intent(query))
    assert intent["intent"] == "knowledge"
    assert intent["feature"] == "lacp"
    assert intent["knowledge_type"] == "configuration"


def test_feature_scoped_h3c_s6850_configuration_is_not_asset_analysis():
    query = (
        "请仅基于本地知识库回答：H3C S6850 Comware 数据中心交换机 VLAN "
        "接入口配置、验证命令和回滚注意事项；不要执行设备操作。"
    )

    assert is_asset_analysis_query(query) is False
    intent = asyncio.run(intent_parser.parse_intent(query))
    assert intent["intent"] == "knowledge"
    assert intent["product_series"] == "S6850"
    assert intent["feature"] == "access_port"
    assert intent["knowledge_type"] == "configuration"


def test_asset_analysis_extracts_only_unambiguous_filters():
    filters = extract_asset_filters("\u7edf\u8ba1 Huawei \u6838\u5fc3\u4ea4\u6362\u673a WH-DC-02 \u7684\u7248\u672c")

    assert filters == {
        "vendor": "huawei",
        "role": "core",
        "device_category": "switch",
        "site": "WH-DC-02",
    }


def test_asset_analysis_accepts_h3c_chinese_vendor_aliases():
    assert extract_asset_filters("\u7edf\u8ba1\u534e\u4e09\u8bbe\u5907\u6570\u91cf") == {"vendor": "h3c"}
    assert extract_asset_filters("\u7edf\u8ba1\u65b0\u534e\u4e09\u8bbe\u5907\u6570\u91cf") == {"vendor": "h3c"}

    intent = asyncio.run(intent_parser.parse_intent("统计华三设备数量"))
    assert intent["intent"] == "asset_analysis"
    assert intent["filters"] == {"vendor": "h3c"}


def test_rendered_report_does_not_turn_missing_eol_into_a_fact():
    report = render_asset_analysis(
        "\u67e5\u8be2\u7eb3\u7ba1\u8bbe\u5907\u5e76\u5206\u6790\u7248\u672c",
        {
            "total_devices": 2,
            "by_vendor": {"H3C": 2},
            "by_role": {"core": 2},
            "by_type": {"switch": 2},
            "by_site": {"WH-DC-02": 2},
            "by_lifecycle": {"production": 2},
            "by_version": [{"vendor": "H3C", "model": "S6800", "version": "7.1.070", "count": 2}],
            "health": {"online_devices": 2, "cpu_observed_devices": 0, "max_cpu": None, "psu_status": {}},
            "alerts": {"active_count": 0, "recent_24h_count": 0},
            "data_quality": {"missing_version": 2, "missing_site": 0},
            "devices": [],
        },
    )

    assert "H3C" in report
    assert "EOL" in report
    assert "\u4e0d\u80fd\u4ec5\u51ed\u7248\u672c\u53f7\u5224\u5b9a" in report
    assert "Juniper" not in report
