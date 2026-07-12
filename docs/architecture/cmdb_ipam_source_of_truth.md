# CMDB / IPAM / Discovery 三层事实源定义

## 目标

明确平台内三类数据的权威边界，避免自动发现数据直接覆盖人工确认的 CMDB/IPAM 数据。

## 三层事实源

| 层级 | 范围 | 是否权威 | 写入原则 |
|---|---|---|---|
| CMDB | 资产、站点、机柜、设备、接口、租户、VRF、VLAN | 是 | 人工维护、审批导入、对账确认后写入 |
| IPAM | prefix、address、pool、VIP、DHCP lease、地址生命周期 | 是 | 通过 IPAM 服务/API 写入，必须做冲突和并发检查 |
| Discovery | ARP、MAC、LLDP/CDP、路由表、SNMP 采样、在线终端、临时观测 | 否 | 只能作为观测证据，进入 CMDB/IPAM 前必须经过 reconciliation |

## 核心原则

1. Discovery 不直接覆盖 CMDB/IPAM。
2. 自动发现的数据必须带来源：
   - `source_type`
   - `source_ref`
   - `confidence`
   - `last_observed_at`
3. 人工确认或审批导入的数据应带确认信息：
   - `last_confirmed_at`
   - `confirmed_by`
4. 当 Discovery 与 CMDB/IPAM 冲突时，生成 reconciliation decision，而不是直接写入。

## 可信等级

| 等级 | 含义 | 示例 |
|---|---|---|
| `manual` | 人工创建或维护 | 手工创建站点、VRF |
| `imported` | 批量导入但未逐条确认 | Excel 导入资产 |
| `discovered` | 自动发现观测 | LLDP 邻居、ARP 记录 |
| `confirmed` | 已确认事实 | 确认后的接口/IP 绑定 |
| `stale` | 过期观测 | 超过保留周期未再次发现 |

## 字段权威答案

| 数据 | 权威来源 |
|---|---|
| IP 地址是否分配 | IPAM `ip_addresses` |
| IP 所属 prefix/VRF/site/tenant | IPAM `prefixes` + `ip_addresses` |
| MAC 当前观测位置 | Discovery `network_endpoints` / ARP/MAC 观测 |
| 设备 hostname | CMDB `devices` |
| 设备 site | CMDB `devices.site_id` |
| VLAN 定义 | CMDB `vlans` |
| 接口身份 | CMDB `interfaces.id` |
| 拓扑链路确认关系 | CMDB/Topology `topology_links.*_interface_id` |

## API 设计引用规则

1. 写 CMDB/IPAM 的 API 必须调用服务层校验，不允许绕过服务层直接写库。
2. Discovery 导入只能写观测表或 reconciliation 队列。
3. 批量任务若要改变 CMDB/IPAM，必须产出可审计的变更结果。
