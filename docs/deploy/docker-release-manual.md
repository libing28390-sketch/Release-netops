# Nexora Docker 部署与离线交付手册

本文以当前仓库的 `docker-compose.yml` 和 `scripts/deploy-docker.sh` 为准，说明在线构建、镜像归档、完全离线部署、升级和故障排查流程。

## 1. 部署架构

| 服务 | 当前镜像标签 | 作用 | 对外端口 |
|---|---|---|---|
| `db` | `nexora-postgres:latest` | PostgreSQL 17、pgvector、pg_trgm | 不直接暴露 |
| `netops` | `nexora-netops:latest` | FastAPI 后端和前端静态资源 | 内部 8003 |
| `nginx` | `nexora-nginx:latest` | HTTPS、静态文件、API/WebSocket 代理 | 80、443 |

后端镜像已经包含 Python 依赖、系统运行库和前端构建产物。目标服务器不需要安装 Node.js、Python、pip 或 npm。

## 2. 镜像仓库地址预留

当前离线交付使用本地镜像标签，不依赖镜像仓库。后续如果接入私有仓库，预留地址如下：

```text
镜像仓库地址：<YOUR_IMAGE_REGISTRY>
项目命名空间：<YOUR_IMAGE_REGISTRY>/nexora
版本标签：    <VERSION>
```

例如：

```text
<YOUR_IMAGE_REGISTRY>/nexora/netops:<VERSION>
<YOUR_IMAGE_REGISTRY>/nexora/nginx:<VERSION>
<YOUR_IMAGE_REGISTRY>/nexora/postgres:<VERSION>
```

这些地址目前只是发布规划占位符；当前 Compose 和离线脚本仍使用 `nexora-*:latest` 本地标签。

## 3. 在线部署

### 3.1 准备环境

目标主机需要 Docker Engine 和 Docker Compose v2：

```bash
docker --version
docker compose version
```

### 3.2 获取代码和配置

```bash
git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
cd nexora-automation
cp .env.example .env
```

编辑 `.env`，至少设置：

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=替换为强密码
POSTGRES_DB=netops
SECRET_KEY=替换为随机密钥
CREDENTIAL_ENCRYPTION_KEY=替换为随机密钥
```

### 3.3 构建并启动

```bash
bash scripts/deploy-docker.sh install
```

等价原生命令：

```bash
docker compose build
docker compose up -d
```

检查状态：

```bash
docker compose ps
docker compose logs -f netops
```

## 4. 制作离线镜像包

### 4.1 当前镜像已经准备好

如果本机已经存在目标版本的三个镜像，不需要重新执行 `docker compose build`：

```bash
bash scripts/deploy-docker.sh save-images \
  ./nexora-images-$(date +%Y%m%d-%H%M%S).tar.gz
```

脚本会验证以下标签：

```text
nexora-netops:latest
nexora-nginx:latest
nexora-postgres:latest
```

然后生成镜像包和校验文件：

```text
nexora-images-YYYYMMDD-HHMMSS.tar.gz
nexora-images-YYYYMMDD-HHMMSS.tar.gz.sha256
```

`save-images` 只导出当前已有镜像，不会构建、拉取、删除或修改本机镜像。

### 4.2 代码或依赖发生变化

只有代码、Python 依赖、前端依赖或 Dockerfile 发生变化时，才需要先构建：

```bash
docker compose build
bash scripts/deploy-docker.sh save-images \
  ./nexora-images-$(date +%Y%m%d-%H%M%S).tar.gz
```

## 5. 完全离线部署

### 5.1 需要传输的文件

镜像包不包含 Compose 文件、运行时密钥、SSL 证书或数据库数据。请将以下文件传到离线服务器：

```text
nexora-images-*.tar.gz
nexora-images-*.tar.gz.sha256
docker-compose.yml
scripts/deploy-docker.sh
.env.example
nginx/nginx.conf
nginx/ssl/                 # 使用正式 HTTPS 证书时复制
```

不要直接分发联网机器的生产 `.env`，在离线服务器创建自己的配置：

```bash
cp .env.example .env
chmod 600 .env
```

### 5.2 导入镜像

在包含 `docker-compose.yml` 和脚本的目录执行：

```bash
bash scripts/deploy-docker.sh load-images \
  /data/nexora-automation/nexora-images-20260823-142221.tar.gz
```

如果 `.sha256` 与镜像包在同一目录，脚本会先校验，再执行 `docker load`：

```bash
docker images nexora-netops nexora-nginx nexora-postgres
```

### 5.3 仅使用本地镜像启动

```bash
bash scripts/deploy-docker.sh start-offline
```

该命令等价于：

```bash
docker compose up -d --no-build --pull never --remove-orphans
```

离线服务器不要执行以下命令：

```bash
docker compose pull
docker compose up -d --build
bash scripts/deploy-docker.sh install
bash scripts/deploy-docker.sh update
```

### 5.4 离线部署前检查

构建机和目标机必须使用相同 CPU 架构，例如都为 `linux/amd64`：

```bash
uname -m
docker version
docker compose version
```

同时确认 Docker 正常运行、80/443 端口可用、`.env` 中的密码和密钥已替换、正式证书已复制，以及目标磁盘空间充足。

## 6. 数据和持久化

镜像包不包含业务数据。Compose 使用以下 volumes：

```text
nexora-pgdata       PostgreSQL 数据
nexora-data         应用数据、许可证等
nexora-backup       配置备份
nexora-dist         前端静态文件共享卷
```

新服务器首次启动会创建数据库并执行迁移。如果需要迁移既有系统，必须另外恢复 PostgreSQL 备份和应用数据，不能只导入镜像包。

查看服务和日志：

```bash
docker compose ps
docker compose logs --tail=200 db
docker compose logs --tail=200 netops
docker compose logs --tail=200 nginx
```

## 7. 升级流程

### 在线升级

```bash
bash scripts/deploy-docker.sh update
```

### 离线升级

联网构建机生成新包：

```bash
bash scripts/deploy-docker.sh save-images ./nexora-images-v2.tar.gz
```

离线服务器导入并重启：

```bash
bash scripts/deploy-docker.sh load-images /data/packages/nexora-images-v2.tar.gz
bash scripts/deploy-docker.sh start-offline
```

使用相同 `latest` 标签导入新包会替换本地镜像标签，但不会删除 Docker volumes。升级前建议先执行项目的数据库和配置备份流程。

## 8. 常见问题

### `Required image is missing locally`

说明镜像没有成功导入，或标签不匹配：

```bash
bash scripts/deploy-docker.sh load-images /data/packages/nexora-images.tar.gz
docker images nexora-netops nexora-nginx nexora-postgres
```

### 离线启动仍尝试拉取镜像

请使用 `start-offline`，或手动指定 `--no-build --pull never`，不要使用普通的 `docker compose up -d`。

### `502 Bad Gateway`

检查后端和数据库：

```bash
docker compose ps
docker compose logs --tail=200 netops
```

### PostgreSQL 密码认证失败

修改 `.env` 中的密码不会修改已经初始化的 PostgreSQL volume。生产环境不要直接删除数据卷，应使用原密码或按数据库迁移流程处理。

### 端口冲突

```bash
ss -lntp | grep -E ':80|:443'
```

## 9. 最短离线命令清单

```bash
bash scripts/deploy-docker.sh load-images \
  /data/nexora-automation/nexora-images-20260823-142221.tar.gz
bash scripts/deploy-docker.sh start-offline
docker compose ps
```

