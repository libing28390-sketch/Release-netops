# 通知 Relay 启动顺序走查

## 结论

启动时报错的直接原因是 `alert_delivery_outbox` 尚未包含 `alert_id` 列，而不是设备未导入。数据库迁移 m0245 会增加该列；在迁移完成前，Relay 的恢复查询会报 PostgreSQL `UndefinedColumn`，并按默认 0.5 秒周期反复重试。

设备尚未导入时，通知 outbox 为空是正常状态，不应阻止 Relay 启动或造成数据库列缺失错误。

## 调用与启动顺序

1. `netops` 主服务启动时同步执行 `init_db()` 和数据库迁移。
2. 迁移完成后，`netops` 的健康检查才会通过。
3. `alert-notify-relay` 等待 PostgreSQL、通知 Redis 和 `netops` 健康后启动。
4. Relay 扫描 outbox；队列为空时正常空转，有待发送记录时才处理通知。

Compose 的 `depends_on: condition: service_healthy` 控制容器启动顺序。它不会在 `netops` 后续运行异常时自动停止已经运行的 Relay。

## 修改内容

- `docker-compose.yml`：为 `alert-notify-relay` 增加对 `netops` 健康状态的启动依赖，使数据库迁移完成后再启动 Relay。
- 没有修改 Relay 业务代码、数据库迁移、通知轮询周期或设备导入流程。

## 验证

- 检查 Compose 依赖片段：新增的 `netops` 依赖位于 `alert-notify-relay` 服务下，条件为 `service_healthy`；`netops` 没有反向依赖 Relay。
- `git diff --check -- docker-compose.yml` 通过。
- 未运行测试或 Compose 部署，也未修改线上主机。当前改动要在线上生效，需要后续用更新后的 Compose 配置重建/重新部署 Relay。

## 影响范围

此修复消除启动期间数据库迁移与 Relay 查询之间的竞态。若迁移本身失败，Relay 会保持等待状态，直到 `netops` 健康；容器仍可通过 `docker ps` 查看其启动状态。
