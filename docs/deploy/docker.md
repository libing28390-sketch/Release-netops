# Docker Compose 部署

适合 Linux 服务器 / 生产环境。一套 compose 拉起 PostgreSQL + 后端 + Nginx，脚本默认同时纳入 Redis sidecar，宿主机无需安装 Node.js / Python。

## 入口文件（仓库根目录）

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | 编排带 pgvector/pg_trgm 的 PostgreSQL 17 + 后端 + Nginx |
| `docker/postgres/Dockerfile` | 基于 pgvector 的 PostgreSQL 镜像（包含 pg_trgm） |
| `Dockerfile` | 后端镜像构建（含前端容器内编译） |
| `.dockerignore` | 构建上下文忽略规则（必须在根目录才生效） |
| `nginx/` | Nginx 配置与 SSL 证书目录 |

`docker-compose.redis.yml` 提供 Redis 7.4.2 Alpine sidecar。Redis 仅用于 IP 定位等可重建缓存，不能替代 PostgreSQL 的任务状态或事实数据。设置 `NETOPS_REDIS_ENABLED=0` 可显式关闭 sidecar。

数据库镜像固定基于 `pgvector/pgvector:0.8.6-pg17-bookworm`，并额外安装
`postgresql-contrib-17`，因此迁移 `0104_ai_pgvector_rag` 所需的 `vector` 和
`pg_trgm` 都能在数据库启动前使用。

> 这些文件**保持在根目录**，所以下面所有命令都直接在仓库根目录执行，无需 `-f` 指定路径。

## 步骤

1. 克隆仓库并准备环境文件：
   ```bash
   git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
   cd nexora-automation
   # 编辑 .env，至少替换 SECRET_KEY、CREDENTIAL_ENCRYPTION_KEY、POSTGRES_PASSWORD、DATABASE_URL
   ```
2. 构建并启动（前端会在容器内自动编译）：
   ```bash
   bash scripts/deploy-docker.sh install
   ```
3. 访问 `http://localhost`。

脚本默认会校验并启动 Redis；如果 `.env` 仍使用 sidecar 默认地址，首次安装会生成 URL-safe 的 Redis 密码并同步写入 `REDIS_PASSWORD`/`REDIS_URL`。已部署环境可以使用以下命令检查或查看 Redis：

```bash
bash scripts/deploy-docker.sh redis-status
bash scripts/deploy-docker.sh redis-logs
```

## 启用 Redis 缓存

将 `.env` 中的 `REDIS_URL` 保持为 Compose 网络内的服务名，并设置定位缓存开关：

```dotenv
REDIS_URL=redis://redis:6379/0
IP_LOCATOR_V2_ENABLED=1
IP_LOCATOR_CACHE_BACKEND=redis
```

通过部署脚本启动 Nexora 和 Redis（同一 Compose 网络内服务名为 `redis`）：

```bash
bash scripts/deploy-docker.sh update --force
```

设置 `REDIS_PASSWORD` 后，sidecar 会启用 Redis 密码认证；同步更新 `REDIS_URL`，并对密码中的特殊字符进行 URL 编码。独立部署时默认只绑定 `127.0.0.1`，需要跨主机访问时设置 `REDIS_BIND_ADDRESS=0.0.0.0`，并在 Redis 主机防火墙中只允许 Nexora 主机访问 6379。跨不可信网络使用 `rediss://` 和证书校验。

定位缓存 TTL 从原始 `collected_at` 计算：路由/ARP 300 秒新鲜、1800 秒保留；MAC/完整结果 120 秒新鲜、900 秒保留；网段 900 秒新鲜、86400 秒保留；拓扑 600 秒新鲜、86400 秒保留；正向未命中 15 秒。Redis 重启、淘汰或短时不可用都不会影响 PostgreSQL 事实；应用会报告降级并按任务队列重新建立缓存。

## 常用命令

```bash
bash scripts/deploy-docker.sh update
bash scripts/deploy-docker.sh redis-status
bash scripts/deploy-docker.sh redis-logs
```

## 完全离线部署

如果目标服务器无法访问 Docker Hub 或其他镜像仓库，请在联网机器上准备好镜像，然后只把镜像归档文件和部署文件传到目标服务器。`save-images` 不会重新构建镜像，也不会访问镜像仓库；它会保存当前本机已存在的 Nexora 镜像，并在 Redis sidecar 启用时一并保存 Redis 镜像。

### 1. 在联网构建机保存镜像

在已经构建好目标版本镜像的部署目录执行：

```bash
bash scripts/deploy-docker.sh save-images \
  ./nexora-images-$(date +%Y%m%d-%H%M%S).tar.gz
```

如果所需镜像已经存在于本机，也不需要先执行 `docker compose build`。脚本会先验证基础镜像和启用的 Redis 标签，再生成归档：

该命令会保存以下镜像，并同时生成 `.sha256` 校验文件：

```text
nexora-netops:latest
nexora-nginx:latest
nexora-postgres:latest
redis:7.4.2-alpine
```

镜像归档不会包含 Compose 文件、运行时环境变量、SSL 证书或数据库数据。请将以下内容传到离线服务器：

```text
nexora-images-*.tar.gz
nexora-images-*.tar.gz.sha256
docker-compose.yml
scripts/deploy-docker.sh
.env.example
nginx/nginx.conf
nginx/ssl/                 # 使用正式 HTTPS 证书时需要
```

不要直接分发包含生产密码和密钥的 `.env`；在目标服务器根据 `.env.example` 创建并填写自己的 `.env`。

### 2. 在离线服务器导入镜像

```bash
bash scripts/deploy-docker.sh load-images \
  /data/packages/nexora-images-20260728.tar.gz
```

如果校验文件与镜像包位于同一目录，脚本会先验证 SHA-256，再执行 `docker load`。导入不会删除或修改镜像归档文件。

### 3. 不构建、不拉取，直接启动

```bash
bash scripts/deploy-docker.sh start-offline
```

等价的原生命令为：

```bash
docker compose up -d --no-build --pull never --remove-orphans
```

离线启动前请确认所需镜像标签都已导入，并确认目标服务器与源构建机的 CPU 架构一致。

离线服务器不要执行 `docker compose up -d --build`、`docker compose pull` 或脚本的 `install`/`update` 命令；这些命令可能尝试构建或访问远程仓库。首次启动会创建新的 Docker volumes 并执行数据库迁移；如果需要迁移原有业务数据，请另外恢复 PostgreSQL 备份和数据卷。

## 服务构成

| 容器 | 镜像 / 来源 | 端口 |
|------|-----------|------|
| `db` | 本地 `docker/postgres/Dockerfile` 构建的 `nexora-postgres:latest`（pgvector + pg_trgm） | 内部 5432 |
| `netops` | 本地 `Dockerfile` 构建 | 内部 8003 |
| `nginx` | `nginx:1.27-alpine` | 对外 80 / 443 |
| `redis`（可选） | `redis:7.4.2-alpine`，由 `docker-compose.redis.yml` 提供 | 内部 6379 |

> 生产环境的 HTTPS、密钥加固等见根目录 [DEPLOY.md](../../DEPLOY.md)。
