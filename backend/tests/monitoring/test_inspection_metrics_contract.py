from __future__ import annotations

import math
import json
from collections import Counter

import pytest
from pydantic import ValidationError

from database.migrations import m0289_inspection_item_unit
from database.migrations import m0290_inspection_threshold_direction
from database.migrations import m0291_disable_generic_bgp_inspection_item
from database.seed import (
    BUILTIN_INSPECTION_UNIT_BY_CHECK_KEY,
    _build_network_inspection_items,
    compliance_expected_values,
    get_default_items,
    std_scripts,
)
from schemas.schemas import InspectionItemCreate, InspectionItemUpdate
from core.analysis import analyze_device_inspection
from services import inspection_service


def _expected_catalog_units():
    """Independent catalog contract; intentionally does not read seed defaults."""
    units = {
        "ping": "ms",
        "ssh": "ms",
        "cpu": "%",
        "memory": "%",
        "bgp_neighbor": "个邻居",
        "cpu_load": "%",
        "cpu_util": "%",
        "mem_avail": "%",
        "swap_util": "%",
        "io_wait": "%",
        "disk_util": "%",
        "inode_util": "%",
        "tcp_conns": "个连接",
        "process_health": "个进程",
        "oom_events": "次",
        "ro_mounts": "个挂载",
        "kernel_errs": "条",
        "zombie_procs": "个进程",
        "fd_util": "%",
        "net_errs": "次/秒",
        "ntp_desync": "状态",
        "dns_latency": "ms",
        "recent_reboot": "状态",
        "core_dumps_count": "个文件",
        "disk_io_await": "ms",
        "tcp_close_wait": "个连接",
        "tcp_retrans_pct": "%",
    }
    for vendor in (
        "cisco_ios",
        "cisco_nxos",
        "huawei_vrp",
        "huawei_vrpv8",
        "h3c_comware",
        "juniper_junos",
        "arista_eos",
    ):
        for suffix, unit in (
            ("cpu", "%"),
            ("mem", "%"),
            ("temp", "°C"),
            ("fan", "状态"),
            ("psu", "状态"),
            ("intf_down", "个接口"),
            ("bgp_down", "个邻居"),
            ("ospf_down", "个邻居"),
        ):
            units[f"{vendor}_{suffix}"] = unit
    for vendor in (
        "cisco_ios",
        "huawei_vrp",
        "huawei_vrpv8",
        "h3c_comware",
        "juniper_junos",
    ):
        units[f"{vendor}_route_total"] = "条"
    units.update(
        {
            "cisco_ios_ntp_status": "状态",
            "cisco_ios_syslog_count": "个日志主机",
            "cisco_ios_aaa_status": "状态",
            "cisco_ios_telnet_status": "状态",
            "cisco_ios_ssh_version": "版本",
            "cisco_ios_snmp_community": "状态",
        }
    )
    return units


_SERVER_SCRIPT_BY_CHECK_KEY = {
    "cpu_load": "std_linux_load",
    "cpu_util": "std_linux_cpu",
    "mem_avail": "std_linux_mem",
    "swap_util": "std_linux_swap",
    "io_wait": "std_linux_iowait",
    "disk_util": "std_linux_disk",
    "inode_util": "std_linux_inode",
    "tcp_conns": "std_linux_conns",
    "process_health": "std_linux_proc",
    "oom_events": "std_linux_oom_events",
    "ro_mounts": "std_linux_ro_mounts",
    "kernel_errs": "std_linux_kernel_errs",
    "zombie_procs": "std_linux_zombie_procs",
    "fd_util": "std_linux_fd_util",
    "net_errs": "std_linux_net_errs",
    "ntp_desync": "std_linux_ntp_desync",
    "dns_latency": "std_linux_dns_latency",
    "recent_reboot": "std_linux_recent_reboot",
    "core_dumps_count": "std_linux_core_dumps_count",
    "disk_io_await": "std_linux_disk_io_await",
    "tcp_close_wait": "std_linux_tcp_close_wait",
    "tcp_retrans_pct": "std_linux_tcp_retrans_pct",
}

_EXPECTED_SCRIPT_IDS = {
    *_SERVER_SCRIPT_BY_CHECK_KEY.values(),
    "std_linux_integrated",
    "insp_cisco_ios_full",
    "insp_cisco_nxos_full",
    "insp_huawei_vrp_full",
    "insp_huawei_vrpv8_full",
    "insp_h3c_comware_full",
    "insp_juniper_junos_full",
    "insp_arista_eos_full",
    "insp_ruijie_rgos_full",
    "insp_h3c_firewall_cli",
    "insp_h3c_wireless_ac_cli",
    "insp_huawei_firewall_cli",
    "insp_huawei_wireless_ac_cli",
    "insp_linux_full",
    "oneclick_network_inspect",
    "oneclick_server_inspect",
}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, ("SUCCESS", "")),
        (1, ("WARNING", "warning")),
        (2, ("ERROR", "critical")),
        (3, ("NOT_COLLECTED", "")),
    ],
)
def test_snmp_component_numeric_state_enum(value, expected):
    assert inspection_service._classify_inspection_status(
        value,
        "ok",
        component_state=True,
    ) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ok", ("SUCCESS", "")),
        ("warning", ("WARNING", "warning")),
        ("failed", ("ERROR", "critical")),
        ("unknown", ("NOT_COLLECTED", "")),
        ("unavailable", ("NOT_COLLECTED", "")),
    ],
)
def test_snmp_component_string_states(value, expected):
    assert inspection_service._classify_inspection_status(
        value,
        "ok",
        component_state=True,
    ) == expected


def test_non_component_numeric_status_is_not_treated_as_librenms_enum():
    assert inspection_service._normalize_inspection_status(0, component_state=False) == "0"
    assert inspection_service._classify_inspection_status(0, component_state=False) == (
        "ERROR",
        "warning",
    )
    assert inspection_service._classify_inspection_status(0.0, "0") == ("SUCCESS", "")
    assert inspection_service._classify_inspection_status(1.0, "0") == ("WARNING", "warning")


def test_compliance_expected_value_keeps_phrase_match_without_accepting_negation():
    assert inspection_service._inspection_status_matches_expected(
        "aaa new-model active",
        "aaa new-model",
        allow_substring=True,
    )
    assert not inspection_service._inspection_status_matches_expected(
        "unsynchronized",
        "synchronized",
        allow_substring=True,
    )


@pytest.mark.parametrize(
    ("value", "metric_status", "expected_analysis"),
    [
        (0, "SUCCESS", "healthy"),
        (1, "WARNING", "warning"),
        ("unknown", "NOT_COLLECTED", None),
    ],
)
def test_analysis_honors_status_contract_and_missing_state(value, metric_status, expected_analysis):
    analysis = analyze_device_inspection(
        {},
        {"ntp_desync": value, "ntp_desync_status": metric_status},
        [{
            "check_key": "ntp_desync",
            "name_zh": "NTP 状态",
            "method": "Shell",
            "parse_type": "status",
            "expected_value": "0",
        }],
    )
    if expected_analysis is None:
        assert analysis == []
    else:
        assert analysis[0]["status"] == expected_analysis


def test_analysis_uses_below_direction_for_syslog_count():
    item = {
        "check_key": "cisco_ios_syslog_count",
        "name_zh": "Syslog 主机数",
        "parse_type": "count",
        "warning_threshold": 1,
        "critical_threshold": None,
        "threshold_direction": "below",
        "unit": "个日志主机",
    }
    below = analyze_device_inspection({}, {"cisco_ios_syslog_count": 0}, [item])
    boundary = analyze_device_inspection({}, {"cisco_ios_syslog_count": 1}, [item])
    assert below[0]["status"] == "warning"
    assert below[0]["unit"] == "个日志主机"
    assert "个日志主机" in below[0]["conclusion"]
    assert "低于阈值" in below[0]["conclusion"]
    assert boundary[0]["status"] == "healthy"


def test_analysis_diff_threshold_uses_change_percent_not_raw_count():
    analysis = analyze_device_inspection(
        {},
        {"cisco_ios_route_total": 100},
        [{
            "check_key": "cisco_ios_route_total",
            "name_zh": "路由数",
            "parse_type": "diff",
            "warning_threshold": 10,
            "critical_threshold": 30,
            "threshold_direction": "above",
        }],
        {"cisco_ios_route_total": 90},
    )
    assert analysis[0]["status"] == "warning"


def test_analysis_skips_not_applicable_metrics():
    assert analyze_device_inspection(
        {},
        {"swap_util": 0, "swap_util_status": "NOT_APPLICABLE"},
        [{
            "check_key": "swap_util",
            "name_zh": "Swap 使用率",
            "parse_type": "numeric",
            "warning_threshold": 70,
            "critical_threshold": 90,
            "unit": "%",
        }],
    ) == []


@pytest.mark.parametrize(("value", "expected_status"), [(0, "healthy"), (2, "critical")])
def test_analysis_maps_only_snmp_component_state_codes_and_includes_unit(value, expected_status):
    analysis = analyze_device_inspection(
        {},
        {"cisco_ios_fan": value},
        [{
            "check_key": "cisco_ios_fan",
            "name_zh": "风扇状态",
            "method": "SNMP",
            "parse_type": "status",
            "expected_value": "ok",
            "unit": "状态",
        }],
    )
    assert analysis[0]["status"] == expected_status
    assert analysis[0]["unit"] == "状态"


def test_analysis_compliance_expected_substring_does_not_accept_negated_state():
    analysis = analyze_device_inspection(
        {},
        {"cisco_ios_ntp_status": "unsynchronized"},
        [{
            "check_key": "cisco_ios_ntp_status",
            "name_zh": "NTP 同步",
            "category": "compliance",
            "method": "CLI",
            "parse_type": "status",
            "expected_value": "synchronized",
            "unit": "状态",
        }],
    )
    assert analysis[0]["status"] == "warning"


def test_missing_and_stale_snmp_values_are_not_collected():
    assert inspection_service._classify_inspection_status(
        None,
        "ok",
        component_state=True,
    ) == ("NOT_COLLECTED", "")
    assert inspection_service._is_unavailable_snmp_snapshot_error(
        "没有可用的完整 IF-MIB 接口状态快照"
    )
    assert not inspection_service._is_unavailable_snmp_snapshot_error(
        "SNMP BGP 邻居采集失败（TimeoutError）"
    )


def test_threshold_directions_and_count_fallback_include_valid_zero(monkeypatch):
    crossed = inspection_service._inspection_threshold_is_crossed
    assert not crossed(0, 1, "above")
    assert crossed(1, 1, "above")
    assert crossed(0, 1, "below")
    assert not crossed(1, 1, "below")

    item_tuple = next(
        item
        for item in _build_network_inspection_items("synthetic")
        if item[4] == "cisco_ios_syslog_count"
    )
    item = {
        "command": item_tuple[7],
        "parse_type": item_tuple[15],
        "textfsm_template": item_tuple[16],
        "parse_field": item_tuple[17],
        "parse_filter": item_tuple[18],
        "fallback_regex": item_tuple[19],
        "vendor": item_tuple[11],
    }
    for output, expected_count in (
        ("", 0),
        ("logging host 192.0.2.10\n", 1),
        ("logging host 192.0.2.10\nlogging host 192.0.2.11\n", 2),
    ):
        value, error = inspection_service._extract_item_value(
            item,
            {item["command"]: output},
        )
        assert (value, error) == (expected_count, "")

    from core import textfsm as textfsm_core

    monkeypatch.setattr(inspection_service, "parse_with_textfsm", lambda *args, **kwargs: [])
    monkeypatch.setattr(textfsm_core, "_find_template", lambda *args, **kwargs: None)
    value, error = inspection_service._extract_item_value(
        item,
        {item["command"]: "Unrecognized command"},
    )
    assert value is None
    assert error


def _cisco_snmp_community_item():
    row = next(
        item
        for item in _build_network_inspection_items("synthetic")
        if item[4] == "cisco_ios_snmp_community"
    )
    return {
        "id": row[0],
        "name": row[1],
        "name_zh": row[2],
        "category": row[3],
        "check_key": row[4],
        "description": row[5],
        "method": row[6],
        "command": row[7],
        "script_id": row[8],
        "warning_threshold": row[9],
        "critical_threshold": row[10],
        "vendor": row[11],
        "parse_type": row[15],
        "textfsm_template": row[16],
        "parse_field": row[17],
        "parse_filter": row[18],
        "fallback_regex": row[19],
        "enabled": row[20],
        "expected_value": row[21],
        "unit": row[22],
        "threshold_direction": row[23],
    }


@pytest.mark.parametrize(
    ("output", "expected_value"),
    [
        ("Community name: public\nCommunity name: private\n", "unsafe"),
        ("Community name: private-app-secret\n", "safe"),
        ("Community name:\n", "unsafe"),
    ],
)
def test_snmp_community_parser_returns_only_safe_state(output, expected_value):
    value, error = inspection_service._extract_item_value(
        _cisco_snmp_community_item(),
        {"show snmp community": output},
    )
    assert value == expected_value
    assert error == ""
    assert value not in output


@pytest.mark.parametrize(
    "output",
    [
        "",
        "No community strings configured\n",
        "__ERROR__: command failed\n",
        "% Invalid input detected at '^' marker.\n",
    ],
)
def test_snmp_community_missing_or_failed_output_never_passes(output):
    value, error = inspection_service._extract_item_value(
        _cisco_snmp_community_item(),
        {"show snmp community": output},
    )
    assert value is None
    assert error


@pytest.mark.parametrize(
    ("output", "expected_value", "expected_metric_status"),
    [
        ("Community name: cust-secret-safe\n", "safe", "SUCCESS"),
        ("Community name: public\nCommunity name: cust-secret\n", "unsafe", "WARNING"),
    ],
)
def test_snmp_community_secret_is_not_persisted_in_inspection_result(
    monkeypatch,
    output,
    expected_value,
    expected_metric_status,
):
    item = _cisco_snmp_community_item()
    monkeypatch.setattr(
        inspection_service,
        "_ping_device",
        lambda *args, **kwargs: {"success": True, "latency_ms": 1.0, "loss_percent": 0},
    )
    monkeypatch.setattr(
        inspection_service,
        "_check_ssh",
        lambda *args, **kwargs: {"success": True, "latency_ms": 1.0, "error": ""},
    )
    monkeypatch.setattr(
        inspection_service,
        "_netmiko_collect",
        lambda device, commands, use_admin_creds: {item["command"]: output},
    )
    monkeypatch.setattr(inspection_service, "_get_last_metrics_dict", lambda device_id: {})
    monkeypatch.setattr(inspection_service, "_get_correlation_rules_cached", lambda: [])

    result = inspection_service._inspect_network_device(
        {"id": "synthetic", "ip_address": "192.0.2.10", "hostname": "synthetic", "platform": "cisco_ios"},
        {},
        [item],
    )

    metrics = json.loads(result["metrics_json"])
    findings = json.loads(result["findings_json"])
    analysis = json.loads(result["analysis_json"])
    raw_outputs = json.loads(result["raw_outputs_json"])
    assert metrics["cisco_ios_snmp_community"] == expected_value
    assert metrics["cisco_ios_snmp_community_status"] == expected_metric_status
    assert analysis[0]["value"] == expected_value
    assert analysis[0]["unit"] == "状态"
    persisted = json.dumps([metrics, findings, analysis, raw_outputs], ensure_ascii=False)
    assert "cust-secret" not in persisted
    assert "public" not in persisted
    assert "<redacted>" in result["raw_outputs_json"]


def test_icmp_and_tcp_metrics_reuse_shared_probes_and_apply_thresholds(monkeypatch):
    calls = Counter()

    def ping(*args, **kwargs):
        calls["icmp"] += 1
        return {"success": True, "latency_ms": 150.0, "loss_percent": 0.0}

    def tcp(*args, **kwargs):
        calls["tcp"] += 1
        return {"success": True, "latency_ms": 750.0, "error": ""}

    monkeypatch.setattr(inspection_service, "_ping_device", ping)
    monkeypatch.setattr(inspection_service, "_check_ssh", tcp)
    monkeypatch.setattr(inspection_service, "_get_last_metrics_dict", lambda device_id: {})
    monkeypatch.setattr(inspection_service, "_get_correlation_rules_cached", lambda: [])
    monkeypatch.setattr(inspection_service, "analyze_device_inspection", lambda *args: [])
    result = inspection_service._inspect_network_device(
        {"id": "synthetic", "ip_address": "192.0.2.8", "hostname": "synthetic", "platform": "cisco_ios"},
        {},
        [
            {
                "check_key": "ping",
                "name_zh": "Ping时延",
                "method": "ICMP",
                "parse_type": "numeric",
                "warning_threshold": 100,
                "critical_threshold": 200,
                "threshold_direction": "above",
            },
            {
                "check_key": "ssh",
                "name_zh": "SSH端口连接时延",
                "method": "TCP",
                "parse_type": "numeric",
                "warning_threshold": 500,
                "critical_threshold": 2000,
                "threshold_direction": "above",
            },
        ],
    )

    metrics = json.loads(result["metrics_json"])
    assert metrics["ping"] == 150.0
    assert metrics["ping_status"] == "WARNING"
    assert metrics["ssh"] == 750.0
    assert metrics["ssh_status"] == "WARNING"
    assert result["health_status"] == "warning"
    assert calls == {"icmp": 1, "tcp": 1}
    assert sum(item["type"] == "data_error" for item in json.loads(result["findings_json"])) == 2


def test_tcp_probe_failure_is_not_duplicated_as_metric_alert(monkeypatch):
    monkeypatch.setattr(
        inspection_service,
        "_ping_device",
        lambda *args, **kwargs: {"success": True, "latency_ms": 10.0, "loss_percent": 0.0},
    )
    monkeypatch.setattr(
        inspection_service,
        "_check_ssh",
        lambda *args, **kwargs: {"success": False, "latency_ms": None, "error": "connection refused"},
    )
    result = inspection_service._inspect_network_device(
        {"id": "synthetic", "ip_address": "192.0.2.9", "hostname": "synthetic", "platform": "cisco_ios"},
        {},
        [{
            "check_key": "ssh",
            "name_zh": "SSH端口连接时延",
            "method": "TCP",
            "parse_type": "numeric",
            "warning_threshold": 500,
            "critical_threshold": 2000,
            "threshold_direction": "above",
        }],
    )
    metrics = json.loads(result["metrics_json"])
    findings = json.loads(result["findings_json"])
    assert metrics["ssh"]["value"] is None
    assert metrics["ssh_status"] == "NOT_COLLECTED"
    assert sum(item["type"] == "connectivity_error" for item in findings) == 1
    assert not any(item["type"] == "data_error" for item in findings)


@pytest.mark.parametrize(
    ("script_output", "expected_status", "finding_count"),
    [("0\n", "SUCCESS", 0), ("1\n", "WARNING", 1), ("NA\n", "NOT_COLLECTED", 0)],
)
def test_server_status_metrics_use_expected_value_and_missing_state(
    monkeypatch,
    script_output,
    expected_status,
    finding_count,
):
    class _Rows:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class _Connection:
        def execute(self, query, params):
            script_id = params[0]
            return _Rows(None if script_id == "insp_linux_full" else {"content": "synthetic"})

        def close(self):
            pass

    monkeypatch.setattr(inspection_service, "get_db_connection", _Connection)
    monkeypatch.setattr(
        inspection_service,
        "_execute_shell_script",
        lambda *args, **kwargs: script_output,
    )
    monkeypatch.setattr(inspection_service, "_get_last_metrics_dict", lambda device_id: {})
    monkeypatch.setattr(inspection_service, "analyze_device_inspection", lambda *args: [])
    item = {
        "check_key": "ntp_desync",
        "name": "NTP sync status",
        "name_zh": "NTP 时间同步状态",
        "category": "Server",
        "method": "Shell",
        "script_id": "std_linux_ntp_desync",
        "parse_type": "status",
        "expected_value": "0",
        "unit": "状态",
        "warning_threshold": None,
        "critical_threshold": None,
        "threshold_direction": "above",
    }
    result = inspection_service._inspect_server_device(
        {"id": "synthetic", "ip_address": "192.0.2.10", "hostname": "synthetic", "platform": "Linux"},
        {},
        [item],
    )

    metrics = json.loads(result["metrics_json"])
    findings = json.loads(result["findings_json"])
    assert metrics["ntp_desync_status"] == expected_status
    assert sum(entry["type"] == "data_error" for entry in findings) == finding_count


def test_aggregate_script_missing_metric_is_not_collected(monkeypatch):
    class _Rows:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class _Connection:
        def execute(self, query, params):
            if params == ("insp_linux_full",):
                return _Rows({"content": "synthetic aggregate"})
            return _Rows(None)

        def close(self):
            pass

    monkeypatch.setattr(inspection_service, "get_db_connection", _Connection)
    monkeypatch.setattr(
        inspection_service,
        "_execute_shell_script",
        lambda *args, **kwargs: "--- METRICS ---\nother_metric: 42\n====================",
    )
    monkeypatch.setattr(inspection_service, "_get_last_metrics_dict", lambda device_id: {})
    monkeypatch.setattr(inspection_service, "analyze_device_inspection", lambda *args: [])
    item = {
        "check_key": "cpu_util",
        "name": "CPU utilization",
        "name_zh": "CPU 使用率",
        "category": "Server",
        "method": "Shell",
        "parse_type": "numeric",
        "unit": "%",
    }
    result = inspection_service._inspect_server_device(
        {"id": "synthetic", "ip_address": "192.0.2.10", "hostname": "synthetic", "platform": "Linux"},
        {},
        [item],
    )
    metrics = json.loads(result["metrics_json"])
    assert metrics["cpu_util_status"] == "NOT_COLLECTED"
    assert metrics["cpu_util"]["value"] is None


@pytest.mark.parametrize(
    ("exit_status", "stdout", "expected"),
    [(0, b"NA\n", "NA"), (2, b"42\n", "ERROR: 脚本进程退出状态 2")],
)
def test_shell_runner_distinguishes_script_exit_failure(monkeypatch, exit_status, stdout, expected):
    import paramiko
    import services.vault_service as vault_service
    import drivers.ssh_compat as ssh_compat

    class _Channel:
        def recv_exit_status(self):
            return exit_status

    class _Stream:
        def __init__(self, payload):
            self.payload = payload
            self.channel = _Channel()

        def read(self):
            return self.payload

    class _SSHClient:
        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, *args, **kwargs):
            pass

        def exec_command(self, *args, **kwargs):
            return None, _Stream(stdout), _Stream(b"")

        def close(self):
            pass

    monkeypatch.setattr(paramiko, "SSHClient", _SSHClient)
    monkeypatch.setattr(vault_service, "resolve_device_credentials", lambda device: {
        "normal_username": "synthetic",
        "normal_password": "synthetic",
    })
    monkeypatch.setattr(ssh_compat, "build_paramiko_compatibility_kwargs", lambda profile: {})
    assert inspection_service._execute_shell_script(
        "192.0.2.12",
        "synthetic-script",
        {},
    ) == expected


def test_inspection_item_schema_accepts_signed_finite_thresholds_and_contract_fields():
    created = InspectionItemCreate(
        name="Temperature",
        name_zh="温度",
        category="Network",
        check_key="temperature",
        method="SNMP",
        script_id="temperature-script",
        warning_threshold=-5,
        critical_threshold=0,
        parse_type="numeric",
        expected_value="",
        unit="°C",
        threshold_direction="below",
    )
    assert created.warning_threshold == -5
    assert created.unit == "°C"
    assert created.threshold_direction == "below"
    update = InspectionItemUpdate(
        script_id="updated-script",
        warning_threshold=-10,
        parse_type="status",
        expected_value="ok",
        unit="状态",
        threshold_direction="above",
    )
    assert update.model_dump(exclude_unset=True) == {
        "script_id": "updated-script",
        "warning_threshold": -10,
        "parse_type": "status",
        "expected_value": "ok",
        "unit": "状态",
        "threshold_direction": "above",
    }

    with pytest.raises(ValidationError):
        InspectionItemCreate(
            name="Bad metric",
            name_zh="错误指标",
            category="Network",
            check_key="bad_metric",
            parse_type="unsupported",
        )
    with pytest.raises(ValidationError):
        InspectionItemUpdate(warning_threshold=math.inf)
    with pytest.raises(ValidationError):
        InspectionItemCreate(
            name="Bad direction",
            name_zh="方向错误",
            category="Network",
            check_key="bad_direction",
            threshold_direction="sideways",
        )


def test_builtin_inspection_unit_catalog_covers_94_seed_items():
    defaults = get_default_items("2026-10-23T00:00:00+08:00")
    network = _build_network_inspection_items("2026-10-23T00:00:00+08:00")
    assert len(defaults) + len(network) == 94
    catalog = defaults + network
    actual_keys = {item[4] for item in catalog}
    expected_units = _expected_catalog_units()
    assert len(actual_keys) == 94
    assert actual_keys == set(expected_units)
    assert BUILTIN_INSPECTION_UNIT_BY_CHECK_KEY == expected_units
    assert {item[4]: item[15] for item in defaults} | {item[4]: item[22] for item in network} == expected_units
    assert {key for key, unit in expected_units.items() if not unit} == set()

    network_by_key = {item[4]: item for item in network}
    assert Counter(item[15] for item in network) == {
        "numeric": 21,
        "count": 22,
        "status": 19,
        "diff": 5,
    }
    assert Counter(item[6] for item in network) == {"SNMP": 56, "CLI": 11}
    for item in network:
        key = item[4]
        if key.endswith(("_fan", "_psu")):
            assert item[6] == "SNMP"
            assert item[15] == "status"
            assert item[21] == "ok"
            assert item[9] is item[10] is None
            assert item[22] == "状态"
            assert item[23] == "above"
        elif key.endswith(("_cpu", "_mem")):
            assert (item[9], item[10]) == (80, 90)
        elif key.endswith("_temp"):
            assert item[22] == "°C"
            assert (item[9], item[10]) == (55, 70)
        elif key.endswith("_intf_down"):
            assert item[15] == "count"
            assert (item[9], item[10]) == (1, 3)
        elif key.endswith(("_bgp_down", "_ospf_down")):
            assert item[15] == "count"
            assert (item[9], item[10]) == (1, 2)
        elif key.endswith("_route_total"):
            assert item[15] == "diff"
            assert item[22] == "条"
            assert (item[9], item[10]) == (10, 30)

    expected_compliance_states = {
        "compliance_cisco_ios_ntp": "synchronized",
        "compliance_cisco_ios_aaa": "aaa new-model",
        "compliance_cisco_ios_telnet": "ssh",
        "compliance_cisco_ios_ssh_ver": "2.0",
        "compliance_cisco_ios_snmp": "safe",
    }
    assert compliance_expected_values == expected_compliance_states
    for key, expected in expected_compliance_states.items():
        metric = network_by_key[
            {
                "compliance_cisco_ios_ntp": "cisco_ios_ntp_status",
                "compliance_cisco_ios_aaa": "cisco_ios_aaa_status",
                "compliance_cisco_ios_telnet": "cisco_ios_telnet_status",
                "compliance_cisco_ios_ssh_ver": "cisco_ios_ssh_version",
                "compliance_cisco_ios_snmp": "cisco_ios_snmp_community",
            }[key]
        ]
        assert metric[15] == "status"
        assert metric[22] == "状态" or metric[22] == "版本"
        assert metric[9] is metric[10] is None
        assert expected == compliance_expected_values[key]

    syslog = network_by_key["cisco_ios_syslog_count"]
    assert syslog[15] == "count"
    assert syslog[7] == "show running-config | include ^logging host"
    assert syslog[9] == 1 and syslog[10] is None
    assert syslog[22] == "个日志主机"
    assert syslog[23] == "below"

    defaults_by_key = {item[4]: item for item in defaults}
    bgp = defaults_by_key["bgp_neighbor"]
    assert bgp[6] == "SNMP"
    assert bgp[15] == "个邻居"
    assert bgp[16] == "count"
    assert bgp[18] == "above"
    assert bgp[9] == 1 and bgp[10] is None
    assert bgp[19] == 0
    assert all(item[20] == 1 for item in network)
    assert defaults_by_key["ntp_desync"][16:19] == ("status", "0", "above")
    assert defaults_by_key["ntp_desync"][9:11] == (None, None)
    assert defaults_by_key["recent_reboot"][16:19] == ("status", "0", "above")
    assert defaults_by_key["recent_reboot"][9:11] == (None, None)


def test_seeded_script_catalog_and_server_bindings_match_output_contract():
    defaults = get_default_items("2026-10-23T00:00:00+08:00")
    server_items = {item[4]: item for item in defaults if item[3] == "Server"}
    scripts = {script[0]: script for script in std_scripts}
    assert len(std_scripts) == 38
    assert set(scripts) == _EXPECTED_SCRIPT_IDS
    assert set(server_items) == set(_SERVER_SCRIPT_BY_CHECK_KEY)
    for check_key, script_id in _SERVER_SCRIPT_BY_CHECK_KEY.items():
        item = server_items[check_key]
        assert item[6] == "Shell"
        assert item[8] == script_id
        assert item[15] == BUILTIN_INSPECTION_UNIT_BY_CHECK_KEY[check_key]
        assert scripts[script_id][2].startswith("#!/bin/bash")

    integrated = scripts["std_linux_integrated"][2]
    assert all(f'echo "{check_key}:' in integrated for check_key in _SERVER_SCRIPT_BY_CHECK_KEY)
    assert "tcp_retrans_pct=0" not in integrated
    assert 'Reference ID' not in integrated
    assert 'www.baidu.com' not in integrated

    comprehensive = scripts["insp_linux_full"][2]
    assert 'load_pct="NA"' in comprehensive
    assert 'mem_util="NA"' in comprehensive
    assert 'swap_util="NA"' in comprehensive
    assert 'tcp_retrans_pct="NA"' in comprehensive
    assert 'else print 0, 0' not in comprehensive
    assert 'tcp_retrans_pct:-0' not in comprehensive

    # Output sentinels and final aggregate markers are parsed by the numeric
    # shell consumer. These examples guard against extracting a number from
    # explanatory headings when a script reports no data.
    assert inspection_service._extract_numeric_value("42.50\n") == 42.5
    assert inspection_service._extract_numeric_value("tcp_retrans_pct:2.75\n") == 2.75
    assert inspection_service._extract_numeric_value(
        "Detailed Disk Usage (Top 10):\nMAX_UTILIZATION: 65"
    ) == 65
    assert inspection_service._extract_numeric_value(
        "Detailed Disk Usage (Top 10):\nMAX_UTILIZATION: NA"
    ) is None
    for output in ("", "NA", "MAX_INODE_UTIL: NA", "NOT_COLLECTED"):
        assert inspection_service._is_no_data_metric_output(output)


def test_network_script_bundles_only_use_platform_read_only_catalog_commands():
    from services.operational_data_service import COMMAND_CATALOG
    from services.platform_registry_service import PLATFORM_ACTION_COMMANDS

    scripts = {script[0]: script for script in std_scripts}
    expected = {
        "insp_cisco_ios_full": "cisco_ios",
        "insp_cisco_nxos_full": "cisco_nxos",
        "insp_huawei_vrp_full": "huawei_vrp",
        "insp_huawei_vrpv8_full": "huawei_vrpv8",
        "insp_h3c_comware_full": "h3c_comware",
        "insp_juniper_junos_full": "juniper_junos",
        "insp_arista_eos_full": "arista_eos",
        "insp_ruijie_rgos_full": "ruijie_rgos",
    }
    assert set(expected).issubset(scripts)
    for script_id, platform in expected.items():
        script = scripts[script_id]
        commands = script[2].splitlines()
        platform_commands = {
            command
            for commands_for_category in (COMMAND_CATALOG.get(platform) or {}).values()
            for command in commands_for_category
        }
        platform_commands.update((PLATFORM_ACTION_COMMANDS.get(platform) or {}).values())
        assert commands
        assert all(command in platform_commands for command in commands)
        assert all(command.startswith(("show ", "display ", "dis ")) for command in commands)
        assert "综合巡检" not in script[1]
        assert "综合巡检" not in script[3]
        assert "display ip routing-table verbose" not in commands
        assert "display ip routing-table" not in commands
        assert "show ip route" not in commands

    # Guard Linux safety fixes & new one-click scripts
    assert "squashfs" in scripts["std_linux_ro_mounts"][2]
    assert "-maxdepth 2" in scripts["std_linux_core_dumps_count"][2]
    assert "display ip routing-table statistics" in scripts["oneclick_network_inspect"][2]
    assert "OVERALL_STATUS=" in scripts["oneclick_server_inspect"][2]


def test_inspection_item_vendor_facet_uses_raw_values_and_ignores_selected_vendor(isolated_db):
    result = inspection_service.list_inspection_items(
        category="Network",
        method="SNMP",
        vendor="cisco_ios",
        page=1,
        page_size=1,
    )
    vendors = result["facets"]["vendors"]
    assert result["total"] > 1
    assert result["page_size"] == 1
    assert vendors["cisco_ios"] > 0
    assert vendors["huawei_vrp"] > 0
    assert sum(vendors.values()) > result["page_size"]


def test_inspection_item_crud_persists_execution_fields_and_unit(isolated_db):
    payload = InspectionItemCreate(
        name="Synthetic status metric",
        name_zh="合成状态指标",
        category="Network",
        check_key="synthetic_status_metric",
        method="SNMP",
        script_id="synthetic-script",
        warning_threshold=-2,
        critical_threshold=3,
        parse_type="numeric",
        expected_value="",
        unit="°C",
        threshold_direction="below",
    ).model_dump()
    created = inspection_service.create_inspection_item(payload)
    assert created["script_id"] == "synthetic-script"

    patch = InspectionItemUpdate(
        script_id="synthetic-script-v2",
        warning_threshold=-1,
        critical_threshold=4,
        parse_type="status",
        expected_value="ok",
        unit="状态",
        threshold_direction="above",
    ).model_dump(exclude_unset=True)
    updated = inspection_service.update_inspection_item(created["id"], patch)
    assert updated is not None
    assert {
        key: updated[key]
        for key in (
            "script_id", "warning_threshold", "critical_threshold", "parse_type",
            "expected_value", "unit", "threshold_direction",
        )
    } == {
        "script_id": "synthetic-script-v2",
        "warning_threshold": -1,
        "critical_threshold": 4,
        "parse_type": "status",
        "expected_value": "ok",
        "unit": "状态",
        "threshold_direction": "above",
    }

    conn = isolated_db["module"].get_db_connection()
    try:
        row = conn.execute(
            "SELECT script_id, warning_threshold, critical_threshold, parse_type, expected_value, unit, threshold_direction "
            "FROM inspection_items WHERE id = ?",
            (created["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert dict(row) == {
        "script_id": "synthetic-script-v2",
        "warning_threshold": -1,
        "critical_threshold": 4,
        "parse_type": "status",
        "expected_value": "ok",
        "unit": "状态",
        "threshold_direction": "above",
    }


def test_inspection_item_unit_migration_backfills_known_keys_and_is_repeatable(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        # Model the immediately previous schema: built-in metric rows already
        # exist, but the unit column has not been introduced yet.
        conn.execute("ALTER TABLE inspection_items DROP COLUMN unit")
        conn.execute(
            "INSERT INTO inspection_items "
            "(id, name, name_zh, category, check_key, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("synthetic-unknown-unit", "Unknown unit", "未知单位", "Network", "synthetic_unknown_unit", "x", "x"),
        )
        m0289_inspection_item_unit.upgrade(conn.cursor(), use_pg=True)
        conn.execute(
            "UPDATE inspection_items SET unit = 'custom-unit' WHERE check_key = 'cisco_ios_temp'"
        )
        m0289_inspection_item_unit.upgrade(conn.cursor(), use_pg=True)
        row = conn.execute(
            "SELECT unit FROM inspection_items WHERE check_key = 'cisco_ios_cpu'"
        ).fetchone()
        temperature = conn.execute(
            "SELECT unit FROM inspection_items WHERE check_key = 'cisco_ios_temp'"
        ).fetchone()
        bgp = conn.execute(
            "SELECT unit FROM inspection_items WHERE check_key = 'bgp_neighbor'"
        ).fetchone()
        unknown = conn.execute(
            "SELECT unit FROM inspection_items WHERE check_key = 'synthetic_unknown_unit'"
        ).fetchone()
        conn.commit()
    finally:
        conn.close()

    assert row["unit"] == "%"
    assert temperature["unit"] == "custom-unit"
    assert bgp["unit"] == "个邻居"
    assert unknown["unit"] == ""


def test_inspection_threshold_direction_migration_repairs_syslog_contract(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        # Model m0289: thresholds exist, but comparison direction is not stored.
        conn.execute("ALTER TABLE inspection_items DROP COLUMN threshold_direction")
        conn.execute(
            "UPDATE inspection_items SET warning_threshold = 1, critical_threshold = NULL "
            "WHERE id = 'compliance_cisco_ios_syslog'"
        )
        conn.execute(
            "INSERT INTO inspection_items "
            "(id, name, name_zh, category, check_key, warning_threshold, critical_threshold, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "custom_syslog_count",
                "Custom syslog count",
                "自定义日志主机数",
                "Custom",
                "custom_syslog_count",
                1,
                None,
                1,
                "2026-10-23T00:00:00+08:00",
                "2026-10-23T00:00:00+08:00",
            ),
        )
        m0290_inspection_threshold_direction.upgrade(conn.cursor(), use_pg=True)
        m0290_inspection_threshold_direction.upgrade(conn.cursor(), use_pg=True)
        syslog = conn.execute(
            "SELECT warning_threshold, critical_threshold, threshold_direction "
            "FROM inspection_items WHERE id = 'compliance_cisco_ios_syslog'"
        ).fetchone()
        custom = conn.execute(
            "SELECT threshold_direction FROM inspection_items WHERE id = 'custom_syslog_count'"
        ).fetchone()
        cpu = conn.execute(
            "SELECT threshold_direction FROM inspection_items WHERE check_key = 'cisco_ios_cpu'"
        ).fetchone()
        conn.commit()
    finally:
        conn.close()

    assert dict(syslog) == {
        "warning_threshold": 1,
        "critical_threshold": None,
        "threshold_direction": "below",
    }
    assert cpu["threshold_direction"] == "above"
    assert custom["threshold_direction"] == "above"


def test_generic_bgp_placeholder_migration_disables_legacy_row(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "UPDATE inspection_items SET enabled = 1 WHERE id = 'net_bgp'"
        )
        conn.execute(
            "INSERT INTO inspection_items "
            "(id, name, name_zh, category, check_key, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "custom_bgp_counter",
                "Custom BGP Counter",
                "自定义 BGP 计数",
                "Custom",
                "custom_bgp_neighbor_count",
                1,
                "2026-10-23T00:00:00+08:00",
                "2026-10-23T00:00:00+08:00",
            ),
        )
        m0291_disable_generic_bgp_inspection_item.upgrade(conn.cursor(), use_pg=True)
        m0291_disable_generic_bgp_inspection_item.upgrade(conn.cursor(), use_pg=True)
        disabled = conn.execute(
            "SELECT enabled, name_zh, unit, threshold_direction FROM inspection_items WHERE id = 'net_bgp'"
        ).fetchone()
        custom = conn.execute(
            "SELECT enabled FROM inspection_items WHERE id = 'custom_bgp_counter'"
        ).fetchone()
        vendor_items = conn.execute(
            "SELECT count(*) AS count FROM inspection_items "
            "WHERE check_key LIKE '%_bgp_down' AND enabled = 1"
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    assert dict(disabled) == {
        "enabled": 0,
        "name_zh": "BGP 邻居数（默认停用）",
        "unit": "个邻居",
        "threshold_direction": "above",
    }
    assert custom["enabled"] == 1
    assert vendor_items["count"] == 7
