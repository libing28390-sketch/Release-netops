# Redis Compose 整合与启动参数验证记录

## 完成摘要

已将 Redis 服务从独立 overlay 合并到主 `docker-compose.yml`，并把多行启动脚本改为 `command` 的单元素列表，确保整段脚本作为 `/bin/sh -ec` 的唯一命令参数传入，避免容器只执行 `umask`、输出 `0022` 后退出重启。部署脚本仍默认启用 Redis，`NETOPS_REDIS_ENABLED=0` 时保留原三服务运行能力。

## 实际修改文件

- `docker-compose.yml`
- 删除 `docker-compose.redis.yml`
- `scripts/deploy-docker.sh`
- `.env.example`
- `backend/tests/release/test_deploy_docker_redis_contract.py`
- `docs/deploy/docker.md`
- `docs/deploy/docker-release-manual.md`
- `docs/deploy/windows.md`
- `docs/plans/plan_20260913_1028_01_Redis容器启动参数.md`

## 关键实现说明

- 将 Redis 服务、ACL、安全配置、健康检查、日志配置和 `nexora-redis-data` 显式命名卷迁入主 Compose。
- 保留 `/bin/sh`、`-ec` entrypoint。
- 将普通多行 `command` 标量改为仅含一个块字符串的列表，显式采用 exec-form argv 语义。
- 部署脚本仅加载主 Compose；默认将 Redis 加入启动服务集，显式禁用时会停止既有 Redis 容器。
- 增加契约测试，解析主 YAML 并锁定 Redis 服务、卷和 `command -> list item -> umask 077` 结构。
- Redis 镜像继续固定为 `redis:7.4.2-alpine`；本次启动故障与镜像版本无关，不在同一修复中引入版本升级。

## 验证命令与结果

1. `.venv\\Scripts\\python.exe -m pytest backend/tests/release/test_deploy_docker_redis_contract.py -q --disable-warnings`
   - 结果：`3 passed in 38.43s`，退出码 0。
2. 使用 PyYAML 解析 `docker-compose.yml`，断言 Redis entrypoint 为两个元素、command 为一个元素、ACL/healthcheck 和持久卷存在。
   - 结果：`redis command argv contract: PASS`。
3. `C:\\Program Files\\Git\\bin\\bash.exe -n scripts/deploy-docker.sh`
   - 结果：`bash syntax: PASS`。
4. `git diff --check` 检查本次修改的 Compose、脚本、测试与文档。
   - 结果：通过；仅报告 Windows 工作区后续可能转换 CRLF 的提示。

## 未执行验证及原因

- 未在本机执行 `docker compose config` 或启动 Redis：当前 Windows 工作区没有 Docker CLI/runtime。
- 需要将变更同步到公有 Release 仓库后，在部署机运行 `bash scripts/deploy-docker.sh update`，再检查 Redis health/log 作为最终运行态验证。

## 剩余风险/后续建议

- Redis 继续使用 `redis:7.4.2-alpine` 固定标签；若需升级应选择明确的固定补丁版本，单独验证 ACL、持久化数据和回滚。
- 显式命名卷 `nexora-redis-data` 已保留，正常更新不会丢失 Redis 数据；不要用 `down -v` 作为常规升级步骤。
