# PostgreSQL 监控账号日志脱敏

## 完成摘要

定位并抑制了 PostgreSQL exporter 账号初始化 SQL 的明文回显。Docker 部署路径和 PostgreSQL 新数据卷初始化路径现在都丢弃 psql 成功输出，并将通知级别设为 `warning`；部署脚本不再输出冗余的账号准备提示。SQL 执行失败仍会通过 stderr 和非零状态暴露。

## 实际修改文件

- `scripts/deploy-docker.sh`
- `docker/postgres/21-postgres-exporter-role.sh`
- `docs/plans/plan_20261011_1101_01_PostgreSQL监控账号日志脱敏.md`
- `docs/walkthrough/walkthrough_20261011_1101_01_PostgreSQL监控账号日志脱敏.md`

## 关键实现说明

- 根因是 `SELECT format(...PASSWORD...)` 与 psql `\gexec` 的组合：格式化出的完整 `ALTER ROLE` 语句先作为查询结果输出，随后才执行。
- 两个脚本都将 psql 标准输出重定向到 `/dev/null`，防止生成的 SQL、密码和成功命令标签进入 Docker 部署日志。
- `SET client_min_messages = warning` 抑制扩展已存在、角色已授权等 NOTICE。
- 保留已有数据卷上的密码对齐、`ON_ERROR_STOP` 和原有服务顺序。后置对齐仍是兼容持久化数据卷的必要步骤。

## 验证命令与结果

- 阅读并对照两条 SQL 执行路径和 Compose 启动调用顺序；静态检查确认 psql stdout 被丢弃、stderr/退出状态未重定向。
- 未运行自动化测试或 Docker 部署；当前请求是日志与流程分析，且没有要求执行测试或部署。

## 未验证项与剩余风险

- 如果已有数据卷中的 exporter 密码与 `.env` 不一致，Compose 会先启动 exporter/vmagent，再运行密码对齐；这会产生短暂的认证失败/采集空档，后续抓取可在角色更新后恢复。此次仅修复日志泄露，没有重排服务启动。
- 用户贴出的日志含有明文 `POSTGRES_EXPORTER_PASSWORD`。应将该密码视为已暴露，在目标部署 `.env` 中轮换后重新部署；本次没有访问或修改真实 `.env`、数据库或容器。
- 回滚只需恢复两处 psql 标准输出和部署进度日志；没有数据库迁移或数据卷变更。
