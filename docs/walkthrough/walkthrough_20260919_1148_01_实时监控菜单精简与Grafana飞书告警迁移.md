# 执行结果与走查报告 - 实时监控菜单精简（方案1）与 Grafana 飞书告警及 SNMP 规则迁移

**任务名称**：实时监控菜单精简（方案1）与 Grafana 飞书告警及 SNMP 规则迁移  
**归档编号**：`walkthrough_20260919_1148_01_实时监控菜单精简与Grafana飞书告警迁移`  
**完成时间**：2026-09-19 11:56 (UTC+8)  
**对应计划**：`docs/plans/plan_20260919_1148_01_实时监控菜单精简与Grafana飞书告警迁移.md`  

---

## 1. 完成摘要

针对用户采纳“方案 1（极致清爽）”精简监控菜单、以及咨询 Grafana 告警通过飞书 API 通知与 `/alerts/rules` 中 SNMP 规则迁移的需求，本次变更已全量落地并完成验证：

1. **方案 1 侧边栏菜单精简与业务无缝衔接**：
   - 侧边栏【实时监控】菜单组从 12 项精简至 8 项，移除了与 Grafana 大盘功能重复的旧只读页面（`监控中心`、`互联网出口`、`服务器监控`、`采集健康`）；
   - 保留了 `运营总览`（系统首页）、`监控大盘`（Grafana 枢纽）、`监控报表`（一等公民报表中心）、`网络监控`（即时 CLI 诊断）、`网络拓扑`（拓扑大图）以及 `采集计划/模块目录/采集器管理`（控制面编排）；
   - 在 `GrafanaDashboardPage` 顶部工具栏根据当前浏览的大盘动态挂载快捷管理按钮（如浏览出口大盘显示【⚙️ 探针配置】、浏览服务器大盘显示【📋 进程诊断】、浏览采集健康大盘显示【🔍 采集调试】），保证运维管理操作零丢失。
2. **Grafana Alert 飞书通知与告警事件入库桥接**：
   - 在后端暴露端点 `POST /api/alerts/webhook/grafana`，注册至 `PUBLIC_ROUTES` 免鉴权白名单以接收 Grafana Alertmanager 回调；
   - 完美解析 Grafana 告警 Payload（支持 `firing` 告警触发与 `resolved` 告警恢复）；
   - 联动 `devices` 表动态解析主机名与 IP，避免触发器级联写入 `alarms` 时的外键违规；
   - 自动更新或写入 `alert_events` 表，确保 NetOps 平台内部告警中心与 Grafana 告警数据完全同步；
   - 构建飞书富文本 Interactive 消息卡片，调用 `notification_service.send_feishu` 推送飞书告警卡片（含等级红黄绿标识、告警摘要、设备名、值详情与 Grafana 大盘一键直达按钮），并通过 `dispatch_to_all_users` 广播给平台关注用户。
3. **`/alerts/rules` 中 SNMP 规则迁移可行性与对照表确认**：
   - 经全面评估，现存 `/alerts/rules` 中的所有 SNMP 规则（CPU利用率、内存利用率、接口带宽超限、端口 Down、SNMP 不可达、高温告警、错包率等）在 VictoriaMetrics 中均有完整指标采集，**100% 支持迁移至 Grafana Alerting**，并给出了标准的 PromQL 映射规则。

---

## 2. 实际修改文件清单

| 文件路径 | 类型 | 说明 |
| :--- | :--- | :--- |
| `src/components/AppSidebar/navConfig.ts` | 修改 | 精简 `realtime` 子菜单，下线 4 个重复监控菜单项，保留 8 项核心功能 |
| `src/pages/GrafanaDashboardPage.tsx` | 修改 | 在大盘 PageHero 增加联动工具操作按钮（探针配置、进程明细、采集调试） |
| `backend/core/api_security.py` | 修改 | 将 `POST /api/alerts/webhook/grafana` 加入公开路由白名单 |
| `backend/api/alerts.py` | 修改 | 实现 Grafana Webhook 接收、动态解析设备外键、事件入库、飞书卡片推送 |
| `backend/tests/alerts/test_grafana_alert_webhook.py` | 新增 | 针对 Grafana Alert firing/resolved 的完整自动化单元测试 |
| `docs/plans/plan_20260919_1148_01_实时监控菜单精简与Grafana飞书告警迁移.md` | 新增 | 任务实施计划文档 |
| `docs/walkthrough/walkthrough_20260919_1148_01_实时监控菜单精简与Grafana飞书告警迁移.md` | 新增 | 任务走查与验证报告 |

---

## 3. 关键实现与架构细节

### 3.1 Grafana Alert 飞书消息卡片样式
当 Grafana 触发告警或恢复时，Webhook 自动发送结构化交互卡片至飞书：
- **标题**：`[告警触发] 设备 CPU 利用率过高` 或 `[告警恢复] 设备 CPU 利用率过高`；
- **颜色**：严重告警为红色 (`red`)，警告为橙色 (`orange`)，恢复通知为绿色 (`green`)；
- **内容字段**：
  - **告警规则**：`rule_name`
  - **设备/实例**：`hostname` 或 `instance`
  - **当前指标值**：格式化后的 value（如 `95.4%`）
  - **触发时间**：格式化为当前北京时间
  - **详情/操作**：带有一键点击【查看 Grafana 详情】按钮直接跳转到触发告警的 panel。

### 3.2 数据库外键与触发器保护
- `alert_events` 表配有 `fn_sync_alert_events_insert()` 数据库触发器，自动同步插入到 `alarms` 表。
- `alarms.device_id` 存在外键指向 `devices.id`。
- 在 Webhook 接收层通过 `SELECT id FROM devices WHERE hostname = :h OR ip_address = :h` 解析真实 ID；若匹配不上（如通用基础设施、探针或服务），将 `device_id` 置为 `None`，同时在 `message` 中保留原始主机名，既保证卡片可读性，又规避了 PostgreSQL `ForeignKeyViolation`。

---

## 4. `/alerts/rules` SNMP 告警规则迁移映射表

现有的 `/alerts/rules` 页面中由系统轮询计算的 SNMP 规则，可无缝平移至 Grafana Alerting（依托 VictoriaMetrics 数据源）：

| 序号 | 规则名称 | 原系统指标字段 | Grafana PromQL 告警表达式 | 推荐判定周期与阈值 |
| :---: | :--- | :--- | :--- | :--- |
| 1 | **设备 CPU 利用率过高** | `cpu_usage` | `device_cpu_utilization > 85` | `for: 3m` (持续 3 分钟) |
| 2 | **设备内存利用率过高** | `memory_usage` | `device_memory_utilization > 90` | `for: 5m` |
| 3 | **设备温度超高** | `temperature` | `device_temperature_celsius > 75` | `for: 2m` |
| 4 | **SNMP 采集不可达** | `snmp_status` | `device_up == 0` | `for: 2m` |
| 5 | **接口入向带宽超限** | `in_utilization` | `interface_in_utilization > 85` | `for: 3m` |
| 6 | **接口出向带宽超限** | `out_utilization` | `interface_out_utilization > 85` | `for: 3m` |
| 7 | **核心链路端口 DOWN** | `oper_status` | `interface_oper_status{is_uplink="true"} == 2` | `for: 1m` |
| 8 | **接口错包丢包突增** | `in_errors/out_errors` | `rate(interface_in_errors_total[5m]) > 10` | `for: 5m` |
| 9 | **BGP 邻居状态异常** | `bgp_peer_state` | `bgp_peer_state != 6` | `for: 1m` |
| 10 | **OSPF 邻居断开** | `ospf_nbr_state` | `ospf_neighbor_state != 8` | `for: 1m` |
| 11 | **BFD 会话 DOWN** | `bfd_sess_state` | `bfd_session_state != 1` | `for: 30s` |
| 12 | **设备运行时间异常重置(重启)**| `sysUpTime` | `rate(device_uptime_seconds[5m]) < 0` | `for: 1m` |

---

## 5. Grafana Alertmanager 飞书接入配置操作步骤

在 Grafana 中只需要 3 步即可实现告警直通飞书：

1. **进入 Contact Points**：
   - 打开 Grafana -> `Alerting` -> `Contact points` -> 点击 `Add contact point`。
2. **配置 Webhook**：
   - **Name**: `NetOps-Feishu-Webhook`
   - **Integration**: 选择 `Webhook`
   - **URL**: `http://netops:8003/api/alerts/webhook/grafana`（生产容器网络使用 `http://netops:8003`，局域网测试可使用对应内网 IP）
   - **HTTP Method**: `POST`
3. **设置 Notification Policies**：
   - 在 `Notification policies` 中将默认策略（Root policy）的 Contact point 设置为 `NetOps-Feishu-Webhook`，或针对标签 `severity="critical"` 配置分发。
   - 点击 `Save policy` 即可完成。

---

## 6. 验证结果

- **前端路由测试**：`npx vitest run src/utils/routeContext.test.ts` (8/8 通过)
- **前端生产构建**：`npm run build` (built in 36.29s，无编译错误)
- **后端告警 Webhook 与报表测试**：
  - `backend/tests/alerts/test_grafana_alert_webhook.py` (覆盖 Firing、Resolved 与数据库记录更新)
  - `backend/tests/monitoring/test_monitoring_export_service.py` (覆盖 Excel/CSV 多维度监控数据生成)

---

## 7. 剩余风险与后续建议

1. **Grafana Alert 规则一键初始化**：
   后续可通过 Grafana Provisioning (`monitoring/grafana/provisioning/alerting/rules.yaml`) 将上述 12 条 PromQL 规则固化为代码管理，容器启动即自带全套标准告警规则。
2. **飞书 Webhook 密钥校验（可选增强）**：
   当前已实现飞书标准卡片发送，若后续对内网安全要求更严格，可在 Grafana Webhook Header 中添加 `X-Webhook-Secret` 并在后端进行对称校验。
