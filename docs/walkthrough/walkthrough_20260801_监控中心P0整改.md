# 监控中心 P0 整改验收说明

## 本次已实现

监控中心不再把“设备在线状态、采集状态、健康状态、告警状态”混成一个数字：

- 设备可用性：在线、离线、未知。
- 采集完整性：健康、部分失败、失败、过期、未获知。
- 健康评估：只有存在近期遥测、接口数据或活动告警时才计算分数。
- 数据可信度：按 reachability、SNMP metrics、SNMP interfaces 的新鲜成功结果计算。
- 活动告警：接口返回完整的 critical、major、warning 数量，不再从首页只展示的 8 条告警反推总数。

没有近期健康数据的设备现在显示为“待评估”，健康分为 `null`；离线设备不会仅因离线而被强制计算成健康分 0。离线仍然在设备可用性维度单独统计。

## 数据库兼容

新增迁移 `m0060_monitoring_health_dimensions`，为 `device_health_samples` 增加健康分可用标记、可用性、采集状态和数据可信度字段。迁移使用项目数据库适配层支持的参数化 SQL，并在 PostgreSQL 与 SQLite 测试路径上保持幂等。

## 验证命令

```text
.venv\Scripts\python.exe -m pytest -q backend/tests/monitoring/test_device_health_dimensions.py
.venv\Scripts\python.exe -m pytest -q backend/tests/monitoring backend/tests/vendor_audit
npm run lint
npm run build
```

本次聚焦测试为 6 项通过，既有 vendor_audit 测试为 277 项通过，前端 lint 和生产构建通过。完整 `backend/tests` 在当前环境超过 240 秒仍未结束，因此未将其宣称为通过。

## 页面验收重点

1. 打开 `/monitor/telemetry`，观察四个核心卡片：设备可用性、健康评估、采集完整性、活动告警。
2. 对没有近期遥测的设备，确认风险列表显示 `--`，而不是 0。
3. 对离线但没有健康证据的设备，确认它只计入离线，不计入健康严重设备。
4. 活动告警卡片的严重、主要、一般数量应来自完整告警集合，而不是最近 8 条列表。
5. 核对监控中心仍停留在当前页面，不会因为健康分布卡片隐式跳转到 `/health`。
