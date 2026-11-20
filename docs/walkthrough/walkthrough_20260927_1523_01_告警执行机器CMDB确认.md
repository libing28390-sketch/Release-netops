# 告警规则执行机器和通知方式优化

## 变更摘要

- 告警规则中的“作用范围”改为“执行机器”。选择“指定设备”后，可按设备名、管理 IP、序列号或资产标签搜索当前租户 CMDB；回车后展示候选设备，勾选后才作为已确认目标保存。
- 设备目标以稳定设备 ID 写入原有 `scope_value`。创建和更新时后端再次校验这些 ID 属于当前租户，运行时按 ID 精确匹配。全局范围不显示设备匹配清单；旧 IP 规则仍可查看、保存并按原行为运行。
- 移除规则编辑区的“采集说明”。
- 网络告警规则及历史快照中的旧通知渠道统一为当前支持的 Webhook/邮件语义，页面不再显示“系统默认（旧规则）”。后续审核确认宿主机规则只用于平台健康状态，不进入通知投递链路；该历史描述已在新 walkthrough 中更正。

## 关键文件

- `src/pages/AlertRulesTab.tsx`：设备搜索、候选选择、已确认机器、全局状态和范围摘要 UI。
- `src/pages/alertManagementShared.ts`、`src/types.ts`：范围与通知渠道类型、归一化及辅助逻辑。
- `backend/api/alerts.py`：范围目录搜索/设备回查参数及请求处理。
- `backend/services/alert_rule_service.py`：当前租户设备目录、写入校验、范围匹配和历史渠道读取归一化。
- `backend/database/migrations/m0259_normalize_alert_rule_notifications.py`：存量规则和非宿主机历史快照的幂等渠道归一化。
- 对应前端、设备范围、租户隔离和迁移测试位于 `src/pages/alertManagementShared.test.ts` 与 `backend/tests/monitoring/`。

## 旧通知方式映射

| 存量网络规则渠道 | 当前规则渠道 |
| --- | --- |
| `workspace` | Webhook + 邮件 |
| 仅有已不支持渠道（如钉钉、企业微信、旧全局 Webhook） | Webhook + 邮件 |
| 已有 Webhook/邮件并混有已不支持渠道 | 只保留原有的 Webhook/邮件 |
| 宿主机阈值规则 `workspace` | 保留内部兼容值；页面说明仅用于健康状态 |

前端和服务读取时都对旧数据执行兼容归一化；m0259 进一步把网络告警规则和非宿主机历史快照写成当前形式。旧 `workspace` 跟随个人偏好的具体投递语义不能从归一化后的记录恢复，回滚时应从迁移前数据库备份恢复。

## 验证结果

- `npm run test:frontend -- src/pages/alertManagementShared.test.ts --run`：14 passed。
- `npm run lint`：通过。
- Vite production build，输出到系统临时目录：通过（4296 modules）。
- 定向 PostgreSQL 后端回归首轮：52 passed、2 failed。失败原因是测试直接调用 FastAPI handler 时未显式传入的 `Query` 默认对象被误作搜索词。修复 handler 参数归一化后，两个失败用例单独重跑：2 passed；没有把首轮和重跑结果描述成一次 54 项全通过。
- Python compileall：通过。
- `scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过；仅输出几个仓库已有文件的行尾格式提示。
- 未执行手工浏览器联调；连接中的浏览器环境并非本工作区部署。未部署，也未对用户运行环境执行 m0259。

## 发布注意

m0259 会永久规范化存量网络规则和历史快照。正式应用前先按项目备份要求建立数据库恢复点；代码回滚不会自动恢复原有 `workspace`/个人偏好语义。
