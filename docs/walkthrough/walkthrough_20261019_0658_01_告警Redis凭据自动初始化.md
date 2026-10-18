# 告警 Redis 凭据自动初始化走查

## 完成摘要

部署脚本会在告警 Redis broker 口令缺失或为空时自动生成唯一的 URL-safe 凭据，避免新建 `.env` 后 Compose 校验失败。既有非空口令不会覆盖。

## 实际修改文件

- `scripts/deploy-docker.sh`
- `.env.example`
- `docker-compose.yml`
- `docs/plans/plan_20261019_0658_01_告警Redis凭据自动初始化.md`
- `docs/fixes/fix_20261019_0658_01_告警Redis凭据自动初始化.md`

## 关键实现

- 生成值为 `nexora` 前缀加 24 字节随机十六进制后缀；值不会写入日志。
- 初始化变更名沿用既有 `ENV_INITIALIZED_KEYS` 报告。
- Compose 缺值提示提供安装/更新命令。

## 验证命令与结果

- `bash -n scripts/deploy-docker.sh`：通过。
- `python -c "import yaml; yaml.safe_load(open('docker-compose.yml', encoding='utf-8'))"`：通过。
- `git diff --check`：通过。
- GitHub Actions #742（`3c4b75df`）：成功；Ubuntu/Linux job 通过，Windows Agent 按流程跳过。
- 目标机发布树：`HEAD` 与 `origin/main` 均为 `b3f55fc`。
- `bash scripts/deploy-docker.sh update --force`：完成，输出 Docker update complete；部署脚本中的 `docker compose config --quiet` 未报错。
- 18 个容器均为 running；11 个 healthcheck 容器均为 healthy。
- `curl -kfsS --max-time 10 https://127.0.0.1/api/health/live` 返回 `{"status":"alive"}`。
- 容器内 `_probe_local_collector_runtime()` 返回 `ONLINE`，vmagent 和 snmp_exporter 均 `ONLINE`。
- 浏览器采集器页加载为 v1.0.10，显示本地采集器在线；状态检查提示两个运行组件均有响应。
- 本次 `.env` 中 broker 口令非空，初始化脚本保留现值，未读取或打印其值。部署备份位于 `.env.backup.20261019072239` 和 `../netops-release-backups/release-20261019-072239/`。

## 未执行验证

- 没有读取 broker 口令本身；验证只确认 Compose 校验通过、值存在且告警 Redis 健康。

## 剩余风险与建议

新建或空值 `.env` 会由部署脚本生成每部署唯一的 `nexora` 前缀随机口令；直接运行 Compose 的操作者仍需自行设置唯一值。目标机已保留原有非空值，并通过完整更新验收。
