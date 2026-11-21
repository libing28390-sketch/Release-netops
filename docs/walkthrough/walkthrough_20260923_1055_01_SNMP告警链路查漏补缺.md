# SNMP 告警链路查漏补缺执行记录

## 完成摘要

已完成 `/alerts/desk`、告警规则服务、SNMP 健康/接口采集、生命周期状态机和通知分发链路的查漏补缺。本批将 Nexora 后端作为 SNMP 告警的唯一评估入口：采集器负责读取已发现/已应用的 OID，规则中心负责阈值和作用域，告警状态机负责 FOR、恢复、静默和维护窗口，durable outbox 负责异步下发。Grafana 保持展示用途，不需要重复配置同一组 SNMP 告警规则。

## 实际修改文件

- `backend/services/background_monitor_service.py`
- `backend/services/notification_service.py`
- `backend/api/users.py`
- `backend/api/alerts.py`
- `src/types.ts`
- `src/pages/alertManagementShared.ts`
- `src/pages/AlertDeskTab.tsx`
- `docs/plans/plan_20260923_1055_01_SNMP告警链路查漏补缺.md`

## 关键实现说明

### SNMP 告警评估

- 告警规则增加 15 秒以内的运行时刷新窗口；规则中心新增、修改、启停后，采集循环会自动重新读取，不需要重启服务。
- 数据库暂时不可用时保留上一份有效规则，避免一次连接抖动让所有告警规则失效。
- 风扇和电源状态统一接受模板采集器的 `True/False/None` 以及旧厂商采集器的文本状态。`False`、`fail`、`warning` 等异常值触发告警，`True`、`ok`、`normal` 等正常值恢复告警，未知值保持当前状态，不制造误报或误恢复。
- 现有 SNMP 指标仍沿用规则中心和告警状态机：CPU、内存、温度、风扇、电源、接口状态、接口利用率、接口错误率、接口震荡以及 SNMP 不可达均按对应规则执行。

### `/alerts/desk` 可观测性

- 告警 API 根据稳定的 dedupe key 返回 `metric_type` 和 `collector_source`，不改动历史表结构。
- 告警列表、详情和 Excel 导出会显示指标类型；详情会显示采集来源，便于确认告警是否来自 SNMP、SSH/CLI、ICMP/TCP 或系统采集。
- 原有确认、分派、备注、维护抑制、自动刷新和时间线行为保持不变。

### 飞书/API 通知通道

- SNMP 告警继续进入现有 `alert_delivery_outbox`，由调度任务异步投递，不在 SNMP 采集协程里直接等待外部 API。
- 用户在个人设置填写独立 webhook 时，自动告警优先使用该个人通道；个人配置是掩码或未配置时回退到全局通道；个人 `enabled` 开关继续生效。
- 用户资料接口现在也能正确回显个人通道的掩码信息，同时保留全局通道兼容性。
- 本批没有新增 SMTP/邮件发送，邮件属于后续独立通知通道任务。

## 验证命令与结果

- `python -m py_compile backend/services/background_monitor_service.py backend/services/notification_service.py backend/api/alerts.py backend/api/users.py`：通过。
- 纯逻辑回归脚本：确认风扇/电源 `False` 触发、`True` 恢复、未知值忽略；确认 dedupe key 能映射到 SNMP 指标和采集来源：通过。
- PostgreSQL 规则读取：当前启用规则 19 条，包含 CPU、内存、温度、风扇、电源、接口状态/利用率/错误率、接口震荡和 SNMP 不可达等 SNMP 指标：通过。
- `npm run lint`（`tsc --noEmit`）：通过。
- `npm run build`：通过，Vite 完成 4287 个模块构建。
- `git diff --check`：通过；仅提示现有前端文件的 LF/CRLF 工作树换行转换，不是代码错误。

## 未执行验证及原因

- 未执行真实设备 SNMP 轮询、Docker、vmagent、Grafana 联调；当前 Windows 环境没有 Docker，且本机没有可用于验证所有厂商硬件传感器的实机环境。
- 未发送真实飞书、钉钉或企业微信消息；验证只覆盖通道选择逻辑和静态构建，避免在本机误发外部通知。
- 未实现邮件发送；用户已要求当前先完成 SNMP 采集告警链路。

## 剩余风险与后续建议

- Docker 环境部署后仍需用至少一台真实设备验证 SNMP View、风扇/电源状态码、温度单位和接口计数器宽度。
- Grafana 如需独立告警必须明确作为外部告警源，并建立去重策略；在当前方案下不建议对同一 SNMP 指标重复配置 Grafana 告警。
- 后续增加邮件时，建议复用同一 outbox、重试和幂等键，新增 SMTP 配置与邮件通道，不改变 SNMP 规则评估逻辑。
