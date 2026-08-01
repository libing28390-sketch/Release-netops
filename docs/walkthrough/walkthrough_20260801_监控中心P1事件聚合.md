# 监控中心 P1：事件聚合与站点展示验收说明

## 本次完成

本次将监控中心从“告警数量展示”推进到“事件队列 + 原始告警时间线”的最小闭环：

- `monitoring_incidents` 保存当前事件投影，`monitoring_incident_alerts` 保存事件与原始告警的关联；
- 同一设备的 Ping、SNMP、SSH、探测失败会聚合为同一个连通性事件，接口中断、容量和其他业务告警保持独立；
- 首页新增“活跃事件与处置”区域，展示事件严重级别、状态、站点、设备数和告警数；
- 点击事件可查看事件摘要和原始告警时间线，并可进入设备详情或告警中心；
- 事件列表、详情、确认/调查、分派和关闭接口已加入监控 API，并保留操作审计入口；
- 站点显示优先使用 `devices.site_id -> sites.site_name` 的用户填写名称。历史记录只有系统 ID 且无法解析时显示为空，不再把 `site-xxxx` 当作站点名称展示。

## 数据与 PostgreSQL 兼容性

新增迁移：`backend/database/migrations/m0061_monitoring_incidents.py`。

迁移使用 `CREATE TABLE IF NOT EXISTS`、普通复合主键和 `ON CONFLICT`，不使用 SQLite 专属函数；项目迁移入口会按 `VERSION` 自动发现并执行。事件聚合服务仍使用项目数据库适配层的 `?` 参数占位符，由 PostgreSQL 适配器转换为 `%s`。

## 主要接口

```text
GET  /api/monitoring/incidents
GET  /api/monitoring/incidents/{incident_id}
POST /api/monitoring/incidents/{incident_id}/acknowledge
POST /api/monitoring/incidents/{incident_id}/assign
POST /api/monitoring/incidents/{incident_id}/resolve
```

## 验收步骤

1. 打开 `/monitor/telemetry`，确认“活跃事件与处置”区域显示事件卡片；
2. 确认卡片中的站点显示用户在站点管理中填写的 `site_name`，而不是 `site-xxxx`；
3. 点击一个事件，确认弹窗显示事件编号、严重级别、状态、影响设备、关联告警和原始时间线；
4. 点击“查看设备”确认仍停留在监控中心内完成设备下钻，不会隐式跳转健康页；
5. 对一个事件执行确认、调查、分派或关闭后，刷新页面确认状态与关联告警一致；
6. 对同一设备制造 Ping/SNMP/SSH 多条连通性告警，确认首页只显示一个事件，详情仍保留多条原始告警；
7. 对接口中断和连通性告警同时验证，确认二者不会被错误合并。

## 处置闭环

事件详情中的处置操作已经接入后端：

- “确认”将事件和关联告警置为 `acknowledged`；
- “调查中”将事件和关联告警置为 `investigating`；
- “分派”写入事件负责人并同步关联告警负责人；
- “关闭事件”经过二次确认后，将事件和关联告警置为 `resolved`；
- 审计操作者始终取自当前登录会话，前端不能伪造操作者身份；
- mutation 成功后刷新事件队列和监控概览，失败时保留详情上下文并显示后端错误。

## 自动化验证

```text
.venv\\Scripts\\python.exe -m pytest -q backend/tests/monitoring backend/tests/vendor_audit
# 280 passed

npm run lint
npm run build
git diff --check
```

构建仍可能提示已有的大体积 bundle warning，但 TypeScript 检查和 Vite 生产构建均成功。
