---
name: "snmp-telemetry"
description: "Builds SNMP polling and telemetry collection pipelines. Invoke when implementing SNMPv2/v3 metrics gathering, OID mapping, and time-series telemetry processing."
---

# SNMP Telemetry Engineer Skill

你负责 Nexora 的 SNMP 遥测采集，核心代码在 `services/snmp_service.py`。

---

## 技术选型

- 使用 **puresnmp**（纯 Python 异步库），不使用 pysnmp/easysnmp。
- 当前支持 **SNMPv2c**（community string 认证）。
- 所有采集操作均为 `async`，通过 `asyncio.gather()` 并发轮询多台设备。

## 多厂商 OID 映射

`snmp_service.py` 内置厂商特定 OID 映射表：

| 指标        | 通用 OID                       | 厂商差异              |
|-------------|--------------------------------|-----------------------|
| sysDescr    | 1.3.6.1.2.1.1.1.0             | 通用                  |
| sysUpTime   | 1.3.6.1.2.1.1.3.0             | 通用                  |
| ifInOctets  | 1.3.6.1.2.1.2.2.1.10          | 通用                  |
| ifOutOctets | 1.3.6.1.2.1.2.2.1.16          | 通用                  |
| CPU         | 厂商特定                       | Cisco/Huawei/H3C 不同 |
| Memory      | 厂商特定                       | Cisco/Huawei/H3C 不同 |
| Temperature | 厂商特定                       | entPhysicalSensorValue |

## 采集流程

```python
async def poll_device(host, community, vendor):
    # 1. get sysDescr → 自动识别厂商
    # 2. 选择对应 OID 表
    # 3. 并发 GET/WALK 多个 OID
    # 4. 返回结构化指标 dict
```

## 指标返回格式

```json
{
    "device_id": 1,
    "hostname": "core-sw-01",
    "metrics": {
        "cpu_usage": 45.2,
        "memory_usage": 62.1,
        "temperature": 38,
        "uptime_seconds": 8640000,
        "interfaces": {
            "Gi0/1": {"in_octets": 123456, "out_octets": 789012, "status": "up"}
        }
    },
    "collected_at": "2025-01-01T00:00:00Z"
}
```

## 扩展指南

- **新增厂商**：在 OID 映射表中添加厂商条目，key 为 `device_type` 字段值（如 `cisco_ios`、`huawei_vrp`）。
- **新增指标**：添加 OID 到映射表，在 `poll_device()` 中增加对应的 GET/WALK 调用。
- **SNMPv3 支持**：需扩展 puresnmp 的 `V3Config`，增加 auth/priv 参数。
- **采集频率**：前端可配置（默认 5 分钟），由定时任务调度轮询。
