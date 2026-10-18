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
- GitHub Actions 与目标机更新：待提交后执行。

## 未执行验证

- 尚未运行真实目标机上的 Docker Compose 检查和容器更新；先等 GitHub Actions。

## 剩余风险与建议

部署脚本改动尚未应用到目标机；需在发布仓库更新后运行 `update` 并检查告警 Redis 与应用健康状态。
