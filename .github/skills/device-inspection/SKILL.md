---
name: device-inspection
description: "网络设备巡检与故障排查工作流。Use when: 设备巡检, device inspection, 故障排查, troubleshooting, 健康检查, health check, 连通性测试, connectivity test, 设备诊断, device diagnostics, 网络排障, 批量巡检, patrol, 接口排查, 告警分析, 合规检查。"
argument-hint: "描述要巡检或排查的设备、范围或故障现象"
---

# 网络设备巡检与故障排查

端到端的设备巡检和故障定位工作流，适用于 NetOps 平台支持的多厂商网络设备（Cisco IOS/NX-OS/IOS-XE、Huawei VRP、H3C Comware、Arista EOS、Juniper JunOS）。

## 何时使用

- 定期设备巡检（单台或批量）
- 接到告警后的故障排查
- 设备上线前的连通性与健康验证
- 接口异常（flapping、高利用率、error/discard）定位
- 合规基线偏离排查

## 巡检流程（Inspection）

### 阶段 1：确定巡检范围

1. 明确目标：单台设备、设备组、站点、还是全网
2. 从 `devices` 表获取设备清单，确认 IP、厂商、平台、角色（router/switch）
3. 如果是告警驱动，先从 `GET /device-health/overview` 获取健康评分低的设备列表

### 阶段 2：连通性验证

按层级逐步排查，每层通过才进入下一层：

```
Layer 1: ICMP Ping
  ├─ 通 → 记录延迟，进入 Layer 2
  └─ 不通 → 记录为 ICMP 不可达（可能被 ACL 过滤，不一定代表设备离线）

Layer 2: TCP 端口探测（SSH:22 / Telnet:23）
  ├─ 通 → 进入 Layer 3
  └─ 不通 → 排查方向：防火墙策略、VTY 线路数、SSH 服务状态

Layer 3: SSH 认证（Deep 模式）
  ├─ 成功 → 设备可管理，进入巡检采集
  ├─ SSH 算法不匹配 → 尝试 Scrapli fallback（支持旧算法）
  ├─ 认证失败 → 检查凭据、AAA 配置、VTY 权限
  └─ 超时 → 检查设备负载、会话数限制
```

**对应 API**: `POST /devices/connect`，参数 `check_mode='quick'` 或 `'deep'`

### 阶段 3：健康数据采集

通过以下接口采集设备健康快照：

| 检查项 | API / 数据源 | 关键指标 |
|--------|-------------|---------|
| 综合健康评分 | `GET /device-health/device/{id}` | score (0-100)、status |
| 健康趋势 | `GET /device-health/device/{id}/trend` | 24h 评分走势 |
| CPU/内存 | 设备 CLI → TextFSM 解析 | 利用率 >80% 告警，>90% 严重 |
| 温度 | 设备 CLI | >60°C 警告，>75°C 严重 |
| 电源/风扇 | 设备 CLI | 冗余丢失 / 故障 |
| 接口状态 | `operational_data_service` → interfaces | down 接口数、flapping 接口 |
| 接口利用率 | 监控数据 | >85% 高利用率 |
| 接口错误率 | 监控数据 | error/discard 计数 |
| 告警 | `alert_rules` 匹配 | critical/major/warning 数量 |

### 阶段 4：运维数据深采（按需）

根据设备角色选择性采集：

| 类别 | 路由器 | 交换机 | 命令示例 |
|------|--------|--------|---------|
| 接口详情 | ✓ | ✓ | `show ip interface brief` |
| 邻居发现 | ✓ | ✓ | `show lldp/cdp neighbors detail` |
| ARP 表 | ✓ | ✓ | `show arp` |
| MAC 地址表 | ✗ | ✓ | `show mac address-table` |
| 路由表 | ✓ | ✗ | `show ip route` |
| BGP 邻居 | ✓ | ✗ | `show bgp summary` |
| OSPF 邻居 | ✓ | ✗ | `show ospf neighbor` |
| BFD 会话 | ✓ | ✗ | `show bfd neighbors` |

**关键**: 使用 `operational_data_service` 采集，输出经 ntc-templates TextFSM 结构化解析。

> 各厂商对应 CLI 命令详见 [多厂商命令对照表](./references/vendor-commands.md)。

### 阶段 5：合规检查

运行合规规则扫描（`POST /compliance/run`），关注以下基线：

| 规则 ID | 检查内容 | 严重程度 |
|---------|---------|---------|
| MGMT-001 | Telnet 是否禁用 | 高 |
| MGMT-002 | SSHv2 是否启用 | 高 |
| SNMP-001 | SNMP 社区名非默认值 | 中 |
| LOG-001 | 集中 Syslog 已配置 | 中 |
| TIME-001 | NTP 已配置 | 中 |
| AAA-001 | AAA/RADIUS/TACACS 已配置 | 高 |
| L2-001 | BPDU Guard/Edge 保护 | 中 |
| CFG-001 | 配置快照存在 | 低 |

### 阶段 6：生成巡检报告

汇总输出结构化报告，包括：

```
## 巡检报告 — {日期}

### 概览
- 巡检设备数: N
- 健康设备: X | 告警设备: Y | 不可达设备: Z

### 设备明细
| 设备 | IP | 健康评分 | CPU | 内存 | 告警数 | 合规状态 |
|------|-----|---------|-----|------|--------|---------|

### 异常发现
1. [严重] 设备 X — CPU 持续 >90%，建议排查进程
2. [警告] 设备 Y — Gi0/1 接口 flapping，建议检查线路

### 合规偏离
- 设备 A: MGMT-001 (Telnet 未禁用)
- 设备 B: SNMP-001 (默认社区名)

### 建议操作
1. ...
```

---

## 故障排查流程（Troubleshooting）

### 步骤 1：症状收集

明确故障现象，常见类型：

| 症状 | 初步方向 |
|------|---------|
| 设备不可达 | 连通性 → 阶段 2 的分层排查 |
| 接口 Down | 物理层 / 协议层 / 配置问题 |
| 接口 Flapping | 线缆、光模块、对端设备、STP |
| 高延迟 / 丢包 | 带宽利用率、QoS、路由环路 |
| BGP/OSPF 邻居丢失 | 认证、Timer、MTU、链路故障 |
| CPU/内存高 | 进程分析、路由震荡、广播风暴 |
| 配置丢失/变更 | 配置漂移检测 → `config_drift` API |

### 步骤 2：快速诊断

1. **连通性测试**: `POST /devices/connect` (deep 模式)
2. **健康评分**: `GET /device-health/device/{id}` — 评分 <50 为 Critical
3. **活跃告警**: 检查该设备关联的 critical/major 告警
4. **最近变更**: 查询 `audit_logs` 和 `change_orders` 确认是否有近期配置变更

### 步骤 3：深度采集

根据症状选择性执行命令：

**接口故障**:
```
show interface {intf}
show interface {intf} counters errors
show spanning-tree interface {intf}
show cdp/lldp neighbors {intf}
```

**路由故障**:
```
show ip route
show bgp summary / show bgp neighbor {peer}
show ospf neighbor / show ospf interface
show bfd neighbors
```

**性能问题**:
```
show processes cpu sorted
show memory summary
show interface utilization
show logging last 50
```

### 步骤 4：关联分析

- 对比配置漂移: `GET /config-drift/` 查看近期变更
- 检查拓扑影响: `GET /topology/` 确认上下游设备状态
- 时间线关联: 将故障时间点与告警、变更记录对齐

### 步骤 5：修复与验证

1. 制定修复命令（config 模式需走审批流程）
2. 通过 `POST /automation/execute` 执行修复
3. 危险命令自动拦截（write erase、reload 等）
4. 修复后重新执行连通性和健康检查验证

---

## 决策参考

### 健康评分扣分规则

| 指标 | 阈值 | 扣分 |
|------|------|------|
| CPU | >80% | -14 |
| CPU | >90% | -25 |
| 内存 | >80% | -14 |
| 内存 | >90% | -25 |
| 温度 | >60°C | -10 |
| 温度 | >75°C | -20 |
| 风扇故障 | - | -35 |
| 电源故障 | - | -35 |
| 接口 Down | 每个 | -4 ~ -16 |
| 接口 Flapping | 每个 | -6 ~ -18 |
| Critical 告警 | 每个 | -18 ~ -36 |

### 驱动 Fallback 机制

```
Netmiko (默认)
  └─ SSH 算法协商失败?
      └─ 自动切换 Scrapli
          ├─ Windows: Paramiko 传输
          ├─ Linux/Mac: 系统 SSH
          └─ 支持旧设备的 legacy KEX/cipher
```

### 命令安全黑名单

以下命令会被自动阻止（403）：
`write erase`, `erase startup`, `format`, `delete /force`, `reload`, `reboot`, `reset saved-configuration`, `restore factory-default`, `system-shutdown`

---

## 辅助资源

- [多厂商巡检命令对照表](./references/vendor-commands.md) — 6 大厂商诊断命令速查
- [批量巡检脚本模板](./scripts/batch_inspection.py) — Python 脚本，调用 API 批量巡检并生成报告
