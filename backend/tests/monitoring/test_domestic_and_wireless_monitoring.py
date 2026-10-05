from backend.services.metric_provider import (
    ALLOWED_METRICS,
    CANONICAL_PROMQL,
    VictoriaMetricsMetricProvider,
)
from backend.services.monitoring_oid_catalog import BUILTIN_OID_CATALOG
import os
import json
from monitoring.grafana.generate_dashboards import (
    CLIENT_COLOR,
    CRITICAL_COLOR,
    HEALTHY_COLOR,
    HIGH_COLOR,
    INFO_COLOR,
    INBOUND_COLOR,
    NEUTRAL_COLOR,
    OUTBOUND_COLOR,
    WARNING_COLOR,
    UTILIZATION_THRESHOLDS,
    NO_VALUE_TEXT,
    build_interface_dashboard,
    build_interface_detail_dashboard,
    build_overview_dashboard,
    build_wireless_dashboard,
)


def _iter_panels(panels):
    for panel in panels:
        yield panel
        yield from _iter_panels(panel.get("panels", []))


def test_allowed_metrics_includes_wireless():
    assert "wireless_ap_online_count" in ALLOWED_METRICS
    assert "wireless_client_online_count" in ALLOWED_METRICS


def test_promql_selector_domestic_vendors():
    selector = VictoriaMetricsMetricProvider._selector("cpu_usage_percent", "device-123")
    assert "zteCpuRate" in selector
    assert "mpCpuUtilization5Min" in selector
    assert "dptechCpuUsage" in selector
    assert "hillstoneCPUUtilization" in selector
    assert "sangforCpuUsage" in selector
    assert "dcnCpuUsage" in selector

    mem_selector = VictoriaMetricsMetricProvider._selector("memory_usage_percent", "device-123")
    assert "zteMemRate" in mem_selector
    assert "mpMemoryUtilization" in mem_selector
    assert "dptechMemUsage" in mem_selector
    assert "hillstoneMemoryUtilization" in mem_selector
    assert "sangforMemUsage" in mem_selector
    assert "dcnMemUsage" in mem_selector


def test_promql_selector_wireless_metrics():
    ap_selector = VictoriaMetricsMetricProvider._selector("wireless_ap_online_count", "wlc-1")
    assert "hh3cDot11CurrOnlineAPNum" in ap_selector
    assert "ruijieApcOnlineApNum" in ap_selector
    assert "cLApTotalUpAPs" in ap_selector
    assert "wlsxSysExtAccessPointsNum" in ap_selector
    assert "ruckusZDTotalNumAP" in ap_selector
    assert "hwWlanCurJointApNum" in ap_selector
    assert "hwWlanCurOnlineApNum" not in ap_selector

    client_selector = VictoriaMetricsMetricProvider._selector("wireless_client_online_count", "wlc-1")
    assert "hwWlanSsid2gStaCnt" in client_selector
    assert "hwWlanSsid5gStaCnt" in client_selector
    assert "hwWlanCurAssocUserNum" not in client_selector
    assert "hh3cDot11CurrAssocUserNum" in client_selector
    assert "ruijieApcTotalStaNum" in client_selector
    assert "cLSysTotalNumOfClients" in client_selector
    assert "wlsxSysExtStationsNum" in client_selector
    assert "ruckusZDTotalNumSta" in client_selector


def test_oid_catalog_has_domestic_and_wireless():
    keys = {item["module_key"] for item in BUILTIN_OID_CATALOG}
    expected = {
        "zte_common", "maipu_common", "dptech_common",
        "hillstone_common", "sangfor_common", "dcn_common",
        "huawei_wireless", "h3c_wireless", "ruijie_wireless",
        "cisco_wireless", "aruba_wireless", "ruckus_wireless",
    }
    missing = expected - keys
    assert not missing, f"Missing expected modules in catalog: {missing}"


def test_dashboards_suite_completeness():
    dashboard_dir = os.path.join("monitoring", "grafana", "dashboards")
    expected_files = [
        "nexora-network-overview.json",
        "nexora-network-device.json",
        "nexora-network-wireless.json",
        "nexora-network-interface.json",
        "nexora-interface-detail.json",
        "nexora-monitoring-health.json",
        "nexora-network-outbound.json",
        "nexora-linux-metrics.json",
        "nexora-windows-metrics.json",
        "nexora-platform-health.json",
        "nexora-outbound-probe-quality.json",
        "nexora-alert-operations.json",
    ]
    for filename in expected_files:
        path = os.path.join(dashboard_dir, filename)
        assert os.path.exists(path), f"Dashboard file {filename} missing"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "uid" in data
            assert len(data.get("panels", [])) > 0
            for panel in _iter_panels(data.get("panels", [])):
                if panel.get("type") == "stat":
                    assert panel.get("targets") and all(
                        target.get("instant") is True
                        for target in panel["targets"]
                    ), f"{filename}: Stat panel {panel.get('title')} must query current state"

    device_dashboard_path = os.path.join(dashboard_dir, "nexora-network-device.json")
    with open(device_dashboard_path, "r", encoding="utf-8") as f:
        device_dashboard = json.load(f)
    port_status_panel = next(
        panel
        for panel in device_dashboard["panels"]
        if any(
            target.get("expr", "").startswith("ifOperStatus{")
            and "group_left(ifName, ifAlias)" in target.get("expr", "")
            for target in panel.get("targets", [])
        )
    )
    port_status_query = port_status_panel["targets"][0]["expr"]
    organize = next(
        transformation["options"]
        for transformation in port_status_panel.get("transformations", [])
        if transformation.get("id") == "organize"
    )
    assert "group_left(ifName, ifAlias)" in port_status_query
    assert "group_left(ifAlias) (max by (instance, ifIndex, ifAlias) (ifAlias{" in port_status_query
    assert "ifDescr{" not in port_status_query
    assert organize["renameByName"]["ifName"] == "接口全称"
    assert organize["renameByName"]["ifAlias"] == "接口描述"
    assert organize["excludeByName"]["ifDescr"] is True

    overview_path = os.path.join(dashboard_dir, "nexora-network-overview.json")
    with open(overview_path, "r", encoding="utf-8") as f:
        overview_dashboard = json.load(f)
    interface_count_panel = next(panel for panel in overview_dashboard["panels"] if panel["id"] == 6)
    interface_count_query = interface_count_panel["targets"][0]["expr"]
    assert interface_count_panel["title"] == "近24h变动且当前 Down 接口数"
    assert 'ifAdminStatus{' in interface_count_query and "== 1" in interface_count_query
    assert 'ifOperStatus{' in interface_count_query and "== 2" in interface_count_query
    assert "!= 1" not in interface_count_query
    assert "当前 Down" in interface_count_panel["description"]
    assert "24小时内状态有变化" in interface_count_panel["description"]
    interface_candidates_panel = next(panel for panel in overview_dashboard["panels"] if panel["id"] == 14)
    candidate_query = interface_candidates_panel["targets"][0]["expr"]
    assert interface_candidates_panel["title"] == "近24h状态变动且当前仍 Down Top20"
    assert 'ifAdminStatus{' in candidate_query and "== 1" in candidate_query
    assert 'ifOperStatus{' in candidate_query and "== 2" in candidate_query
    assert "长期" in interface_candidates_panel["description"]
    assert "不在此列" in interface_candidates_panel["description"]
    candidate_role_override = next(
        override
        for override in interface_candidates_panel["fieldConfig"]["overrides"]
        if override["matcher"].get("options") == "接口用途"
    )
    assert candidate_role_override["properties"][0]["value"][0]["options"]["unclassified"]["text"] == "用途待确认"
    wireless_client_panel = next(panel for panel in overview_dashboard["panels"] if panel["id"] == 4)
    assert wireless_client_panel["title"] == "控制器汇总在线终端数"
    assert "or vector(0)" not in wireless_client_panel["targets"][0]["expr"]
    assert "description" not in wireless_client_panel

    wireless_path = os.path.join(dashboard_dir, "nexora-network-wireless.json")
    with open(wireless_path, "r", encoding="utf-8") as f:
        wireless_dashboard = json.load(f)
    for panel_id in range(1, 5):
        panel = next(panel for panel in wireless_dashboard["panels"] if panel["id"] == panel_id)
        assert "or vector(0)" not in panel["targets"][0]["expr"]
    bss_panel = next(panel for panel in wireless_dashboard["panels"] if panel["id"] == 12)
    assert 'vendor=~"(?i)(h3c|comware|huawei)"' in bss_panel["targets"][0]["expr"]
    huawei_ssid_panel = next(panel for panel in wireless_dashboard["panels"] if panel["id"] == 13)
    assert 'vendor=~"(?i).*huawei.*"' in huawei_ssid_panel["targets"][0]["expr"]
    ap_wireless_client_panel = next(panel for panel in wireless_dashboard["panels"] if panel["id"] == 10)
    assert 'component_class="wireless_access_point",sensor_class="clients"' in ap_wireless_client_panel["targets"][0]["expr"]
    assert 'vendor=~"$vendor"' in ap_wireless_client_panel["targets"][0]["expr"]
    assert "AP 当前关联客户端" in ap_wireless_client_panel["title"]

    interface_dashboard_path = os.path.join(dashboard_dir, "nexora-network-interface.json")
    with open(interface_dashboard_path, "r", encoding="utf-8") as f:
        interface_dashboard = json.load(f)
    utilization_panel = next(panel for panel in interface_dashboard["panels"] if panel["id"] == 6)
    role_override = next(
        override
        for override in utilization_panel["fieldConfig"]["overrides"]
        if override["matcher"].get("options") == "接口用途"
    )
    assert role_override["properties"][0]["value"][0]["options"]["unclassified"]["text"] == "用途待确认"

    interface_detail_path = os.path.join(dashboard_dir, "nexora-interface-detail.json")
    with open(interface_detail_path, "r", encoding="utf-8") as f:
        interface_detail = json.load(f)
    optical_table = next(panel for panel in interface_detail["panels"] if panel["id"] == 18)
    optical_trend = next(panel for panel in interface_detail["panels"] if panel["id"] == 19)
    assert optical_table["fieldConfig"]["overrides"][0]["properties"][0] == {
        "id": "unit", "value": "dBm"
    }
    assert all("ifName=~\"$interface\"" in target["expr"] for target in optical_table["targets"])
    assert all("job=\"network_snmp\"" in target["expr"] for target in optical_trend["targets"])
    assert all("hwEntityOptical" not in target["expr"] for target in optical_trend["targets"])
    optical_queries = " ".join(target["expr"] for target in optical_table["targets"] + optical_trend["targets"])
    assert "!= 21474836.47" in optical_queries  # H3C invalid power sentinel, converted to dBm.
    assert "!= -100" in optical_queries  # Ruijie invalid power sentinel.
    assert "!= 0" in optical_queries  # Juniper's unsupported zero-power reading.
    assert "hwEntityOptical" not in optical_queries  # Huawei's mixed encoding stays out of exporter dBm panels.
    assert "实测光功率" in optical_table["description"]
    assert "阈值因模块而异" in optical_table["description"]

    for filename in (
        "nexora-network-device.json",
        "nexora-network-interface.json",
        "nexora-interface-detail.json",
        "nexora-network-outbound.json",
    ):
        with open(os.path.join(dashboard_dir, filename), "r", encoding="utf-8") as f:
            dashboard = json.load(f)
        joined_expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
            if "group_left(ifName, ifAlias)" in target.get("expr", "")
        ]
        assert joined_expressions
        assert all("group_left(ifAlias) (max by (instance, ifIndex, ifAlias) (ifAlias{" in expr for expr in joined_expressions)
        assert all("or on(instance, ifIndex) (max by (instance, ifIndex, ifName) (ifName{" in expr for expr in joined_expressions)
        assert all("ifDescr{" not in expr for expr in joined_expressions)
        assert all(
            "ifName=~" not in expr.split("group_left(ifAlias) (max by (instance, ifIndex, ifAlias) (ifAlias{", 1)[1].split("}", 1)[0]
            for expr in joined_expressions
        )

        for panel in dashboard["panels"]:
            if not any("group_left(ifName, ifAlias)" in target.get("expr", "") for target in panel.get("targets", [])):
                continue
            organize = next(
                (
                    transformation["options"]
                    for transformation in panel.get("transformations", [])
                    if transformation.get("id") == "organize"
                ),
                None,
            )
            if organize:
                assert organize["renameByName"].get("ifAlias") == "接口描述"
                assert organize["excludeByName"].get("ifDescr") is True


def test_dashboard_panel_descriptions_are_concise():
    dashboard_dir = os.path.join("monitoring", "grafana", "dashboards")
    for dashboard_path in sorted(
        os.path.join(dashboard_dir, filename)
        for filename in os.listdir(dashboard_dir)
        if filename.endswith(".json")
    ):
        with open(dashboard_path, "r", encoding="utf-8") as dashboard_file:
            dashboard = json.load(dashboard_file)
        for panel in _iter_panels(dashboard.get("panels", [])):
            description = panel.get("description")
            if description:
                assert len(description) <= 60, (
                    f"Panel description exceeds 60 characters in "
                    f"{os.path.basename(dashboard_path)}: {panel.get('title', panel.get('id'))}"
                )


def test_wireless_dashboard_uses_hardware_inventory_job_and_joins_by_device():
    dashboard = build_wireless_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    def query(title):
        return panels[title]["targets"][0]["expr"]

    for title in (
        "AP 当前状态明细",
        "AP 当前关联客户端 Top 20",
        "Radio 利用率 Top 10",
        "AP 无线单元（BSS）客户端 Top 20",
        "华为 SSID 客户端 Top 20",
    ):
        expression = query(title)
        assert 'job="platform_hardware_inventory"' in expression
        assert 'job="network_snmp"' not in expression

    assert 'vendor=~"$vendor"' in query("AP 当前状态明细")
    assert 'component_class="wireless_access_point"' in query("AP 当前状态明细")
    assert 'sensor_class="utilization"' in query("Radio 利用率 Top 10")
    assert 'vendor=~"(?i)(h3c|comware|huawei)"' in query("AP 无线单元（BSS）客户端 Top 20")
    assert 'vendor=~"(?i).*huawei.*"' in query("华为 SSID 客户端 Top 20")

    online_ap_expression = query("在线 AP")
    assert 'job="network_snmp"' in online_ap_expression
    assert 'job="platform_hardware_inventory"' in online_ap_expression
    assert "unless on(site_name,vendor,role,hostname)" in online_ap_expression
    assert "or on(site_name,vendor,role,hostname)" in online_ap_expression

    clients_expression = query("控制器汇总在线终端数")
    assert 'job="network_snmp"' in clients_expression
    assert 'job="platform_hardware_inventory"' in clients_expression
    assert "unless on(site_name,vendor,role,hostname)" in clients_expression


def test_wireless_dashboard_homepage_groups_actual_metrics_by_wireless_layer():
    dashboard = build_wireless_dashboard()
    panels = {panel["id"]: panel for panel in dashboard["panels"]}

    for panel_id in range(1, 7):
        panel = panels[panel_id]
        assert panel["type"] == "stat"
        assert panel["gridPos"]["w"] == 4
        assert panel["gridPos"]["h"] == 3
        expected_no_value = NO_VALUE_TEXT if panel_id == 4 else "—"
        assert panel["fieldConfig"]["defaults"]["noValue"] == expected_no_value

    assert panels[5]["title"] == "高利用率 Radio"
    assert 'sensor_class="utilization"' in panels[5]["targets"][0]["expr"]
    assert ">= 75" in panels[5]["targets"][0]["expr"]
    assert (
        "不代表告警" in panels[5]["description"]
        or "不创建告警" in panels[5]["description"]
        or "用于定位热点" in panels[5]["description"]
    )
    assert 'max by (site_name,vendor,role,hostname,ap_id,ap_name,radio_id)' in panels[5]["targets"][0]["expr"]
    assert 'sensor_class="utilization"' in panels[6]["targets"][0]["expr"]
    assert "avg(" in panels[6]["targets"][0]["expr"]

    trend_targets = panels[7]["targets"]
    assert len(trend_targets) == 2
    assert {target["legendFormat"] for target in trend_targets} == {"在线 AP", "关联终端"}
    assert panels[8]["type"] == "bargauge"
    assert 'count by (state_description)' in panels[8]["targets"][0]["expr"]
    assert "description" not in panels[8]

    assert panels[4]["title"] == "控制器汇总在线终端数"
    assert "description" not in panels[4]

    assert panels[9]["gridPos"]["y"] < panels[11]["gridPos"]["y"] < panels[12]["gridPos"]["y"]
    assert panels[11]["type"] == "bargauge"
    assert panels[11]["targets"][0]["instant"] is True
    assert 'max by (site_name,vendor,role,hostname,ap_id,ap_name,radio_id)' in panels[11]["targets"][0]["expr"]
    assert panels[11]["fieldConfig"]["defaults"]["max"] == 100
    row_titles = {panel["title"] for panel in dashboard["panels"] if panel["type"] == "row"}
    assert row_titles == {"趋势与 AP 状态", "AP 明细", "Radio 热点", "SSID / BSS 客户端明细（依厂商采集覆盖）"}
    assert "无线控制器" not in " ".join(panel["title"] for panel in dashboard["panels"])


def test_wireless_and_interface_dashboards_share_reference_semantic_colors():
    assert (HEALTHY_COLOR, WARNING_COLOR, HIGH_COLOR, CRITICAL_COLOR, INFO_COLOR, NEUTRAL_COLOR) == (
        "#73BF69", "#E0B400", "#FF9830", "#F2495C", "#5794F2", "#8A8F98"
    )
    assert [step["value"] for step in UTILIZATION_THRESHOLDS] == [None, 60, 75, 90]

    wireless = build_wireless_dashboard()
    wireless_panels = {panel["id"]: panel for panel in wireless["panels"]}
    assert wireless["time"] == {"from": "now-15m", "to": "now"}
    assert wireless["refresh"] == "30s"

    assert wireless_panels[1]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == NEUTRAL_COLOR
    assert wireless_panels[2]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == HEALTHY_COLOR
    assert wireless_panels[3]["fieldConfig"]["defaults"]["thresholds"]["steps"] == [
        {"color": HEALTHY_COLOR, "value": None},
        {"color": WARNING_COLOR, "value": 1},
        {"color": CRITICAL_COLOR, "value": 5},
    ]
    trend_colors = {
        override["matcher"]["options"]: override["properties"][0]["value"]["fixedColor"]
        for override in wireless_panels[7]["fieldConfig"]["overrides"]
    }
    assert trend_colors == {"在线 AP": HEALTHY_COLOR, "关联终端": CLIENT_COLOR}

    ap_state_distribution = wireless_panels[8]
    assert ap_state_distribution["fieldConfig"]["defaults"]["color"] == {
        "mode": "fixed",
        "fixedColor": NEUTRAL_COLOR,
    }
    state_color_overrides = {
        override["matcher"]["options"]: {
            prop["id"]: prop["value"]
            for prop in override["properties"]
        }
        for override in ap_state_distribution["fieldConfig"]["overrides"]
    }
    assert state_color_overrides["associated"]["color"]["fixedColor"] == HEALTHY_COLOR
    assert state_color_overrides["idle"]["color"]["fixedColor"] == CRITICAL_COLOR
    assert state_color_overrides["join"]["color"]["fixedColor"] == WARNING_COLOR

    ap_state_table = wireless_panels[9]
    state_mapping = next(
        override for override in ap_state_table["fieldConfig"]["overrides"]
        if override["matcher"] == {"id": "byName", "options": "状态说明"}
        and override["properties"][0]["id"] == "mappings"
    )["properties"][0]["value"]
    state_options = state_mapping[0]["options"]
    assert state_options["associated"] == {"text": "在线", "color": HEALTHY_COLOR}
    assert state_options["idle"] == {"text": "离线", "color": CRITICAL_COLOR}
    assert state_options["join"] == {"text": "接入中", "color": WARNING_COLOR}
    assert any(
        override["matcher"] == {"id": "byName", "options": "状态说明"}
        and override["properties"][0]["value"] == {"type": "color-background"}
        for override in ap_state_table["fieldConfig"]["overrides"]
    )
    organized_fields = ap_state_table["transformations"][0]["options"]["excludeByName"]
    assert organized_fields["Value"] is True

    interface = build_interface_dashboard()
    interface_panels = {panel["id"]: panel for panel in interface["panels"]}
    assert interface_panels[1]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == INBOUND_COLOR
    assert interface_panels[2]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == OUTBOUND_COLOR
    assert interface_panels[3]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == HIGH_COLOR
    assert interface_panels[4]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == CRITICAL_COLOR
    flow_colors = {
        override["matcher"]["options"]: override["properties"][0]["value"]["fixedColor"]
        for override in interface_panels[5]["fieldConfig"]["overrides"]
    }
    assert flow_colors[".*入向$"] == INBOUND_COLOR
    assert flow_colors[".*出向$"] == OUTBOUND_COLOR
    assert interface_panels[17]["fieldConfig"]["defaults"]["color"]["fixedColor"] == INBOUND_COLOR
    assert interface_panels[18]["fieldConfig"]["defaults"]["color"]["fixedColor"] == OUTBOUND_COLOR
    interface_utilization_thresholds = next(
        prop["value"]["steps"]
        for override in interface_panels[6]["fieldConfig"]["overrides"]
        if override["matcher"] == {"id": "byName", "options": "利用率 (%)"}
        for prop in override["properties"]
        if prop["id"] == "thresholds"
    )
    assert interface_utilization_thresholds == UTILIZATION_THRESHOLDS

    detail = build_interface_detail_dashboard()
    detail_panels = {panel["id"]: panel for panel in detail["panels"]}
    assert detail_panels[1]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == INBOUND_COLOR
    assert detail_panels[2]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == OUTBOUND_COLOR
    detail_flow_colors = {
        override["matcher"]["options"]: override["properties"][0]["value"]["fixedColor"]
        for override in detail_panels[7]["fieldConfig"]["overrides"]
    }
    assert detail_flow_colors["入向带宽"] == INBOUND_COLOR
    assert detail_flow_colors["出向带宽"] == OUTBOUND_COLOR

    overview = {panel["id"]: panel for panel in build_overview_dashboard()["panels"]}
    overview_client_expr = overview[4]["targets"][0]["expr"]
    wireless_client_expr = wireless_panels[4]["targets"][0]["expr"]
    assert overview_client_expr == wireless_client_expr
    assert 'component_class="wireless_controller",sensor_class="clients"' in overview_client_expr
    assert 'component_class="wireless_ssid",sensor_class="clients"' in overview_client_expr
    assert "unless on(site_name,vendor,role,hostname)" in overview_client_expr
    assert "or vector(0)" not in overview_client_expr
    assert overview[4]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] == NEUTRAL_COLOR
    assert overview[8]["targets"][0]["expr"] == overview_client_expr


def test_wireless_ap_counts_use_collected_state_rows_and_explicit_statuses():
    dashboard = build_wireless_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    total_panel = panels["采集 AP"]
    total_expression = total_panel["targets"][0]["expr"]
    assert "count by (site_name,vendor,role,hostname)" in total_expression
    assert 'nexora_hw_component_state{' in total_expression
    assert 'component_class="wireless_access_point"' in total_expression
    assert "hwWlanApTotalNum" not in total_expression
    assert any(term in total_panel["description"] for term in ("实际采集", "已采集", "已采到"))
    assert "控制器配置" in total_panel["description"]
    assert "不等" in total_panel["description"]

    online_expression = panels["在线 AP"]["targets"][0]["expr"]
    assert 'state_description=~"^(associated|run)$"' in online_expression
    assert 'coverage_complete="true"' in online_expression
    assert 'sensor_class="ap-count"' in online_expression  # Actual aggregate fallback for platforms without a complete AP detail set.
    assert "unless on(site_name,vendor,role,hostname)" in online_expression

    offline_panel = panels["明确离线 AP"]
    offline_expression = offline_panel["targets"][0]["expr"]
    assert 'state_description=~"^(deassociated|idle)$"' in offline_expression
    assert 'coverage_complete="true"' in offline_expression
    assert "hwWlanApTotalNum" not in offline_expression
    assert any(term in offline_panel["description"] for term in ("不从", "不用"))
    assert "在线数" in offline_panel["description"]
    assert "推算" in offline_panel["description"]


def test_dashboard_device_variables_use_current_up_targets():
    dashboard_dir = os.path.join("monitoring", "grafana", "dashboards")
    network_dashboards = (
        "nexora-network-overview.json",
        "nexora-network-device.json",
        "nexora-network-wireless.json",
        "nexora-network-interface.json",
        "nexora-interface-detail.json",
        "nexora-network-outbound.json",
    )
    network_variable_specs = {
        "site": ("site_name", '/.*site_name="([^\"]+)".*/'),
        "vendor": ("vendor", '/.*vendor="([^\"]+)".*/'),
        "role": ("role", '/.*role="([^\"]+)".*/'),
        "device": ("hostname", '/.*hostname="([^\"]+)".*/'),
    }

    for filename in network_dashboards:
        with open(os.path.join(dashboard_dir, filename), "r", encoding="utf-8") as dashboard_file:
            dashboard = json.load(dashboard_file)
        variables = {variable["name"]: variable for variable in dashboard["templating"]["list"]}
        if filename == "nexora-network-device.json":
            asset_variable = variables["asset_id"]
            asset_query = asset_variable["query"]["query"]
            assert asset_variable["definition"] == asset_query
            assert asset_query.startswith(
                'query_result(label_join(max by (asset_id,hostname,instance,site_name) '
                '(up{job="network_snmp",asset_id!=""'
            )
            assert 'site_name=~"$site"' in asset_query
            assert 'vendor=~"$vendor"' in asset_query
            assert 'role=~"$role"' in asset_query
            assert 'asset_id="(?<value>[^\"]+)"' in asset_variable["regex"]
            assert 'device_label="(?<text>[^\"]+)"' in asset_variable["regex"]
            assert "label_values(" not in asset_query
            assert "== 1" not in asset_query  # Keep configured assets selectable when SNMP is down.
            assert {"site", "vendor", "role"} <= variables.keys()
            assert {
                "cpu_window", "hardware_group", "sensor_name", "component_class",
            } <= variables.keys()
            assert all(
                'asset_id="$asset_id"' in variables[name]["query"]["query"]
                for name in ("cpu_window", "hardware_group", "sensor_name", "component_class")
            )
            continue
        for variable_name, (label, regex) in network_variable_specs.items():
            variable = variables[variable_name]
            query = variable["query"]["query"]
            assert variable["definition"] == query
            assert query.startswith(f"query_result(count by ({label}) (up{{job=\"network_snmp\"")
            assert variable["regex"] == regex
            assert "label_values(" not in query
            assert "== 1" not in query  # Keep configured targets selectable when SNMP is down.

    for filename, job in (
        ("nexora-linux-metrics.json", "linux_servers"),
        ("nexora-windows-metrics.json", "windows_servers"),
    ):
        with open(os.path.join(dashboard_dir, filename), "r", encoding="utf-8") as dashboard_file:
            dashboard = json.load(dashboard_file)
        variables = {variable["name"]: variable for variable in dashboard["templating"]["list"]}
        device_query = variables["device"]["query"]["query"]
        assert device_query.startswith(f"query_result(count by (hostname) (up{{job=\"{job}\"")
        assert variables["device"]["regex"] == '/.*hostname="([^\"]+)".*/'
        assert "label_values(" not in device_query
        assert "== 1" not in device_query
