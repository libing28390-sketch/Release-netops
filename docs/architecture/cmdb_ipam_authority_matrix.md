# CMDB/IPAM 字段权威矩阵

## 权威源定义

| 权威源 | 含义 | 示例 |
|---|---|---|
| CMDB Manual | 人工确认或流程审批后的权威数据 | 站点、租户、设备生命周期、机柜位置 |
| IPAM Manual | 地址规划和分配权威 | prefix、IP 分配、地址状态 |
| Device Runtime | 从设备实时采集或连接配置得到的数据 | 接口 oper status、SNMP 指标、配置备份 |
| Discovery Observation | 网络观测结果，不直接作为权威写入 | ARP、MAC、LLDP/CDP、在线终端 |
| Derived/System | 系统计算或同步结果 | prefix utilization、topology confidence、health status |
| Secret Vault | 凭据和密钥权威 | SSH 密码、SNMP community、enable password |

## 核心字段权威矩阵

| 数据项 | 当前出现位置 | 当前权威判断 | 目标权威源 | 后续动作 |
|---|---|---|---|---|
| 设备 hostname | `devices.hostname`、`physical_assets.hostname`、`ip_addresses.hostname`、`network_endpoints.hostname` | 多处重复 | `devices.hostname` 为可管理设备权威；endpoint hostname 为观测 | 明确同步方向，endpoint 不直接覆盖 device |
| 管理 IP | `devices.ip_address`、`physical_assets.management_ip` | 两处重复 | `devices.ip_address` 为连接目标；`physical_assets.management_ip` 为资产录入来源 | 资产变更同步设备，但设备连接以 `devices` 为准 |
| 业务 IP | `physical_assets.business_ip`、`ip_addresses.address` | 分离 | IPAM 权威 | 业务 IP 应登记到 `ip_addresses`，资产只展示引用 |
| 设备平台 | `devices.platform`、`physical_assets.platform`、发现/导入逻辑 | 多处重复 | `devices.platform` | 资产平台字段作为录入候选或展示缓存 |
| 设备型号 | `devices.model`、`physical_assets.model`、`device_types.model` | 多处重复 | `physical_assets.model` + `device_types` | 设备运行态可显示，但资产规格为权威 |
| 序列号 | `devices.sn`、`physical_assets.serial_number` | 两处重复 | `physical_assets.serial_number` | 采集值作为校验，确认后写资产 |
| 生命周期 | `devices.lifecycle_status`、`physical_assets.lifecycle_status` | 两处重复 | CMDB Manual | 需要明确 asset lifecycle 与 managed device lifecycle 的映射 |
| 站点 | `sites.id`、`devices.site`、`prefixes.site_id`、`network_endpoints.site` | 混合 | `sites.id` | `devices.site` 应迁移为 `site_id` 或映射字段 |
| 机柜位置 | `physical_assets.rack/rack_unit/planned_start_u`、`racks`、`rack_devices` | 基本清楚 | CMDB Manual | 继续以 rack/rack_devices 为上架权威 |
| 接口名称 | `interfaces.interface_name`、`ip_addresses.interface_name`、`arp_table.interface_name`、`mac_table.interface_name` | 多处字符串 | `interfaces.id` + `interfaces.interface_name` | IP/ARP/MAC/Telemetry 逐步绑定 `interface_id` |
| 接口 MAC | `interfaces.mac_address`、`ip_addresses.mac_address`、`network_endpoints.mac`、`mac_table.mac_address` | 多处重复 | `interfaces.mac_address` 对本机接口；endpoint/mac_table 为观测 | 区分设备接口 MAC 和终端 MAC |
| 接口状态 | `interfaces.admin_status/oper_status`、telemetry、SNMP 采集 | 运行态 | Device Runtime | 不作为人工 CMDB 字段，保留最后观测 |
| VLAN | `vlans.vlan_id`、`interfaces.access_vlan/native_vlan/allowed_vlans`、`physical_assets.vlan`、`network_endpoints.vlan` | 多处重复 | `vlans` + interface VLAN membership | 资产 VLAN 为录入辅助；endpoint VLAN 为观测 |
| VRF | `vrfs.id`、`interfaces.vrf_id`、`prefixes.vrf_id`、`ip_addresses.vrf_id`、`network_endpoints.vrf` | 部分结构化 | `vrfs.id` | endpoint VRF 需通过对账映射为 `vrf_id` |
| Prefix | `prefixes.prefix` | IPAM 权威 | IPAM Manual | 后续迁移到 PostgreSQL `cidr` |
| IP 地址 | `ip_addresses.address`、`network_endpoints.ip`、`arp_table.ip_address`、`devices.ip_address` | 多处重复 | `ip_addresses.address` 为地址分配权威；Discovery 为观测 | 管理 IP 也应可回写/关联到 IPAM |
| IP 状态 | `ip_addresses.status`、DHCP lease、endpoint active | 不完整 | IPAM Manual + Discovery evidence | 增加生命周期状态和 quarantine/released 语义 |
| DHCP 租约 | `ipam_dhcp_leases` | 动态租约 | Discovery/External DHCP | 与静态 IPAM 做冲突检测 |
| VIP | `ipam_vips` | 独立 VIP 表 | IPAM Manual | 纳入统一地址冲突检测 |
| 拓扑链路 | `topology_links` | 发现/推断链路 | Discovery Observation，确认后可提升为 CMDB link | 增加确认状态和 evidence |
| 终端在线状态 | `network_endpoints.is_active` | 观测数据 | Discovery Observation | 不能直接删除或覆盖 IPAM |
| 凭据 | `credentials`、`devices`、`physical_assets` | 多处相关 | Secret Vault / credential center | 设备和资产只引用 credential，不应散落明文 |
| 审计 | `audit_events` 及各模块 log_audit_event | 分散使用 | Derived/System | 统一 before/after/details 标准 |

## 当前一致项

1. `interfaces` 已有 `device_id` 外键和设备内唯一接口名，适合作为网络 CMDB 子资源。
2. `topology_links` 已经支持接口级链路关系。
3. `prefixes` 已经关联 VRF、VLAN、site、tenant。
4. `ip_addresses` 已经预留 `interface_id`，说明系统已经有向接口绑定收敛的方向。
5. `network_endpoints` 与 `get_ipam_reconciliation()` 已经形成基础对账能力。

## 当前不一致项

1. CMDB 页面和 `/api/cmdb/*` 尚未把 `devices`、`interfaces` 纳入 CMDB 主资源。
2. `ip_addresses.interface_name` 仍是主要绑定字段，`interface_id` 未成为强约束。
3. `devices.site` 仍是文本，和 `sites.id` 没有强关系。
4. `physical_assets` 和 `devices` 有多处字段重复，权威边界需要收敛。
5. Discovery 数据缺少持久化 finding/action 状态，无法形成完整审批闭环。
6. IP/prefix 字段仍是文本，数据库层无法充分表达 `inet/cidr` 约束。

## 建议的权威写入规则

### 人工录入

- 写入 CMDB/IPAM 权威表。
- 必须记录审计。
- 高风险动作需要管理员或变更流程。

### 设备采集

- 写入运行态、观测表或 last observed 字段。
- 不直接覆盖人工确认字段。
- 可以生成 reconciliation finding。

### 批量导入

- 先进入 staging 或 validation 结果。
- 通过校验后写入权威表。
- 冲突数据必须给出逐条原因。

### Discovery 对账

- Discovery 只产生 finding。
- 用户确认后 action 才能写入 CMDB/IPAM。
- action 必须包含 source evidence 和 audit event。

## 建议的下一步任务

| 编号 | 任务 | 目标 |
|---|---|---|
| `CMDB-000` | 确立 device + interface 为 CMDB 主骨架 | 将设备/接口纳入 CMDB 主视图和聚合 API |
| `CMDB-002` | 资产、设备、接口关系重构 | 收敛重复字段和一对一关系 |
| `IPAM-003` | 原子 IP 分配 | 解决并发分配风险 |
| `IPAM-001` | PostgreSQL 原生 IPAM | 引入 `cidr/inet` 或规范化字段 |
| `REC-002` | 对账中心闭环 | finding/action/audit 状态机 |

