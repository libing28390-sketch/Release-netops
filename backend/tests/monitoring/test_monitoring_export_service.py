from __future__ import annotations

import io
import openpyxl
import pytest

from services.monitoring_export_service import (
    generate_interfaces_report,
    generate_devices_report,
    generate_outbound_report,
    fetch_interfaces_report_data,
    fetch_devices_report_data,
    fetch_outbound_report_data,
)
from services import monitoring_export_service


class DummyCursor:
    def __init__(self, data):
        self.data = data

    def fetchall(self):
        return self.data

    def fetchone(self):
        return self.data[0] if self.data else None


class DummyConnection:
    def __init__(self, table_data=None):
        self.table_data = table_data or []

    def execute(self, query, params=()):
        return DummyCursor(self.table_data)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def disable_external_metric_queries(monkeypatch):
    monkeypatch.setattr(monitoring_export_service, "_query_vm_instant_safe", lambda _query: {})


MOCK_INTERFACES = [
    {
        "id": "if-1",
        "device_id": "dev-1",
        "interface_name": "GigabitEthernet0/1",
        "description": "Uplink to Core",
        "admin_status": "UP",
        "oper_status": "UP",
        "speed": 1000000000,
        "mac_address": "00:11:22:33:44:55",
        "hostname": "SW-CORE-01",
        "ip_address": "192.168.1.1",
        "vendor": "huawei",
        "role": "core",
        "site_name": "武汉数据中心",
    },
    {
        "id": "if-2",
        "device_id": "dev-1",
        "interface_name": "GigabitEthernet0/2",
        "description": "Server Farm",
        "admin_status": "UP",
        "oper_status": "UP",
        "speed": 1000000000,
        "mac_address": "00:11:22:33:44:56",
        "hostname": "SW-CORE-01",
        "ip_address": "192.168.1.1",
        "vendor": "cisco",
        "role": "access",
        "site_name": "北京数据中心",
    }
]

MOCK_DEVICES = [
    {
        "id": "dev-1",
        "hostname": "SW-CORE-01",
        "ip_address": "192.168.1.1",
        "vendor": "huawei",
        "platform": "huawei_vrp",
        "role": "core",
        "status": "online",
        "cpu_usage": 35.5,
        "memory_usage": 42.0,
        "temperature": 38.0,
        "site_name": "武汉数据中心",
    }
]

MOCK_OUTBOUND = [
    {
        "id": "out-1",
        "name": "电信出口探针",
        "target_type": "icmp",
        "target": "114.114.114.114",
        "isp": "中国电信",
        "is_active": True,
    }
]


def test_generate_interfaces_report_xlsx():
    conn = DummyConnection(MOCK_INTERFACES)
    content, filename, media_type = generate_interfaces_report(conn=conn, format_type="xlsx")
    assert filename.startswith("nexora_interfaces_")
    assert filename.endswith(".xlsx")
    assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert content.startswith(b"PK\x03\x04")

    # Load with openpyxl to verify workbook structure and 4 sheets
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert "接口清单与状态" in wb.sheetnames
    assert "流量与利用率统计" in wb.sheetnames
    assert "高利用率预警接口" in wb.sheetnames
    assert "接口错误与丢弃排行" in wb.sheetnames

    ws1 = wb["接口清单与状态"]
    assert ws1.cell(row=1, column=1).value == "设备名称"
    assert ws1.cell(row=2, column=1).value == "SW-CORE-01"


def test_generate_interfaces_report_csv():
    conn = DummyConnection(MOCK_INTERFACES)
    content, filename, media_type = generate_interfaces_report(conn=conn, format_type="csv")
    assert filename.startswith("nexora_interfaces_")
    assert filename.endswith(".csv")
    assert "text/csv" in media_type
    assert content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    text = content.decode("utf-8-sig")
    assert "SW-CORE-01" in text
    assert "GigabitEthernet0/1" in text


def test_generate_devices_report_xlsx_and_csv():
    conn = DummyConnection(MOCK_DEVICES)
    content, filename, media_type = generate_devices_report(conn=conn, format_type="xlsx")
    assert filename.endswith(".xlsx")
    assert content.startswith(b"PK\x03\x04")

    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert "设备运行与资源清单" in wb.sheetnames

    c_content, c_filename, _ = generate_devices_report(conn=conn, format_type="csv")
    assert c_filename.endswith(".csv")
    assert c_content.startswith(b"\xef\xbb\xbf")
    assert "SW-CORE-01" in c_content.decode("utf-8-sig")


def test_generate_outbound_report_xlsx_and_csv():
    conn = DummyConnection(MOCK_OUTBOUND)
    content, filename, media_type = generate_outbound_report(conn=conn, format_type="xlsx")
    assert filename.endswith(".xlsx")
    assert content.startswith(b"PK\x03\x04")

    c_content, c_filename, _ = generate_outbound_report(conn=conn, format_type="csv")
    assert c_filename.endswith(".csv")
    assert c_content.startswith(b"\xef\xbb\xbf")
    assert "电信出口探针" in c_content.decode("utf-8-sig")


def test_fetch_interfaces_report_data_with_filters():
    conn = DummyConnection(MOCK_INTERFACES)
    res = fetch_interfaces_report_data(conn=conn, filters={"vendor": "huawei"})
    assert res["summary"]["total_interfaces"] == 1
    assert res["items"][0]["vendor"] == "huawei"
    assert "huawei" in res["options"]["vendors"]
    assert "cisco" in res["options"]["vendors"]

    res_kw = fetch_interfaces_report_data(conn=conn, filters={"keyword": "Server"})
    assert res_kw["summary"]["total_interfaces"] == 1
    assert res_kw["items"][0]["description"] == "Server Farm"


def test_fetch_devices_and_outbound_data():
    conn_dev = DummyConnection(MOCK_DEVICES)
    res_dev = fetch_devices_report_data(conn=conn_dev)
    assert res_dev["summary"]["total_devices"] == 1
    assert res_dev["summary"]["online_devices"] == 1
    assert res_dev["items"][0]["hostname"] == "SW-CORE-01"

    conn_out = DummyConnection(MOCK_OUTBOUND)
    res_out = fetch_outbound_report_data(conn=conn_out)
    assert res_out["summary"]["total_probes"] == 1
    assert res_out["items"][0]["isp"] == "中国电信"


def test_fetch_devices_report_reads_normalized_hardware_metrics_only(monkeypatch):
    queries = []
    values_by_family = {
        'nexora_hw_cpu_usage_percent{source_type="librenms_rule"}': {"asset:dev-1": 36.2},
        'nexora_hw_memory_usage_percent{source_type="librenms_rule"}': {"asset:dev-1": 43.1},
        'nexora_hw_temperature_celsius{source_type="librenms_rule"}': {"asset:dev-1": 37.5},
    }

    def query_metric(query):
        queries.append(query)
        return values_by_family[query]

    monkeypatch.setattr(monitoring_export_service, "_query_vm_instant_safe", query_metric)

    class RecordingConnection(DummyConnection):
        def __init__(self, table_data=None):
            super().__init__(table_data)
            self.statements = []

        def execute(self, query, params=()):
            self.statements.append(query)
            return super().execute(query, params)

    connection = RecordingConnection(MOCK_DEVICES)
    result = fetch_devices_report_data(conn=connection)

    item = result["items"][0]
    assert queries == [
        'nexora_hw_cpu_usage_percent{source_type="librenms_rule"}',
        'nexora_hw_memory_usage_percent{source_type="librenms_rule"}',
        'nexora_hw_temperature_celsius{source_type="librenms_rule"}',
    ]
    assert "d.cpu_usage" not in connection.statements[0]
    assert "d.memory_usage" not in connection.statements[0]
    assert "d.temp" not in connection.statements[0]
    assert item["cpu_usage"] == 36.2
    assert item["memory_usage"] == 43.1
    assert item["temperature"] == 37.5
    assert item["sample_quality"] == "current"
    assert item["metric_sources"] == {
        "cpu_usage": "victoriametrics",
        "memory_usage": "victoriametrics",
        "temperature": "victoriametrics",
    }


def test_fetch_devices_report_does_not_fallback_to_device_hardware_snapshot(monkeypatch):
    queries = []

    def no_hardware_samples(query):
        queries.append(query)
        return {}

    monkeypatch.setattr(monitoring_export_service, "_query_vm_instant_safe", no_hardware_samples)

    result = fetch_devices_report_data(conn=DummyConnection(MOCK_DEVICES))
    item = result["items"][0]

    assert queries == [
        'nexora_hw_cpu_usage_percent{source_type="librenms_rule"}',
        'nexora_hw_memory_usage_percent{source_type="librenms_rule"}',
        'nexora_hw_temperature_celsius{source_type="librenms_rule"}',
    ]
    assert item["cpu_usage"] is None
    assert item["memory_usage"] is None
    assert item["temperature"] is None
    assert item["temperature_str"] == "--"
    assert item["sample_quality"] == "no_data"
    assert item["risk_level"] == "NO_DATA"
    assert item["metric_sources"] == {
        "cpu_usage": "none",
        "memory_usage": "none",
        "temperature": "none",
    }
    assert result["summary"]["no_data_devices"] == 1
    assert result["summary"]["stale_devices"] == 0
