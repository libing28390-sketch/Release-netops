---
name: netops-grafana-dashboards
description: >
  Use the Nexora Grafana V2 visual baseline when designing, editing, validating, or troubleshooting dashboards.
version: 2.0.0
language: zh-CN
scope:
  - grafana
  - dashboard
  - dashboard-json
  - prometheus
  - victoriametrics
  - snmp
  - network-operations
  - nexora-netops
  - nexora-network-overview
  - nexora-network-device
  - nexora-network-wireless
  - nexora-network-interface
  - nexora-monitoring-health
  - nexora-network-outbound
  - nexora-linux-metrics
  - nexora-windows-metrics
  - nexora-interface-detail
  - nexora-platform-health
  - nexora-outbound-probe-quality
  - nexora-alert-operations
---

# Nexora Grafana Dashboard Design Skill V2

> This repository uses V2 as the normative visual baseline. It supersedes conflicting older palette and panel styling guidance; compatible repository metric, data source, version, and generation contracts below remain in force.

## 1. 目标

本 Skill 是 Nexora 当前整套 Grafana 监控界面的统一开发规范。

AI 的任务不是“把页面做得更花”，而是建立稳定的 NOC 视觉语言：

> **颜色不是装饰，是状态语言。**

> **只让异常发光。**

必须达到：

1. 第一屏 3 秒判断健康状态。
2. 颜色语义跨 Dashboard 一致。
3. 异常优先于普通业务数据。
4. No Data / Unknown 与 Fault 明确区分。
5. 视觉修改不得破坏业务查询逻辑。
6. 同一类指标在 12 个 Dashboard 中必须使用相同颜色。

---

## 2. Dashboard Registry

| # | UID | Dashboard | 定位 |
|---|---|---|---|
| 01 | `nexora-network-overview` | 网络总览 | 全局 NOC 首屏；规模、在线、趋势、资源热点、链路异常 |
| 02 | `nexora-network-device` | 网络设备详情 | 单设备身份、硬件健康、传感器、端口与流量 |
| 03 | `nexora-network-wireless` | 无线专网监控 | AP、终端、Radio、SSID/BSS 状态与热点 |
| 04 | `nexora-network-interface` | 接口流量与健康 | 多接口实时流量、利用率、质量与抖动 |
| 05 | `nexora-monitoring-health` | SNMP 采集健康 | SNMP 目标在线、采集耗时、失败目标 |
| 06 | `nexora-network-outbound` | 互联网出口与 WAN | 出口带宽、利用率、错误/丢弃与排行 |
| 07 | `nexora-linux-metrics` | Linux 服务器监控 | CPU、内存、负载、磁盘、网络与进程 |
| 08 | `nexora-windows-metrics` | Windows 服务器监控 | CPU、内存、磁盘、网络、RDP 与服务 |
| 09 | `nexora-interface-detail` | 接口详情 | 单接口流量、利用率、PPS、Flap、状态、光功率 |
| 10 | `nexora-platform-health` | 监控平台健康 | 平台端点、VM/vmagent、存储、Remote Write、容器 |
| 11 | `nexora-outbound-probe-quality` | WAN 链路健康与拨测质量 | 可用率、RTT、丢包、连续 Down、WAN 健康 |
| 12 | `nexora-alert-operations` | 告警处置与通知效果 | 告警严重度、生命周期、投递、MTTA/MTTR |


以上 12 个 Dashboard 全部属于本 Skill 的强制适用范围。后续新增同类 Dashboard 也必须继承本规范。

---

## 3. Nexora NOC Dark 标准色

| 语义 | Hex | 规则 |
|---|---:|---|
| Primary Blue | `#3B82F6` | 主数据、容量、Outbound、一般系统指标 |
| Network Cyan | `#22D3EE` | Inbound、Receive、网络实时数据 |
| Healthy Green | `#22C55E` | UP、Online、Normal、0 Fault |
| Wireless Purple | `#A78BFA` | Wireless、Client、辅助业务维度 |
| Warning Amber | `#F59E0B` | Warning、接近阈值 |
| High Orange | `#F97316` | High / Major / 中高风险 |
| Critical Red | `#F43F5E` | Down、Critical、Discard、严重异常 |
| Muted Gray | `#64748B` | No Data、Unknown、Unclassified |
| Soft Gray | `#94A3B8` | 次级文字 |

### 强制语义

- Green 只表达健康、正常、成功。
- Red 只表达明确严重异常。
- Gray 只表达未知、无数据、未分类。
- Inbound / Receive 固定 Cyan。
- Outbound / Transmit 固定 Blue。
- Error 固定 Amber。
- Discard 固定 Red。
- Wireless Client 固定 Purple。

禁止将 Green 同时作为普通 Outbound 曲线颜色。

---

## 4. No Data 与 0 的区别

这是 Nexora Dashboard 的重要规则。

`0` 可能代表健康：

- 0 个 Down 接口
- 0 个 Critical 告警
- 0 个 Remote Write failure
- 0 个异常部件

因此：

```text
0 Fault = Green
No Data = Gray
```

AI 在修改 Stat 时应优先使用 Value Mapping / Special Mapping，使 No Data 仍为 Gray，而不是因为默认阈值颜色而误显示为 Green。

---

## 5. Stat 设计

- 默认使用 `colorMode: value`。
- 不默认使用彩色整块背景。
- Critical 场景可以在明确需求下使用弱背景，但不是默认。
- 中性容量数据使用 Blue/Cyan/Purple。
- 健康状态使用 Green。
- 故障计数必须让 0 与 >0 产生明显差异。
- 不得把所有 Stat 统一为灰色。

---

## 6. Time Series

推荐：

```json
{
  "lineWidth": 2,
  "fillOpacity": 12,
  "gradientMode": "none",
  "showPoints": "never"
}
```

重要业务方向必须使用固定颜色。

大量设备/大量部件的多序列图可以保留 palette，但固定语义序列必须显式 override。

---

## 7. Table

原则：

> 文字负责信息，颜色负责状态。

优先：

1. Gauge
2. Colored text
3. Status text
4. 必要时才使用 colored background

禁止普通表格大面积红/绿背景。

Data Link、资产跳转、接口跳转不得因视觉重构而删除。

---

## 8. Threshold

有业务阈值时必须使用业务阈值。

优先级：

1. CMDB / 接口自定义阈值
2. 设备/厂商阈值
3. Nexora 业务配置阈值
4. Skill 默认视觉阈值

不得用 Skill 默认值覆盖更具体的业务阈值。

温度、光功率等强设备相关指标，没有设备阈值时禁止凭空制造 Critical 阈值。

---

## 9. JSON 安全契约

### MUST PRESERVE

- Dashboard UID
- Panel ID
- Datasource UID
- PromQL / MetricsQL
- Targets
- Template Variables
- Transformations
- Data Links
- Dashboard Links
- 统计口径
- 标签匹配逻辑

### 默认允许修改

- `fieldConfig`
- `options`
- `overrides`
- `thresholds`
- `mappings`
- `custom`
- panel 展示尺寸和布局（用户要求时）

### Query 修改

Query 永远排在最后。

如果没有用户明确授权，不得为了“看起来更好”改 Query。

---

## 10. 优化顺序

```text
1. 状态语义
2. 颜色
3. Threshold / Mapping
4. Stat
5. Time Series
6. Table / Gauge
7. Row 信息层级
8. Layout
9. Query（最后且需明确授权）
```


## 12 个 Dashboard 专项设计档案

### 01 Network Overview — `nexora-network-overview`

**角色：** 全局 NOC 首屏。用户进入监控后，应在 3 秒内判断“规模、健康、异常、热点”。

**固定规则：**
- 纳管设备数：Primary Blue。
- 监控站点数：Purple。
- 全网在线数：Healthy Green。
- 在线终端：Wireless Purple。
- 接口总数：Primary Blue。
- Down 接口：0=Green，1~4=Amber，>=5=Red。
- 总流量：Inbound=Cyan，Outbound=Blue。
- 无线趋势：Clients=Purple，AP=Cyan。
- CPU/Memory Top10：使用 Gauge，不使用整行背景色。
- Temperature Top10：没有设备阈值时不强行定义红黄阈值。
- Down Top20：只突出变化次数、状态等故障字段。

**特别注意：**
当前 CPU/内存/温度面板统计的是“覆盖设备数”，不是覆盖率。除非用户允许修改 Query，否则不得擅自改成百分比。

---

### 02 Network Device — `nexora-network-device`

**角色：** 单设备诊断页面，应突出“设备是否活着、硬件是否健康、哪个部件异常”。

**固定规则：**
- SNMP 在线=Green，不可达=Red，Unknown=Gray。
- 系统运行时长属于中性信息，使用 Blue。
- CPU/Memory Gauge：正常 Green，接近阈值 Amber，严重 Red。
- 最高温度没有厂商阈值时只作为 Purple/中性读数，禁止随意定义统一温度告警。
- 异常部件数：0=Green，>=1=Red。
- 状态未知部件数：0=Green，>=1=Amber。
- 渲染错误：0=Green，>=1=Red。
- 端口运行状态使用 colored text，避免大面积色块。
- 接口流量：Inbound=Cyan，Outbound=Blue。

---

### 03 Wireless — `nexora-network-wireless`

**角色：** 无线 AC/AP 运营页，应快速判断 AP 覆盖、离线、终端规模和 Radio 热点。

**固定规则：**
- 采集 AP=Purple。
- 在线 AP=Green。
- 离线 AP：0=Green，1~4=Amber，>=5=Red。
- 在线终端=Purple。
- 高利用率 Radio：0=Green，1~4=Amber，>=5=Red。
- Radio 利用率：Green → Amber → Orange → Red。
- 趋势：AP=Cyan，Client=Purple。
- AP 状态：online=Green，joining=Amber，offline=Red，unknown=Gray。
- AP 明细中的状态只给状态字段着色，不整行染色。

---

### 04 Network Interface — `nexora-network-interface`

**角色：** 多接口运营页，应突出流量方向、利用率热点、错误/丢弃和链路抖动。

**固定规则：**
- Inbound=Cyan。
- Outbound=Blue。
- Error=Amber。
- Discard=Red。
- 利用率默认阈值：<60 Green，60~75 Amber，75~90 Orange，>=90 Red；如果接口已有 CMDB 自定义阈值，应优先使用接口阈值。
- TopN 利用率使用 Gradient Gauge。
- Bar Gauge：Inbound=Cyan，Outbound=Blue。
- 运行状态使用 colored text，不使用整行或大面积 background。
- PPS：入向 Cyan、出向 Blue、组播 Purple、广播 Amber。

---

### 05 Monitoring Health — `nexora-monitoring-health`

**角色：** SNMP 采集链路自身的健康页。

**固定规则：**
- 在线目标=Green。
- 失败目标：0=Green，>=1=Red。
- 平均采集耗时=Blue。
- 最大采集耗时保留当前业务阈值：5s Amber、15s Red。
- 失败设备清单的失败状态=Red。
- 最慢目标排行使用 Gauge：<5s Green，5~15s Amber，>=15s Red。
- 不得把“指标缺失”自动等同于设备 Down。

---

### 06 Network Outbound — `nexora-network-outbound`

**角色：** Internet/WAN 出口流量运营页。

**固定规则：**
- Inbound=Cyan，Outbound=Blue。
- 最高利用率：Green / Amber / Orange / Red。
- Error/Discard 总速率：无异常 Green，有明显异常才 Amber/Red。
- 筛选接口数=Blue。
- 进出流量趋势必须固定方向颜色，不使用随机 palette。
- 利用率排行使用 Gradient Gauge。
- 错误/丢弃排行只突出数值字段。

---

### 07 Linux Metrics — `nexora-linux-metrics`

**角色：** Linux 主机健康与容量页。

**固定规则：**
- 纳管主机数=Blue。
- Uptime=Purple。
- CPU：<70 Green，70~85 Amber，>=85 Red。
- Memory：<80 Green，80~90 Amber，>=90 Red。
- TCP 活跃连接数属于业务/容量信息，使用 Cyan，不自动标红。
- 文件句柄保留当前 20k/100k 告警阈值。
- CPU 趋势：整机 Blue、user Cyan、system Purple、iowait Amber。
- Disk：Read=Cyan，Write=Blue。
- Network：Receive=Cyan，Transmit=Blue。
- 磁盘使用率 Top10 使用 Gauge；默认 70/85 作为视觉阈值，可由项目阈值覆盖。
- 阻塞/I/O wait 使用 Amber。

---

### 08 Windows Metrics — `nexora-windows-metrics`

**角色：** Windows 主机资源、磁盘、网络和服务运行状态页。

**固定规则：**
- 纳管主机数=Blue。
- CPU：<70 Green，70~85 Amber，>=85 Red。
- Memory：<80 Green，80~90 Amber，>=90 Red。
- RDP 活跃会话=Purple。
- 物理内存已用=Purple，可用=Cyan，Committed=Amber，Total=Gray。
- 磁盘剩余空间 Top10：<10 Red，10~20 Orange，20~30 Amber，>=30 Green。
- Network：Receive=Cyan，Transmit=Blue。
- 服务 Running=Green，Not Running=Red。
- 服务表只给状态字段着色。

---

### 09 Interface Detail — `nexora-interface-detail`

**角色：** 单接口深度诊断页面。

**固定规则：**
- 入向=Cyan，出向=Blue。
- 利用率使用 Green / Amber / Orange / Red。
- Error=Amber；精确为 0 时显示 Green。
- Discard=Red；精确为 0 时显示 Green。
- PPS：Unicast/方向使用蓝青体系，Multicast=Purple，Broadcast=Amber。
- 接口状态：Up=Green，Down=Red，Unknown=Gray。
- CMDB 阈值状态：NORMAL=Green，WARNING=Amber，HIGH=Orange，CRITICAL=Red。
- 光功率：Receive=Cyan，Transmit=Blue。
- 光模块 dBm 阈值不能凭空创建，应使用厂商/模块阈值。

---

### 10 Platform Health — `nexora-platform-health`

**角色：** Nexora 监控栈自身可用性页面。

**固定规则：**
- 平台端点在线=Green。
- 端点失败：0=Green，>=1=Red。
- 端点总数=Blue。
- 最大采集耗时保留 2s Amber / 5s Red。
- 数据库连接：1=Green，0=Red。
- Remote Write backlog：正常 Green，>=100MB Amber，>=1GB Red。
- Push failure / dropped packets：0=Green，>=1=Red。
- VM 可用空间=Cyan，已用数据量=Purple。
- Storage read-only：0=Green，1=Red。
- 容器磁盘 Read=Cyan，Write=Blue。
- 端点状态表只给状态字段着色。

---

### 11 WAN Probe Quality — `nexora-outbound-probe-quality`

**角色：** WAN/SLA/拨测质量页面。

**固定规则：**
- 样本量=Blue。
- 可用率默认视觉阈值：<95% Red，95~99% Amber，>=99% Green。
- RTT 平均值=Cyan，最大值=Purple/Orange，用颜色区分而不随意创建 RTT 告警阈值。
- 连续 Down 接口：0=Green，>=1=Red。
- 连续 Down 时长：0=Green，存在 Down 时使用 Red。
- ICMP 丢包默认视觉阈值：<1% Green，1~5% Amber，>=5% Red；业务 SLA 存在时必须覆盖此默认值。
- WAN 采集成功率 / Oper UP 比例：95% / 99% 阈值。
- WAN 流量：Downstream=Cyan，Upstream=Blue。
- Error=Amber，Discard=Red。
- 健康状态趋势：UP/Healthy=Green，Degraded=Amber，Down=Red，Unknown=Gray。

---

### 12 Alert Operations — `nexora-alert-operations`

**角色：** 告警运营、处置效率和通知效果页面。

**固定规则：**
- 当前打开告警：0=Green，1~4=Amber，>=5=Red。
- Critical：0=Green，>=1=Red。
- Major：0=Green，>=1=Orange。
- Warning：0=Green，>=1=Amber。
- Minor：0=Green，>=1=Purple。
- 通知成功率默认视觉阈值：<95% Red，95~99% Amber，>=99% Green。
- 告警生命周期：New=Purple，Acknowledged=Amber，Recovered=Green。
- 通知结果：Succeeded=Green，Retrying=Amber，Failed=Red。
- 最久未恢复时长保留 1h Amber / 24h Red。
- 重复未恢复告警：0=Green，1~4=Amber，>=5=Red。
- MTTA/MTTR 没有业务 SLA 时使用中性 Blue/Purple，不擅自标红。


## 13. AI 执行流程

### STEP 1：识别 Dashboard

必须先根据 UID / title 判断属于哪一个专项档案。

### STEP 2：完整扫描

检查：

- Panel type
- Stat thresholds
- Timeseries colors
- Table overrides
- palette-classic
- No Data
- Links
- Variables
- Transformations
- PromQL

### STEP 3：建立业务语义

每个指标归入：

```text
Inventory
Health
Traffic
Wireless
Warning
Critical
Unknown
Capacity
Quality
```

### STEP 4：只修改展示层

默认不改 Query。

### STEP 5：验证

必须程序化或人工确认：

- targets 未变化
- templating 未变化
- panel IDs 未变化
- transformations 未变化
- links 未变化
- UID 未变化

### STEP 6：输出

如果用户要求直接优化 JSON，应提供：

1. 优化后的完整 JSON。
2. Dashboard 级修改摘要。
3. 明确说明是否改 PromQL。
4. 明确说明是否改统计口径。
5. 明确说明是否保留 Data Link。
6. 说明使用了哪些默认视觉阈值。

---

## 14. 验收 Checklist

### 全局

- [ ] 12 个 Dashboard 使用同一套颜色语言
- [ ] Green 不再承担 Outbound 普通业务曲线
- [ ] Error / Discard 已统一 Amber / Red
- [ ] No Data 为 Gray
- [ ] 0 Fault 为 Green
- [ ] Inbound / Outbound 为 Cyan / Blue
- [ ] Wireless Client 为 Purple

### JSON 安全

- [ ] UID 未改变
- [ ] Panel ID 未改变
- [ ] PromQL 未改变
- [ ] Targets 未改变
- [ ] Variables 未改变
- [ ] Transformations 未改变
- [ ] Data Link 未改变

### 页面观感

- [ ] 第一屏能快速判断状态
- [ ] 红色数量明显少于普通颜色
- [ ] 表格未大面积染色
- [ ] 关键数值比辅助字段更突出
- [ ] 同一业务语义跨页面颜色一致

---

## 15. 最终设计原则

> Nexora 不是“Grafana 默认 Dashboard 的集合”，而应是一套统一的 Network Operations 产品。

> 少颜色，高对比，强语义，统一规则。

> 正常状态不抢眼，故障状态必须第一时间被看到。

> 在没有数据依据时，不用颜色假装知道设备是否健康。


## 16. Repository integration

### Project conventions

- This repository pins Grafana `12.1.0` in `docker-compose.yml`. Verify that version before relying on a dashboard feature; Grafana `/latest/` documentation may describe a newer release.
- VictoriaMetrics is provisioned as the Prometheus-compatible data source with UID `victoriametrics`. Preserve that UID and verify the data source before changing any query.
- `monitoring/grafana/generate_dashboards.py` and `monitoring/grafana/dashboard_presentation_v2.json` are the authoring sources for the 12 generated dashboards. The JSON files in `monitoring/grafana/dashboards/` are outputs. Do not edit generated JSON alone. Before running the generator, inspect `git status` and its full output list, and preserve user edits.

### Metric and traffic semantics

- Treat metric names, labels, units, and meanings as an explicit contract. Check collector/exporter configuration, the metric catalog, generator queries, and relevant source before writing PromQL. A dashboard title does not prove that a metric or label exists.
- For interface metadata, `ifName` is the interface name, `ifAlias` carries the configured description, and `ifIndex` is an internal join key. Match series on the correct device/interface identity and do not require labels that the selected source metric does not expose.
- Do not call the sum of all monitored interface rates “total network traffic.” The same flow can be counted at access, aggregation, and core interfaces, and `ifHCIn`/`ifHCOut` are relative to each device. Use “observed interface traffic” or “monitored interface aggregate” and state the selected scope. Use WAN/edge ingress or egress only when interface roles identify the boundary and the query filters exactly those interfaces.
- Separate traffic hotspots from congestion risk. Rank raw throughput to find busy links; rank utilization against known per-direction capacity to find constrained links. Do not interpret unknown or invalid speed as spare capacity. On full-duplex links, evaluate ingress and egress against capacity independently.

### Units, mappings, and panel behavior

- Use the source metric's actual unit. IF-MIB octet counters become bytes/s after `rate()` and bits/s after multiplying by 8; error/discard counter rates are packets/s; utilization is percent only after dividing traffic rate by a known interface capacity. Match Grafana percent units and thresholds to the query scale (0–1 ratio versus 0–100 percentage). Set unit, decimals, min/max, and no-value text explicitly.
- Show current utilization and rate for the selected interval. Add peak/P95 utilization only with an explicit time window and per-interface meaning; calculate PPS from collected packet counters rather than estimating it from bit rate. Show headroom only when capacity is known, with ingress and egress separate.
- For IF-MIB, distinguish `ifAdminStatus` (desired/admin state) from `ifOperStatus` (observed operational state). Values 1–7 mean up, down, testing, unknown, dormant, notPresent, and lowerLayerDown; confirm exporter output before mapping extra values such as 0. Admin-down plus oper-down is not automatically faulty; admin-up plus oper-down is a fault candidate.
- Use exact Value mappings for enumerated states, Range mappings for meaningful continuous bands, Special mappings for `null`/`NaN`, and Regex mappings only for controlled string formats. In tables, choose colored text or background cell mode for mapped colors. Value mappings are presentation rules, not data conversion; mapped values can bypass unit/decimal formatting, and on Time series they change display text but do not apply mapped colors to the series.
- Apply thresholds to continuous values with a known unit and range, such as utilization against interface capacity or a documented temperature policy. Thresholds affect panel display; they do not create alert rules or notifications. Never invent temperature or optical-power thresholds when device/business thresholds are unavailable.
- Use transformations for presentation tasks such as organizing, renaming, hiding, or sorting fields after the query. Keep counter math and identity-sensitive joins in PromQL or the metric contract where possible. Inspect intermediate/final table data when a panel looks wrong; do not use a lossy reduction that hides per-device or per-interface faults.
- Name series with stable site/device/interface labels and bound high-cardinality views with variables or Top N. Use tooltips suited to the comparison without listing an unreadable fleet. Add data links from fleet/top-N tables to the relevant device/interface dashboard while carrying selected variables. Grafana panel Actions can issue unauthenticated API calls; do not use them for device configuration changes or other privileged operations.
- When a panel is empty, inspect the raw query and expanded variables first, then returned fields/labels, transformation output, panel mappings, time range, scrape interval, and data-source health. Distinguish a true zero counter rate from missing scrapes or absent metrics.
- PromQL/query edits require explicit user authorization. This visual optimization standard does not authorize query or metric changes.

### Operator visualization patterns

## Choose a visualization for the network task

The existing Nexora dashboards mainly use Stat, Time series, and Table panels. Keep those as the default; choose another panel when its data shape makes a network operation easier to understand.

| Operator question | Preferred view | Network-specific fit and limits |
|---|---|---|
| How many devices, interfaces, APs, or failed scrapes are there right now? | Stat | Show a small set of fleet totals or current values. Pair it with an exception list; a total alone does not locate the fault. |
| Is traffic, utilization, CPU, temperature, or scrape duration changing over time? | Time series | Best for timestamped measurements. Keep fleet series bounded (for example, selected devices or Top N) and use separate units/queries for bps, pps, percent, and temperature. |
| Which device or interface is down, busy, or accumulating errors? | Table | Best when the operator needs identity and several facts together: site, device, interface name/description, admin state, oper state, current rate, and errors. Sort by the operational concern and use readable state mappings. |
| Which interfaces or devices have the highest current rate or utilization? | Bar chart or Table | Use a ranked bar chart for quick comparison; use a table when device/interface identity, alias, multiple metrics, or drill-down links matter. Limit the result to a useful Top N. |
| Is one selected interface close to its capacity? | Gauge; Bar gauge or table gauge for several interfaces | Use a Gauge for one selected interface and a known capacity range. For many ports, prefer a Bar gauge or a table with gauge cells so labels and values remain readable. Do not imply 0–100% capacity when the speed is absent or invalid. |
| Which links flapped or remained down during a time window? | State timeline or Status history | Use for a small, filtered set of sampled device/interface states. State timeline can merge consecutive equal states; Status history preserves each periodic sample. Scrape interval, gaps, and retention limit the accuracy of the history. |
| Where are devices or sites, and how are they physically connected? | Geomap or Node graph, only with matching data | Geomap needs usable location fields such as coordinates or geohash. Node graph needs real node/edge data. Current VictoriaMetrics dashboard labels provide site/device/interface identity but no site coordinates or topology edges; get that data from the asset/topology model before choosing these views. |
| Is a measurement distribution changing? | Heatmap or Histogram, only with distribution data | Use when the source supplies histogram buckets or a suitable distribution. Ordinary interface byte counters and their rates are not histograms. |

Pie charts are appropriate only for a small categorical composition where proportions answer the question. They are a poor fit for time trends and long device/interface rankings.

## Dashboard responsibilities and traffic semantics

- Keep fleet discovery on the network overview: device/interface health, major exceptions, and monitored traffic hotspots. Use the interface traffic and health dashboard to explain the selected ports with utilization, rates, errors/discards, and state. Device/interface detail should answer why one selected asset is unhealthy. Prefer drill-down links over repeating the same Top-N panels on every dashboard.
- Do not call the sum of all monitored interface rates “total network traffic.” The same flow can be counted at access, aggregation, and core interfaces, and `ifHCIn`/`ifHCOut` are relative to each device. Use “observed interface traffic” or “monitored interface aggregate” and show the selected scope. Use WAN/edge ingress or egress only when interface roles identify the boundary and the query filters exactly those interfaces.
- Separate traffic hotspots from congestion risk. Rank raw throughput to find busy links; rank utilization against known per-direction capacity to find constrained links. Do not interpret unknown or invalid speed as spare capacity. On full-duplex links, evaluate ingress and egress against capacity independently.

## Configure Grafana for network semantics

- **Units and field options:** Use the source metric's actual unit. IF-MIB octet counters become bytes/s after `rate()` and bits/s after multiplying by 8; error/discard counter rates are packets/s; utilization is percent only after dividing traffic rate by a known interface capacity. Match the Grafana percent unit and thresholds to the query scale (0–1 ratio versus 0–100 percentage). Set unit, decimals, min/max, and no-value text explicitly. Do not threshold a raw counter as though it were a utilization percentage.
- **Capacity and health measures:** Show current utilization and rate for the selected interval. Add peak/P95 utilization only with an explicit time window and per-interface meaning; calculate PPS from collected packet counters rather than estimating it from bit rate. Show headroom only when capacity is known, keeping ingress and egress separate. Treat `ifLastChange` as an uptime-relative state-change value, not a wall-clock timestamp; derive flap counts from adequately sampled state transitions. Check the current collector and metric contract before using any of these measures.
- **Value mappings:** Use exact Value mappings for enumerated states, Range mappings for meaningful continuous bands, Special mappings for `null`/`NaN`, and Regex mappings only for controlled string formats. For IF-MIB, distinguish `ifAdminStatus` (desired/admin state) from `ifOperStatus` (observed operational state). `ifOperStatus` values 1–7 mean up, down, testing, unknown, dormant, notPresent, and lowerLayerDown; confirm what the exporter actually emits before mapping any extra value such as 0. An interface with admin-down and oper-down is not automatically faulty; admin-up plus oper-down is a fault candidate. Keep unavailable data separate from a valid unknown state. In tables, choose colored-text/background cell mode for mapped colors. Value mappings are presentation rules, not data conversion; mapped values can bypass unit/decimal formatting, and on Time series they change display text but do not apply mapped colors to the series.
- **Thresholds and overrides:** Apply thresholds to continuous values with a known unit and range, such as utilization against interface capacity or a documented temperature policy. Panel thresholds only affect display; they do not create alert rules or notifications. For alert-policy changes, use `netops-monitoring-telemetry` and follow the project's alert architecture. Use targeted field overrides for direction-specific colors, units, and labels; avoid a global override when one panel contains mixed units or different device metrics.
- **Queries and expressions:** Use PromQL in the current VictoriaMetrics data source for metric filtering, counter rates, label joins, and aggregation. Calculate `rate()` before aggregating counters and keep grouping labels aligned with device/interface identity. Grafana expressions can help with small post-query calculations or combining query results. Share a query result across panels only when the query and result shape really are shared; avoid unnecessary dependencies between panels. SQL Expressions became public preview after this repository's Grafana `12.1.0` pin; do not make the current dashboards depend on them unless the target instance has been upgraded and the feature has been confirmed.
- **Transformations:** Use transformations for presentation tasks such as organizing, renaming, hiding, or sorting fields after the query. Keep counter math and identity-sensitive joins in PromQL or the metric contract where possible. Transformations run in order, so inspect intermediate/final table data when a panel looks wrong; do not use a lossy reduction that hides the per-device or per-interface fault.
- **Legends, tooltips, and drill-down:** Name series with stable site/device/interface labels and bound high-cardinality views with variables or Top N. Use tooltips that support the comparison without listing an unreadable fleet. Add data links from fleet/top-N tables to the relevant device or interface dashboard while carrying the selected variables. Grafana panel Actions can issue unauthenticated API calls; do not use them for device configuration changes or other privileged operations.
- **Empty panels:** Inspect the raw query and expanded variables first, then the returned fields/labels, transformation output, panel mappings, time range, scrape interval, and datasource health. Distinguish a truly zero counter rate from a missing scrape or absent metric.

## Dashboard workflow

1. Identify the operator question, audience, time horizon, and source metrics. Check the current dashboard, data source, collection path, and target Grafana version before changing panel definitions.
2. Design the page around the V2 investigation order: status, colors, thresholds/mappings, Stat, Time series, Table/Gauge, row hierarchy, then layout. Apply the dashboard-specific rules in the registry above.
3. Write queries against observed metric contracts. For counters, calculate rates before aggregating; retain only labels needed for filtering or interpretation; avoid accidental duplicate series from joins. Prefer high-capacity interface counters where collected, and use a fallback only when that fallback is part of the contract.
4. Keep missing, unknown, and healthy-zero states distinct. Do not turn absent telemetry into zero or a healthy status unless another availability signal proves that zero is meaningful. Configure useful no-value text and explicit status mappings where panels show device or interface state.
5. Use dashboard variables and transformations only when they improve reuse or legibility. Confirm variable queries return values for the configured data source, and confirm chained filters do not create unexpectedly broad or expensive queries.
6. Keep dashboard files version-controlled. Do not write to a live Grafana instance, alter provisioning, or deploy generated dashboards unless the user requested that operation.

## Validation

- For generator changes, inspect `git status` and the complete 12-dashboard output catalog first, then run the generator, compile the Python module, and parse all generated dashboard JSON files.
- Review the full diff and verify the JSON safety contract: UID, panel IDs, datasource UID, queries/targets, variables, transformations, links, and aggregation logic remain unchanged unless explicitly authorized.
- Review V2 semantic colors, Stat no-data mappings, zero-versus-fault thresholds, units, and known business/device thresholds. Check metric labels against the actual collection contract before changing PromQL.
- Run `git diff --check`. Use `netops-monitoring-telemetry` when metric collection or alert semantics change and `netops-quality-gate` when focused repository checks are needed.
- Source JSON validation does not prove that dashboards render or return data in the target Grafana. State clearly when visual or live-instance verification was not performed.

## Grafana documentation

Use the official documentation for the target Grafana release when checking UI behavior or schema details. The links below use `/latest/`; switch to the deployed release in Grafana's documentation version selector before relying on specifics:

- [Dashboards](https://grafana.com/docs/grafana/latest/visualizations/dashboards/) — panels, queries, transformations, and dashboard structure.
- [Dashboard variables](https://grafana.com/docs/grafana/latest/visualizations/dashboards/variables/) — variable types and behavior.
- [Panel visualizations](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/) — choose a panel by the shape and question of the data.
- [Configure value mappings](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-value-mappings/) — exact values, ranges, regexes, and special values.
- [Configure standard options](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-standard-options/) — units, bounds, decimals, display names, colors, and no-value display.
- [Configure thresholds](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-thresholds/) — numeric thresholds and threshold modes.
- [Configure field overrides](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-overrides/) — targeted per-field or per-series display settings.
- [Transform data](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/query-transform-data/transform-data/) — field shaping and transformation order.
- [Configure tooltips](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-tooltips/) — interaction when inspecting time-series panels.
- [Configure data links and actions](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-data-links/) — contextual drill-down and action behavior.
- [Provision Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/) — file-based dashboard and data-source provisioning.
- [Dashboard overview](https://grafana.com/docs/grafana/latest/fundamentals/dashboards-overview/) — data source, query, transformation, and panel concepts.
- [RFC 2863: IF-MIB](https://www.rfc-editor.org/rfc/rfc2863) — interface admin/oper state and counter semantics.
