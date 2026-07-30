# Docker Compose 部署

适合 Linux 服务器 / 生产环境。一套 compose 拉起 PostgreSQL + 后端 + Nginx 三个容器，宿主机无需安装 Node.js / Python。

## 入口文件（仓库根目录）

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | 编排 PostgreSQL 17 + 后端 + Nginx |
| `Dockerfile` | 后端镜像构建（含前端容器内编译） |
| `.dockerignore` | 构建上下文忽略规则（必须在根目录才生效） |
| `nginx/` | Nginx 配置与 SSL 证书目录 |

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

## 常用命令

```bash
docker compose up -d --build     # 构建并启动
docker compose down              # 停止所有容器
docker compose logs -f netops    # 后端日志
docker compose logs -f nginx     # Nginx 日志
docker compose restart netops    # 重启后端
```

## 离线镜像部署

如果生产服务器无法访问镜像仓库，建议在一台可以联网的构建机上准备镜像，再把镜像归档文件和部署目录传到目标服务器。离线服务器不执行构建、不拉取镜像，只执行 `docker load` 和 Compose 启动。

### 1. 在联网构建机保存镜像

在已成功启动 Nexora 的部署目录执行：

```bash
bash scripts/deploy-docker.sh save-images /tmp/nexora-images-$(date +%Y%m%d-%H%M%S).tar.gz
```

该命令会保存以下镜像，并同时生成 `.sha256` 校验文件：

```text
nexora-netops:latest
nexora-nginx:latest
postgres:17-alpine
```

将以下文件以及部署目录中的 `docker-compose.yml`、`.env` 和 `nginx/ssl/` 传到离线服务器：

```text
nexora-images-*.tar.gz
nexora-images-*.tar.gz.sha256
```

### 2. 在离线服务器导入镜像

```bash
bash scripts/deploy-docker.sh load-images /data/packages/nexora-images-20260728.tar.gz
```

如果校验文件与镜像包位于同一目录，脚本会先验证 SHA-256，再执行 `docker load`。

### 3. 不构建、不拉取，直接启动

```bash
bash scripts/deploy-docker.sh start-offline
```

等价的原生命令为：

```bash
docker compose up -d --no-build --pull never --remove-orphans
```

离线启动前请确认三个镜像标签都已导入，并确认目标服务器与源构建机的 CPU 架构一致。

## 服务构成

| 容器 | 镜像 / 来源 | 端口 |
|------|-----------|------|
| `db` | `postgres:17-alpine` | 内部 5432 |
| `netops` | 本地 `Dockerfile` 构建 | 内部 8003 |
| `nginx` | `nginx:1.27-alpine` | 对外 80 / 443 |

> 生产环境的 HTTPS、密钥加固等见根目录 [DEPLOY.md](../../DEPLOY.md)。
