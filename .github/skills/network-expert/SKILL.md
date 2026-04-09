---
name: "network-expert"
description: "Implements multi-vendor network automation and full-stack Nexora features. Invoke when building device workflows, telemetry, compliance, or network operations logic."
---

# Network Expert Skill

你是 Nexora 的全栈网络运维专家。当任务跨越前后端或涉及多个子系统时调用此 skill。

如果任务明确只涉及单个领域，优先使用更专业的 skill：
- 纯后端 API/架构 → `backend-architect`
- 驱动/作业/设备连接 → `automation-engineer`
- 凭据/权限/安全合规 → `network-security`
- 拓扑发现/可视化 → `topology-engineer`
- SNMP 采集 → `snmp-telemetry`
- CLI 解析 → `textfsm-parser`
- 监控/告警/日志 → `observability-engineer`

---

## 何时使用此 Skill

1. **端到端功能开发**：需要同时修改后端 API + Service + 前端页面。
2. **跨子系统问题排查**：故障涉及驱动层 → 服务层 → API → 前端多环节。
3. **网络协议知识**：需要 BGP/OSPF/STP/VLAN/VXLAN 等专业知识辅助决策。
4. **新功能架构设计**：需要评估在哪一层实现、如何拆分前后端职责。

## 全栈功能开发流程

以"新增设备接口流量图表"为例：

```
1. 后端
   ├── schemas/schemas.py       → 定义 InterfaceTrafficResponse
   ├── services/snmp_service.py  → 添加 get_interface_traffic()
   └── api/monitoring.py         → 添加 GET /api/monitoring/interface-traffic/{device_id}

2. 前端
   ├── src/types.ts              → 添加 InterfaceTraffic 类型
   └── src/components/           → 创建 InterfaceTrafficChart.tsx (Recharts)
```

## 网络协议速查

### 路由协议
- **BGP**：AS 间路由，`show bgp summary` / `display bgp peer`
- **OSPF**：区域内路由，`show ip ospf neighbor` / `display ospf peer`
- **ISIS**：大规模 IGP，常用于 DC 和运营商

### 二层协议
- **VLAN**：802.1Q 标记，`show vlan brief` / `display vlan`
- **STP**：环路防护，合规规则 L2-001 检查
- **LACP**：链路聚合

### 网络服务
- **SNMP**：遥测采集（见 `snmp-telemetry` skill），SNMP-001 合规检查
- **NTP**：时间同步，TIME-001 合规检查
- **Syslog**：日志收集，LOG-001 合规检查
- **AAA**：认证授权审计，AAA-001 合规检查

## 多厂商命令映射

| 功能         | Cisco IOS            | Huawei VRP            | H3C Comware            |
|-------------|----------------------|-----------------------|------------------------|
| 运行配置     | show running-config  | display current-config | display current-config |
| 接口状态     | show ip int brief    | display int brief     | display int brief      |
| 路由表       | show ip route        | display ip routing    | display ip routing     |
| VLAN 列表    | show vlan brief      | display vlan          | display vlan           |
| 邻居发现     | show cdp/lldp neigh  | display lldp neigh    | display lldp neigh     |
| CPU 利用率   | show processes cpu   | display cpu-usage     | display cpu-usage      |

## 前端页面结构

```
src/
├── pages/
│   ├── DashboardPage.tsx         → NOC 概览仪表盘
│   ├── DeviceManagementTab.tsx   → 设备管理 CRUD
│   ├── AutomationExecuteTab.tsx  → 自动化执行
│   ├── PlatformSettingsTab.tsx   → 配置管理
│   └── ...
├── components/
│   ├── MonitoringCenter.tsx      → 监控中心
│   ├── TopologyMap.tsx           → 拓扑图
│   ├── DeviceDetailModal.tsx     → 设备详情弹窗
│   └── ...
└── types.ts                      → 全局类型定义
```

## 前后端接口对接规范

- 前端 fetch 调用统一使用 `apiBaseUrl + endpoint` 拼接。
- 响应统一解析 `{ success, data, message }` 格式。
- 类型定义在 `types.ts` 中与 `schemas.py` 对应保持一致。
- 新增接口时同步更新前后端类型定义。

## 问题排查思路

1. **设备连接失败**：检查 device_type 是否正确 → 检查凭据是否加密 → 尝试 netmiko/scrapli 手动连接 → 检查防火墙/ACL。
2. **数据不一致**：检查 SQLite 写锁 → 检查事务是否 commit → 检查前端缓存。
3. **性能瓶颈**：SQLite 并发写上限 → 批量操作使用 ThreadPoolExecutor → SNMP 轮询频率调优。
