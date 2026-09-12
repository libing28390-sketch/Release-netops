# Redis 容器时区补全走查记录

## 完成摘要

- 为独立 Redis Compose sidecar 注入 `TZ=${TZ:-Asia/Shanghai}`，与 PostgreSQL、Nexora、Nginx 及 `.env.example` 使用同一时区契约。
- 保留 `docker-compose.redis.yml` 独立文件：它可用于 Windows/本机原生 Nexora 场景下的 Redis-only 部署；Docker 全栈部署仍由 `scripts/deploy-docker.sh` 自动把主 Compose 与 Redis Compose 合并为同一项目管理。
- Docker 部署文档明确记录独立/合并两种用法和默认时区。
- Redis `MONITOR` 的协议时间戳仍为 Unix epoch；已有格式化脚本继续负责查看时转换，不修改 Redis 协议输出。
- 未执行 Git 提交、推送或实际部署。

## 实际修改文件

- `docker-compose.redis.yml`
- `docs/deploy/docker.md`
- `docs/plans/plan_20260913_0030_01_Redis容器时区补全.md`
- `docs/walkthrough/walkthrough_20260913_0030_01_Redis容器时区补全.md`

## 关键实现说明

Redis 服务的 `environment` 现同时传入：

- `TZ=${TZ:-Asia/Shanghai}`：复用根目录 `.env` 的 `TZ`，未配置时默认北京时间。
- `REDIS_PASSWORD=${REDIS_PASSWORD:-}`：原有 ACL 密码行为保持不变。

没有把 Redis 服务并入 `docker-compose.yml`。原因是主文件包含 PostgreSQL、应用密钥等必填插值，Redis-only 操作若依赖主文件，会被与 Redis 无关的全栈变量约束；保留 sidecar 文件能让两种部署边界清晰。全栈脚本已通过 `COMPOSE_FILES=(-f docker-compose.yml)` 和 `COMPOSE_FILES+=(-f docker-compose.redis.yml)` 自动合并，对操作人员仍是一条命令。

## 验证命令与结果

1. PyYAML 解析 `docker-compose.yml` 与 `docker-compose.redis.yml`，并断言 Redis 与三个主服务的时区契约：通过。
2. 静态断言 `scripts/deploy-docker.sh` 默认加入主 Compose 和 Redis Compose，且保留 `NETOPS_REDIS_ENABLED` 开关：通过。
3. `1789210633.197223 ... "PING" | python scripts/format_redis_monitor.py --timezone=Asia/Shanghai`：通过，输出 `2026-09-12 18:57:13.197223+08:00 ... "PING"`。
4. `git diff --check -- docker-compose.redis.yml docs/deploy/docker.md ...`：通过，未发现空白错误。
5. 最终作用域文件检查与工作树检查：通过；未覆盖工作区中原有的无关修改。

## 未执行验证及原因

- 未运行 `docker compose config` 或启动 Redis 容器：当前 Windows 环境未安装可调用的 Docker CLI。
- 未运行 `bash -n scripts/deploy-docker.sh`：当前 `bash`/WSL 运行时返回实例创建错误；本次未修改该脚本，并已静态核对其 Compose 文件组合逻辑。
- 未运行前后端测试、lint 或 build：此次仅修改 Compose 环境变量和部署说明，不影响应用代码或前端构建产物。

## 剩余风险与后续建议

- 交付前或目标 Docker 主机上应补跑：
  - `docker compose -f docker-compose.redis.yml config`
  - `docker compose -f docker-compose.yml -f docker-compose.redis.yml config`
  - `docker compose -f docker-compose.redis.yml up -d` 后执行 `docker exec nexora-redis date`，确认目标主机自定义 `TZ` 的实际显示。
- 回滚只需移除 Redis 服务的 `TZ` 项并还原对应文档句子，不涉及 Redis 数据卷。
