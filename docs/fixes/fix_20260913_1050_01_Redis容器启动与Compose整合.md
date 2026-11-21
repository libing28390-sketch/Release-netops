# Redis 容器启动与 Compose 整合

## 问题现象

Docker Redis 容器启动后反复重启，日志仅输出 `0022`。Redis 服务原先单独定义在 `docker-compose.redis.yml`，部署还需要同时维护主 Compose、overlay、脚本和多处说明。

## 根因

Redis 的 `/bin/sh -ec` entrypoint 收到被拆分的多行 shell command，实际只执行了 `umask`，没有启动 Redis。单独 overlay 还定义了 `nexora-redis` Compose 项目名，导致其与主 Compose 项目身份容易不一致。

## 解决方案

- 把 Redis 服务、安全 ACL、健康检查和显式命名的数据卷合并进 `docker-compose.yml`。
- 把 shell 程序配置为单元素 `command` 列表，确保整段内容作为一个参数传给 shell。
- 删除 `docker-compose.redis.yml`，更新部署脚本、环境示例、Windows 和 Docker 部署文档。
- 保留默认启用 Redis 以及 `NETOPS_REDIS_ENABLED=0` 关闭 Redis 的脚本行为。
- 保留 `nexora-redis` 容器名和 `nexora-redis-data` 卷名，正常更新无需迁移数据。

## 实际修改文件

- `docker-compose.yml`
- 删除 `docker-compose.redis.yml`
- `scripts/deploy-docker.sh`
- `.env.example`
- `backend/tests/release/test_deploy_docker_redis_contract.py`
- `docs/deploy/README.md`
- `docs/deploy/docker.md`
- `docs/deploy/docker-release-manual.md`
- `docs/deploy/windows.md`
- `docs/plans/plan_20260913_1028_01_Redis容器启动参数.md`
- `docs/walkthrough/walkthrough_20260913_1028_01_Redis容器启动参数.md`

## 验证命令与结果

- `.venv\\Scripts\\python.exe -m pytest backend/tests/release/test_deploy_docker_redis_contract.py -q --disable-warnings`：`3 passed in 38.43s`。
- `C:\\Program Files\\Git\\bin\\bash.exe -n scripts/deploy-docker.sh`：通过。
- YAML 契约测试验证主 Compose 中 Redis command 是单元素列表，且保留容器名与显式数据卷。
- `git diff --check`：通过；Git 提示 Windows 工作区后续可能转换换行符。

## 未验证项

- 当前工作区没有 Docker CLI，未执行 `docker compose config` 或实际启动 Redis。
- 推送 `main` 后 GitHub Actions 会运行发布门禁；公有 Release 同步结果以工作流成功完成为准。

## 风险与回滚方式

现有 Redis 容器名和命名卷保持不变，常规更新不会删除 Redis 数据。若发布门禁或目标部署出现问题，可在私有仓库回退本次提交并重新推送；不要通过 `docker compose down -v` 回滚，以免删除数据库或 Redis 数据卷。
