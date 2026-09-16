"""Official SNMP preset catalog sourced from the user's vendor OID document.

This module deliberately keeps the document's OID boundary intact.  A numeric
OID is only turned into a health metric when the document gives enough context
to identify the metric.  OIDs whose article section does not provide a stable
name/meaning remain in ``source_oids`` so they are visible and auditable without
being assigned a guessed meaning.
"""

from copy import deepcopy
from typing import Any


_IF_MIB = {
    "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
    "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
    "if_admin_status_oid": "1.3.6.1.2.1.2.2.1.7",
    "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
    "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
    "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
    "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
    "sys_uptime_oid": "1.3.6.1.2.1.1.3.0",
    "if_mtu_oid": "1.3.6.1.2.1.2.2.1.4",
    "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
    "if_phys_address_oid": "1.3.6.1.2.1.2.2.1.6",
    "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
    "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
    "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
    "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
    "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
    "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
    "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
    "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
    "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
    "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
    "if_hc_in_ucast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.7",
    "if_hc_in_multicast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.8",
    "if_hc_in_broadcast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.9",
    "if_hc_out_ucast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.11",
    "if_hc_out_multicast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.12",
    "if_hc_out_broadcast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.13",
    "dot3_hc_fcs_errors_oid": "1.3.6.1.2.1.10.7.11.1.2",
    "dot3_hc_frame_too_long_oid": "1.3.6.1.2.1.10.7.11.1.4",
    "dot3_hc_internal_mac_rx_errors_oid": "1.3.6.1.2.1.10.7.11.1.5",
    "dot3_hc_symbol_errors_oid": "1.3.6.1.2.1.10.7.11.1.6",
    "dot3_fcs_errors_oid": "1.3.6.1.2.1.10.7.2.1.3",
    "counter_mode": "auto",
    "enabled": True,
}


def _iface() -> dict[str, Any]:
    return deepcopy(_IF_MIB)


def _direct(
    oid: str,
    *,
    aggregation: str = "first",
    unit: str = "",
    description: str | None = None,
) -> dict[str, Any]:
    definition: dict[str, Any] = {
        "mode": "direct_value",
        "oid": oid,
        "aggregation": aggregation,
        "scale": 1,
        "offset": 0,
        "unit": unit,
    }
    if description:
        definition["description"] = description
    return definition


def _percent(oid: str, *, description: str | None = None) -> dict[str, Any]:
    definition = _direct(oid, aggregation="first", unit="%", description=description)
    definition["mode"] = "direct_percent"
    return definition


def _status(
    oid: str,
    *,
    ok: list[int],
    warning: list[int] | None = None,
    fail: list[int] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    definition = _direct(oid, description=description)
    definition["mode"] = "status_code"
    definition["status_ok_values"] = ok
    definition["status_warning_values"] = warning or []
    definition["status_fail_values"] = fail or []
    return definition


H3C_SYSTEM_OIDS = [
    "1.3.6.1.2.1.1.5",
    "1.3.6.1.2.1.1.3",
    "1.3.6.1.2.1.47.1.1.1.1.7",
    "1.3.6.1.2.1.47.1.1.1.1.10",
    "1.3.6.1.2.1.47.1.1.1.1.11",
    "1.3.6.1.4.1.25506.2.6.1.1.1.1.19",
    "1.3.6.1.4.1.25506.2.6.1.1.1.1.11",
    "1.3.6.1.4.1.25506.2.6.1.1.1.1.12",
    "1.3.6.1.4.1.25506.2.6.1.1.1.1.6",
    "1.3.6.1.4.1.25506.2.6.1.1.1.1.8",
    "1.3.6.1.4.1.25506.8.35.9.1.1.1.2",
    "1.3.6.1.4.1.25506.8.35.9.1.2.1.2",
    "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.8",
    "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.4",
    "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.5",
    "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.10",
    "1.3.6.1.4.1.25506.8.35.5.1.12",
    "1.3.6.1.4.1.25506.2.6.1.2.1.1.5",
]

H3C_INTERFACE_OIDS = list(_IF_MIB.values())[:-2]


HUAWEI_SYSTEM_OIDS = [
    "1.3.6.1.2.1.1.5",
    "1.3.6.1.2.1.1.3",
    "1.3.6.1.2.1.47.1.1.1.1.10",
    "1.3.6.1.2.1.47.1.1.1.1.11",
    "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.2",
    "1.3.6.1.2.1.47.1.1.1.1.7",
    "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5",
    "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7",
    "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11",
    "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.3",
    "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.5",
    "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.6",
    "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7",
    "1.3.6.1.4.1.2011.6.9.1.4.2.1.2",
    "1.3.6.1.4.1.2011.6.9.1.4.2.1.3",
    "1.3.6.1.4.1.2011.6.9.1.4.2.1.4",
    "1.3.6.1.4.1.2011.6.9.1.4.2.1.5",
    "1.3.6.1.4.1.2011.5.25.42.2.1.1",
    "1.3.6.1.4.1.2011.5.25.42.2.1.14",
]


ZTE_SYSTEM_OIDS = [
    "1.3.6.1.2.1.1.5",
    "1.3.6.1.2.1.1.3",
    "1.3.6.1.4.1.3902.3.600.3.2",
    "1.3.6.1.4.1.3902.3.600.3.7",
    "1.3.6.1.4.1.3902.3.600.2.1.1.3.0.0.1.0",
    "1.3.6.1.4.1.3902.3.600.2.1.1.4.0.0.1.0",
    "1.3.6.1.4.1.3902.3.600.2.1.1.5.0.0.1.0",
    "1.3.6.1.4.1.3902.3.600.2.1.1.6.0.0.1.0",
    "1.3.6.1.4.1.3902.3.600.2.1.1.7.0.0.1.0",
    "1.3.6.1.4.1.3902.3.600.2.2.1.2",
    "1.3.6.1.4.1.3902.3.600.2.2.1.9",
    "1.3.6.1.4.1.3902.3.600.2.3.1.2",
    "1.3.6.1.4.1.3902.3.600.2.3.1.4",
    "1.3.6.1.4.1.3902.3.600.2.3.1.6",
    "1.3.6.1.4.1.3902.3.600.2.4.1.3",
    "1.3.6.1.4.1.3902.3.600.2.4.1.5",
    "1.3.6.1.4.1.3902.3.600.2.4.1.7",
]

ZTE_OPTICAL_OIDS = [
    "1.3.6.1.4.1.3902.3.103.11.1.1.2",
    "1.3.6.1.4.1.3902.3.103.11.1.1.3",
    "1.3.6.1.4.1.3902.3.103.11.1.1.4",
    "1.3.6.1.4.1.3902.3.103.11.1.1.16",
    "1.3.6.1.4.1.3902.3.103.11.1.1.18",
    "1.3.6.1.4.1.3902.3.103.11.1.1.20",
    "1.3.6.1.4.1.3902.3.103.11.1.1.24",
]


CISCO_SOURCE_OIDS = {
    "system": [
        "SNMP-FRAMEWORK-MIB::snmpEngineTime.0",
        "SNMPv2-MIB::sysName.0",
        "CISCO-PROCESS-MIB::cpmCPUTotal5sec",
        "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolName",
        "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolUsed",
        "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolFree",
        "CISCO-ENVMON-MIB::ciscoEnvMonTemperatureStatusDescr",
        "CISCO-ENVMON-MIB::ciscoEnvMonTemperatureStatusValue",
        "CISCO-ENVMON-MIB::ciscoEnvMonFanStatusDescr",
        "CISCO-ENVMON-MIB::ciscoEnvMonFanState",
        "CISCO-ENVMON-MIB::ciscoEnvMonSupplyStatusDescr",
        "CISCO-ENVMON-MIB::ciscoEnvMonSupplyState",
    ],
    "interface": [
        "IF-MIB::ifName",
        "IF-MIB::ifAdminStatus",
        "IF-MIB::ifOperStatus",
        "IF-MIB::ifHighSpeed",
        "IF-MIB::ifMtu",
        "IF-MIB::ifAlias",
        "IF-MIB::ifPhysAddress",
        "IF-MIB::ifHCInOctets",
        "IF-MIB::ifHCOutOctets",
        "IF-MIB::ifInDiscards",
        "IF-MIB::ifInErrors",
        "IF-MIB::ifOutDiscards",
        "IF-MIB::ifOutErrors",
        "IF-MIB::ifHCInUcastPkts",
        "IF-MIB::ifHCInMulticastPkts",
        "IF-MIB::ifHCInBroadcastPkts",
        "IF-MIB::ifHCOutUcastPkts",
        "IF-MIB::ifHCOutMulticastPkts",
        "IF-MIB::ifHCOutBroadcastPkts",
    ],
}


_BASE_MD_OFFICIAL_MODEL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "md-h3c-comware-v7",
        "vendor": "H3C",
        "model": "Comware V7 (S5000-S10500)",
        "category": "Campus Switch",
        "description": (
            "以 MD 中 h3ccs_system/h3ccs_interface 为准，覆盖 "
            "S5000、S5110、S5120、S5130、S5135、S5170、S5500、S5800、S6300、"
            "S6500、S6800、S10500 的 Comware V7 范围；MD 未提供 V5 专用 OID，"
            "因此不扩展 V5 模板，也不臆造光模块 OID。"
        ),
        "metric_definitions": {
            "cpu": _percent(
                "1.3.6.1.4.1.25506.2.6.1.1.1.1.6",
                description="h3cEntityExtCpuUsage（MD h3ccs_system）",
            ),
            "memory": _percent(
                "1.3.6.1.4.1.25506.2.6.1.1.1.1.8",
                description="h3cEntityExtMemUsage（MD h3ccs_system）",
            ),
            "temperature": _direct(
                "1.3.6.1.4.1.25506.2.6.1.1.1.1.12",
                aggregation="max",
                unit="°C",
                description="h3cEntityExtTemperature（MD h3ccs_system）",
            ),
            "uptime": _direct(
                "1.3.6.1.4.1.25506.2.6.1.1.1.1.11",
                unit="s",
                description="h3cEntityExtUptime（MD h3ccs_system）",
            ),
            "fan": _status(
                "1.3.6.1.4.1.25506.2.6.1.1.1.1.19",
                ok=[2],
                fail=[3, 4, 41],
                description="h3cEntityExtErrorStatus；按实体索引区分风扇实体",
            ),
            "power_supply": _status(
                "1.3.6.1.4.1.25506.2.6.1.1.1.1.19",
                ok=[2],
                fail=[3, 4, 51],
                description="h3cEntityExtErrorStatus；按实体索引区分电源实体",
            ),
        },
        "interface_config": _iface(),
        "source_oids": {
            "system": H3C_SYSTEM_OIDS,
            "interface": H3C_INTERFACE_OIDS,
        },
    },
    {
        "id": "md-huawei-vrp-switch",
        "vendor": "Huawei",
        "model": "VRP (S3700-S16700)",
        "category": "Campus Switch",
        "description": (
            "以 MD 中 hcs_system 及统一 IF-MIB 说明为准，覆盖 "
            "S3700、S5700、S6700、S7700、S8700、S9700、S12700、S16700；"
            "MD 未给出华为光模块模块的完整 OID 定义，模板不额外推断。"
        ),
        "metric_definitions": {
            "cpu": _percent(
                "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5",
                description="hwEntityCpuUsage（MD hcs_system）",
            ),
            "memory": _percent(
                "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7",
                description="hwEntityMemUsage（MD hcs_system）",
            ),
            "temperature": _direct(
                "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11",
                aggregation="max",
                unit="°C",
                description="hwEntityTemperature（MD hcs_system）",
            ),
            "uptime": _direct(
                "1.3.6.1.2.1.1.3",
                unit="s",
                description="SNMPv2-MIB::sysUpTime（MD hcs_system）",
            ),
            "fan": _status(
                "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7",
                ok=[1],
                fail=[2],
                description="hwEntityFanState（MD hcs_system）",
            ),
        },
        "interface_config": _iface(),
        "source_oids": {
            "system": HUAWEI_SYSTEM_OIDS,
            "interface": H3C_INTERFACE_OIDS,
        },
    },
    {
        "id": "md-zte-zxr10-switch",
        "vendor": "ZTE",
        "model": "ZXR10 Switch",
        "category": "Campus Switch",
        "description": (
            "以 MD 中 zte_system、zte_interface、zte_optical 的 OID 清单为准。"
            "MD 对 zte_system 数值节点没有逐项给出稳定的指标名称，"
            "因此保留为原始 OID 清单，不把节点猜测为 CPU、内存或温度；"
            "光模块 DisplayString 节点也不强行转换为数值健康指标。"
        ),
        "metric_definitions": {
            "uptime": _direct(
                "1.3.6.1.2.1.1.3",
                unit="s",
                description="SNMPv2-MIB::sysUpTime（MD zte_system）",
            ),
        },
        "interface_config": _iface(),
        "source_oids": {
            "system": ZTE_SYSTEM_OIDS,
            "interface": H3C_INTERFACE_OIDS,
            "optical": ZTE_OPTICAL_OIDS,
            "optical_index_lookup": [
                "zxr10OpticalIfIndex -> zxr10OpticalIfName",
            ],
        },
    },
    {
        "id": "md-cisco-catalyst-categraf",
        "vendor": "Cisco",
        "model": "Catalyst (Categraf)",
        "category": "Campus Switch",
        "description": (
            "以 MD 最后给出的 Cisco Catalyst Categraf 配置为准。"
            "Cisco 配置中的 MIB 节点已按当前导入 MIB 解析为数值 OID；"
            "内存按 Processor pool 的 used/free 计算，池名称过滤仍需采集侧支持。"
        ),
        "metric_definitions": {
            "cpu": _percent(
                "1.3.6.1.4.1.9.9.109.1.1.1.1.3",
                description="CISCO-PROCESS-MIB::cpmCPUTotal5sec",
            ),
            "memory": {
                "mode": "used_free_percent",
                "used_oid": "1.3.6.1.4.1.9.9.48.1.1.1.5",
                "free_oid": "1.3.6.1.4.1.9.9.48.1.1.1.6",
                "aggregation": "first",
                "scale": 1,
                "offset": 0,
                "unit": "%",
                "pool_name_oid": "1.3.6.1.4.1.9.9.48.1.1.1.2",
                "pool_name_filter": "Processor",
                "description": (
                    "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolUsed/Free；"
                    "MD 要求 Processor pool"
                ),
            },
            "uptime": _direct(
                "1.3.6.1.6.3.10.2.1.3.0",
                unit="s",
                description="SNMP-FRAMEWORK-MIB::snmpEngineTime.0",
            ),
            "temperature": _direct(
                "1.3.6.1.4.1.9.9.13.1.3.1.3",
                aggregation="max",
                unit="°C",
                description="CISCO-ENVMON-MIB::ciscoEnvMonTemperatureStatusValue",
            ),
            "fan": _status(
                "1.3.6.1.4.1.9.9.13.1.4.1.3",
                ok=[1],
                fail=[2, 3, 4, 5],
                description="CISCO-ENVMON-MIB::ciscoEnvMonFanState",
            ),
            "power_supply": _status(
                "1.3.6.1.4.1.9.9.13.1.5.1.3",
                ok=[1],
                fail=[2, 3, 4, 5],
                description="CISCO-ENVMON-MIB::ciscoEnvMonSupplyState",
            ),
        },
        "interface_config": _iface(),
        "source_oids": CISCO_SOURCE_OIDS,
    },
]


_H3C_MODEL_SCOPE = (
    "S5000",
    "S5110",
    "S5120",
    "S5130",
    "S5135",
    "S5170",
    "S5500",
    "S5800",
    "S6300",
    "S6500",
    "S6800",
    "S10500",
)

_HUAWEI_MODEL_SCOPE = (
    "S3700",
    "S5700",
    "S6700",
    "S7700",
    "S8700",
    "S9700",
    "S12700",
    "S16700",
)


def _model_preset(
    base: dict[str, Any],
    *,
    preset_id: str,
    family_id: str,
    model: str,
    verification_level: str,
    support_status: str,
    firmware_scope: str = "",
    testable: bool = True,
    description_suffix: str = "",
    source_oids: dict[str, list[str]] | None = None,
    interface_config: dict[str, Any] | None = None,
    metric_definitions: dict[str, Any] | None = None,
    source_modules: list[str] | None = None,
) -> dict[str, Any]:
    """Create one visible model row without changing the MD-backed OIDs."""

    item = deepcopy(base)
    item["id"] = preset_id
    item["family_id"] = family_id
    item["model"] = model
    item["verification_level"] = verification_level
    item["support_status"] = support_status
    item["firmware_scope"] = firmware_scope
    item["testable"] = testable
    if description_suffix:
        item["description"] = f'{item["description"]} {description_suffix}'
    if source_oids is not None:
        item["source_oids"] = deepcopy(source_oids)
    if interface_config is not None:
        item["interface_config"] = deepcopy(interface_config)
    if metric_definitions is not None:
        item["metric_definitions"] = deepcopy(metric_definitions)
    if source_modules is not None:
        item["source_modules"] = list(source_modules)
    return item


def _build_expanded_md_official_model_presets() -> list[dict[str, Any]]:
    """Expand the MD's series scope into explicit, searchable model rows.

    The MD gives usable numeric definitions for the H3C/Huawei series and for
    Cisco Catalyst, but it does not give a model-specific numeric OID set for
    H3C S10500 V5.  The V5 row remains visible as a non-testable
    documentation row instead of silently reusing a different firmware's
    OIDs.
    """

    bases = {item["id"]: item for item in _BASE_MD_OFFICIAL_MODEL_PRESETS}
    h3c_base = bases["md-h3c-comware-v7"]
    huawei_base = bases["md-huawei-vrp-switch"]
    zte_base = bases["md-zte-zxr10-switch"]
    cisco_base = bases["md-cisco-catalyst-categraf"]
    expanded: list[dict[str, Any]] = []

    for model in _H3C_MODEL_SCOPE:
        expanded.append(
            _model_preset(
                h3c_base,
                preset_id=f"md-h3c-{model.lower()}-v7",
                family_id=h3c_base["id"],
                model=model,
                verification_level="md_scope",
                support_status="documented_scope",
                firmware_scope="Comware V7",
                description_suffix="MD 明确列出的 Comware V7 适配型号。",
            )
        )

    # MD explicitly warns that S10500 V5 uses a different module/OID scope;
    # keep it discoverable, but do not offer the V7 definitions as a testable
    # V5 template.
    expanded.append(
        _model_preset(
            h3c_base,
            preset_id="md-h3c-s10500-v5",
            family_id=h3c_base["id"],
            model="S10500 (V5)",
            verification_level="needs_walk",
            support_status="firmware_specific_pending",
            firmware_scope="Comware V5",
            testable=False,
            description_suffix="MD 明确说明 V5 与 V7 模块不同；正文未提供 V5 专用 OID，需导入对应 MIB/Walk 后再启用。",
            source_oids={"interface": H3C_INTERFACE_OIDS},
            metric_definitions={},
            interface_config={**_iface(), "enabled": False},
        )
    )

    tested_huawei = {"S5700", "S6700", "S12700"}
    for model in _HUAWEI_MODEL_SCOPE:
        is_tested = model in tested_huawei
        expanded.append(
            _model_preset(
                huawei_base,
                preset_id=f"md-huawei-{model.lower()}-vrp",
                family_id=huawei_base["id"],
                model=model,
                verification_level="md_tested" if is_tested else "md_scope",
                support_status="tested_in_md" if is_tested else "documented_scope",
                firmware_scope="VRP",
                description_suffix=(
                    "MD 文档列为实测系列。"
                    if is_tested
                    else "MD 文档列出的模块覆盖范围，未在正文中标注为实测型号。"
                ),
            )
        )

    expanded.append(
        _model_preset(
            zte_base,
            preset_id=zte_base["id"],
            family_id=zte_base["id"],
            model="ZXR10 系列（MD 未指定具体型号）",
            verification_level="needs_walk",
            support_status="series_unspecified",
            firmware_scope="",
            description_suffix="MD 只给出 ZXR10 系列 OID 清单，未指定可逐项展示的具体型号；数值含义需以设备 Walk/MIB 核对。",
        )
    )

    expanded.append(
        _model_preset(
            cisco_base,
            preset_id=cisco_base["id"],
            family_id=cisco_base["id"],
            model="Catalyst 园区系列（Categraf）",
            verification_level="md_config",
            support_status="documented_config",
            description_suffix="MD 给出 Categraf 配置示例；正文未列出 Catalyst 的逐型号清单，实际型号仍建议一键测试。",
        )
    )

    return expanded


MD_OFFICIAL_MODEL_PRESETS: list[dict[str, Any]] = _build_expanded_md_official_model_presets()


def get_md_official_model_presets() -> list[dict[str, Any]]:
    """Return a defensive copy so callers cannot mutate the source catalog."""

    return deepcopy(MD_OFFICIAL_MODEL_PRESETS)
