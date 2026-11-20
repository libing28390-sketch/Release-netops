# Docker Compose 项目名兼容走查记录

## 完成摘要

- 修复健康运行的 `nexora-db` 因历史 Compose 项目标签不同而被更新脚本误判为未运行的问题。
- 项目名解析优先级调整为：shell `COMPOSE_PROJECT_NAME`、`.env` 配置、现有 `nexora-db` 的 Compose 项目标签、全新部署默认值 `nexora`。
- 保持发布前 PostgreSQL 强制备份，不通过跳过备份规避错误。
- Redis 与 PostgreSQL、应用、Nginx 继续由同一 Compose 项目和网络管理；Redis 只承担缓存，不替代 `nexora-db`。

## 实际修改文件

- `scripts/deploy-docker.sh`
- `backend/tests/release/test_deploy_docker_redis_contract.py`
- `docs/deploy/docker.md`
- `docs/plans/plan_20260913_0034_01_Docker项目名兼容.md`
- `docs/walkthrough/walkthrough_20260913_0034_01_Docker项目名兼容.md`

## 关键实现说明

`resolve_compose_project_name` 只在没有显式配置项目名时读取固定容器 `nexora-db` 的 `com.docker.compose.project` 标签。这样旧部署可以在原项目上下文中执行 `compose exec -T db pg_dump`，完成安全备份后再更新；没有旧容器的全新部署仍稳定使用 `nexora`。解析结果继续通过项目名字符白名单。

## 验证命令与结果

- `C:\Program Files\Git\bin\bash.exe -n scripts/deploy-docker.sh`：通过。
- 项目名优先级静态契约检查：通过。
- `.venv\Scripts\python.exe -m pytest backend/tests/release/test_deploy_docker_redis_contract.py backend/tests/release/test_redis_monitor_formatter.py -q`：6 passed。
- Redis MONITOR 北京时间样例验证：通过。
- Redis Compose YAML 解析及时区契约检查：通过。
- `git diff --check`：通过。

## 未执行验证及原因

- 未在用户生产主机执行 Docker 命令；本地环境没有 Docker CLI，无法复现生产容器标签和实际 `pg_dump`。
- 未运行前后端全量测试或构建：改动仅涉及部署脚本、Compose 环境和发布契约测试。

## 剩余风险与后续建议

- 用户主机首次重试前可用 `docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' nexora-db` 核对历史标签。
- 若主机当前仍运行尚未包含本修复的脚本，可把上述标签临时作为 `COMPOSE_PROJECT_NAME` 传入更新命令；更新到修复版本后脚本会自动识别。
- 回滚脚本修改不会改变现有容器或数据卷，但会重新暴露旧项目标签兼容问题。
