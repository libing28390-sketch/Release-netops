---
name: "observability-engineer"
description: "Designs monitoring, metrics, logging, and alerting for Nexora. Invoke when building observability pipelines, dashboards, or reliability visibility features."
---

# Observability Engineer Skill

你负责 Nexora 的监控、日志、告警和可观测性体系设计。

---

## 日志系统 — `core/logging.py`

- **setup_logging()** 在应用启动时调用，配置统一日志格式。
- **Handler**：`TimedRotatingFileHandler`，按天轮转，保留 30 天。
- **日志路径**：`data/logs/netops.log`。
- **脱敏过滤**：`SanitizeFilter` 自动替换日志中的 password/secret/token/community 关键字为 `***`。
- **格式**：`%(asctime)s - %(name)s - %(levelname)s - %(message)s`。

## 审计事件 — `services/audit_service.py`

- `log_audit_event(db, username, action, resource_type, resource_id, details)` 记录关键操作。
- 审计覆盖：设备增删改、配置变更、自动化执行、用户登录、权限变更。
- 审计日志存入数据库 `audit_events` 表，支持前端查询和导出。

## 设备健康标注 — `services/device_health_service.py`

- `annotate_devices_with_health(devices)` 为设备列表附加实时健康信息。
- 健康指标：CPU、Memory、Temperature、Uptime、接口 Up/Down 数量。
- 健康状态分级：`healthy` / `warning` / `critical`。

## 监控端点 — `api/monitoring.py` & `api/device_health.py`

- `GET /api/monitoring/metrics` — 全局指标汇总。
- `GET /api/device-health/{id}` — 单设备健康详情。
- `GET /api/monitoring/trends` — 历史趋势数据。

## 告警系统 — `api/alerts.py` & `services/alert_rule_service.py`

- 告警规则定义：指标阈值 + 触发条件 + 通知方式。
- 告警状态流转：`active` → `acknowledged` → `resolved`。
- 维护窗口：`services/alert_maintenance_service.py` 支持预设维护时段内静默告警。
- 批量操作：支持批量确认、批量解决、批量删除。

## 前端监控中心 — `components/MonitoringCenter.tsx`

- 实时仪表盘：设备状态分布、告警趋势、自动化成功率。
- 图表使用 Recharts 渲染。
- 支持时间范围筛选和自动刷新。

## 扩展指南

- **新增监控指标**：在 `snmp_service.py` 添加采集 → `device_health_service.py` 添加计算 → `monitoring.py` 暴露 API。
- **新增告警规则类型**：在 `alert_rule_service.py` 的评估逻辑中添加条件分支。
- **通知渠道扩展**：`notification_service.py` 支持新增通知方式（目前支持邮件和 Webhook）。
