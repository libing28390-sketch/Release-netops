# NetOps Automation — Deployment Guide / 部署指南

[English](#english) | [中文](#中文)

> For full system requirements (OS, software, hardware, network), see [README.md — System Requirements](README.md#system-requirements--系统要求).
>
> 完整系统要求（操作系统、软件、硬件、网络）请参阅 [README.md — 系统要求](README.md#system-requirements--系统要求)。

**Supported OS quick reference / 支持的操作系统速查：**
- ✅ Ubuntu 20.04 / 22.04 / 24.04 (x86_64)
- ✅ Debian 11 / 12 (x86_64)
- ✅ RHEL / Rocky Linux / AlmaLinux 8.x, 9.x (x86_64)
- ✅ CentOS Stream 8, 9 (x86_64)
- ✅ Docker (any host OS, x86_64)
- ❌ CentOS 7.x — glibc 2.17, not supported
- ❌ ARM64 / Windows / macOS native — not supported

---

## English

### Architecture Overview

```
User Browser
    │
    ▼
Nginx (:80)
    ├── /assets/*  →  dist/ static files (365-day cache)
    ├── /api/*     →  reverse proxy → FastAPI (:8003)
    ├── /api/ws/*  →  WebSocket proxy → FastAPI (:8003)
    └── /*         →  SPA fallback → index.html
```

| Component | Stack | Port |
|-----------|-------|------|
| Frontend  | React 19 + Vite (built to dist/) | served by Nginx |
| Backend   | Python FastAPI + Uvicorn | 8003 (internal) |
| Database  | PostgreSQL 17 | 5432 |
| Proxy     | Nginx | 80 (public) |

---

### Option A — Ubuntu One-Click Deploy

The recommended path for bare-metal servers, VMs, and container environments (GitHub Codespaces, Docker).

The script auto-detects whether `systemd` is available and falls back to `service` + background process in containers.

#### Fresh server (nothing pre-installed)

```bash
# Recommended: download first, then execute
curl -fsSL -o /tmp/deploy.sh https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh
chmod +x /tmp/deploy.sh
bash /tmp/deploy.sh
```

Or pipe directly (also supported):
```bash
curl -fsSL https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh | bash
```

#### Inside a cloned directory

```bash
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

#### What the script does

1. Installs system packages: Python 3, Node.js 22, Nginx, PostgreSQL, libcap2-bin
2. Creates a Python virtual environment and installs `backend/requirements.txt`
3. Installs Node.js dependencies and builds the frontend (`dist/`)
4. Generates `.env` from `.env.example` with random `SECRET_KEY` and `CREDENTIAL_ENCRYPTION_KEY`
5. Creates PostgreSQL user `netops` and database `netops` with a random password
6. Sets `CAP_NET_RAW` on the venv Python binary (for ICMP ping)
7. Writes and enables an Nginx reverse proxy config on port 80
8. **systemd environments**: registers and starts a `netops.service` unit
9. **Container environments**: starts the backend with `nohup` and writes PID to `data/netops.pid`

#### After deployment

| Item | Value |
|------|-------|
| Access URL | `http://<server-ip>` |
| Default credentials | `admin / admin` |
| Backend port | 8003 (internal, not exposed) |
| Nginx port | 80 |
| Backend logs (systemd) | `sudo journalctl -u netops -f` |
| Backend logs (container) | `tail -f data/netops.log` |

**Change the default password immediately after first login.**

#### Service management

```bash
# systemd
sudo systemctl status netops
sudo systemctl restart netops
sudo systemctl stop netops
sudo journalctl -u netops -f

# Container / Codespaces
tail -f data/netops.log
kill $(cat data/netops.pid)          # stop
bash deploy-ubuntu.sh                # restart

# Nginx (both environments)
sudo nginx -t && sudo nginx -s reload
sudo tail -f /var/log/nginx/error.log
```

---

### Option B — Docker Compose

Runs PostgreSQL, backend, and Nginx as a single stack. No host-level dependencies needed beyond Docker.

#### Prerequisites

```bash
# Install Docker (if not already installed)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker   # or re-login
```

#### Start

```bash
git clone https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation

# Build frontend first (required — Dockerfile copies dist/)
npm install && npm run build

# Start all containers
docker compose up -d --build
```

Access at `http://localhost`.

#### Environment variables

Create a `.env` file before starting:

```env
# Database
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-this-password
POSTGRES_DB=netops

# Security — generate random values for production
SECRET_KEY=replace-with-a-very-secret-key
CREDENTIAL_ENCRYPTION_KEY=replace-with-a-32-char-random-key

# License
MACHINE_ID_OVERRIDE=YOUR-MACHINE-ID   # required for non-trial licenses
LICENSE_FILE_PATH=/app/data/license.json

# Optional
CORS_ORIGINS=https://netops.example.com
PLATFORM_URL=https://netops.example.com
ALERT_NOTIFY_WEBHOOK_URL=
```

Get your Machine ID: `http://<server>/api/license/machine-id`

#### Common commands

```bash
docker compose up -d --build     # Build and start
docker compose down              # Stop all containers
docker compose ps                # Container status
docker compose logs -f netops    # Backend logs
docker compose logs -f nginx     # Nginx logs
docker compose restart netops    # Restart backend only
```

#### Custom domain

Edit `nginx/nginx.conf`, change `server_name _` to your domain:

```nginx
server_name netops.example.com;
```

#### HTTPS / SSL

1. Place certificates in `nginx/ssl/`
2. Uncomment the SSL volume in `docker-compose.yml`
3. Add SSL server block to `nginx/nginx.conf`

---

### Option C — Manual Setup

For custom environments or development.

**Prerequisites:** Node.js 18+, Python 3.10+, PostgreSQL 17

```bash
# 1. Clone
git clone https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation

# 2. Python environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

# 3. Frontend
npm install
npm run build

# 4. PostgreSQL
sudo -u postgres psql -c "CREATE USER netops WITH PASSWORD 'your-password';"
sudo -u postgres psql -c "CREATE DATABASE netops OWNER netops;"

# 5. Environment
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, CREDENTIAL_ENCRYPTION_KEY

# 6. CAP_NET_RAW (Linux, for ICMP ping)
sudo setcap cap_net_raw+ep $(readlink -f .venv/bin/python)

# 7. Start
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8003 --workers 2
```

---

### License Setup

1. Obtain `license.json` from the vendor
2. Place at `data/license.json`, or upload via **Settings → License** in the UI
3. The platform validates on startup — check logs for `[License] [OK]`

For Docker: mount the file or copy it into the `netops-data` volume:

```bash
docker cp license.json netops-automation:/app/data/license.json
docker compose restart netops
```

---

### Upgrading

```bash
# Ubuntu systemd
cd /opt/netops-automation
git pull
npm install && npm run build
pip install -r backend/requirements.txt
sudo systemctl restart netops

# Docker
git pull
npm install && npm run build
docker compose up -d --build
```

---

## 中文

### 架构说明

```
用户浏览器
    │
    ▼
Nginx (:80)
    ├── /assets/*  →  dist/ 静态文件（365 天缓存）
    ├── /api/*     →  反向代理 → FastAPI (:8003)
    ├── /api/ws/*  →  WebSocket 代理 → FastAPI (:8003)
    └── /*         →  SPA 回退 → index.html
```

| 组件 | 技术栈 | 端口 |
|------|--------|------|
| 前端 | React 19 + Vite（构建到 dist/） | 由 Nginx 提供 |
| 后端 | Python FastAPI + Uvicorn | 8003（内部） |
| 数据库 | PostgreSQL 17 | 5432 |
| 代理 | Nginx | 80（对外） |

---

### 方式 A — Ubuntu 一键部署

适用于裸机服务器、虚拟机及容器环境（GitHub Codespaces、Docker）。

脚本自动检测是否有 `systemd`，容器环境自动切换为 `service` 命令 + 后台进程模式。

#### 全新服务器（无需预装任何依赖）

```bash
# 推荐：先下载再执行，避免管道模式下的 stdin 问题
curl -fsSL -o /tmp/deploy.sh https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh
chmod +x /tmp/deploy.sh
bash /tmp/deploy.sh
```

也支持管道方式：
```bash
curl -fsSL https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh | bash
```

#### 已克隆项目目录内执行

```bash
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

#### 脚本自动完成的步骤

1. 安装系统包：Python 3、Node.js 22、Nginx、PostgreSQL、libcap2-bin
2. 创建 Python 虚拟环境并安装 `backend/requirements.txt`
3. 安装 Node.js 依赖并构建前端（`dist/`）
4. 从 `.env.example` 生成 `.env`，随机生成 `SECRET_KEY` 和 `CREDENTIAL_ENCRYPTION_KEY`
5. 创建 PostgreSQL 用户 `netops` 和数据库 `netops`，随机生成密码
6. 为虚拟环境 Python 设置 `CAP_NET_RAW`（用于 ICMP ping）
7. 写入并启用 Nginx 反向代理配置（监听 80 端口）
8. **systemd 环境**：注册并启动 `netops.service` 系统服务
9. **容器环境**：以 `nohup` 后台方式启动后端，PID 写入 `data/netops.pid`

#### 部署完成后

| 项目 | 值 |
|------|-----|
| 访问地址 | `http://<服务器IP>` |
| 默认账号 | `admin / admin` |
| 后端端口 | 8003（内部，不对外暴露） |
| Nginx 端口 | 80 |
| 后端日志（systemd） | `sudo journalctl -u netops -f` |
| 后端日志（容器） | `tail -f data/netops.log` |

**首次登录后请立即修改默认密码。**

#### 服务管理命令

```bash
# systemd 环境
sudo systemctl status netops
sudo systemctl restart netops
sudo systemctl stop netops
sudo journalctl -u netops -f

# 容器 / Codespaces 环境
tail -f data/netops.log
kill $(cat data/netops.pid)          # 停止
bash deploy-ubuntu.sh                # 重启

# Nginx（两种环境通用）
sudo nginx -t && sudo nginx -s reload
sudo tail -f /var/log/nginx/error.log
```

---

### 方式 B — Docker Compose 部署

PostgreSQL、后端、Nginx 三个容器一键启动，宿主机只需安装 Docker。

#### 安装 Docker（如未安装）

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker   # 或重新登录
```

#### 启动

```bash
git clone https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation

# 先构建前端（必须，Dockerfile 会复制 dist/）
npm install && npm run build

# 启动所有容器
docker compose up -d --build
```

访问地址：`http://localhost`

#### 环境变量配置

启动前创建 `.env` 文件：

```env
# 数据库
POSTGRES_USER=postgres
POSTGRES_PASSWORD=修改为安全密码
POSTGRES_DB=netops

# 安全密钥（生产环境必须修改为随机值）
SECRET_KEY=替换为随机密钥
CREDENTIAL_ENCRYPTION_KEY=替换为32位随机密钥

# License
MACHINE_ID_OVERRIDE=你的机器ID   # 非试用版 License 必填
LICENSE_FILE_PATH=/app/data/license.json

# 可选
CORS_ORIGINS=https://netops.example.com
PLATFORM_URL=https://netops.example.com
ALERT_NOTIFY_WEBHOOK_URL=
```

机器 ID 获取：访问 `http://<服务器>/api/license/machine-id`

#### 常用命令

```bash
docker compose up -d --build     # 构建并启动
docker compose down              # 停止所有容器
docker compose ps                # 查看容器状态
docker compose logs -f netops    # 查看后端日志
docker compose logs -f nginx     # 查看 Nginx 日志
docker compose restart netops    # 仅重启后端
```

#### 自定义域名

编辑 `nginx/nginx.conf`，将 `server_name _` 改为你的域名：

```nginx
server_name netops.example.com;
```

#### 启用 HTTPS

1. 将证书文件放入 `nginx/ssl/` 目录
2. 取消 `docker-compose.yml` 中 SSL volume 的注释
3. 在 `nginx/nginx.conf` 中添加 SSL 配置块

---

### 方式 C — 手动部署

适用于自定义环境或开发调试。

**前置条件**：Node.js 18+、Python 3.10+、PostgreSQL 17

```bash
# 1. 克隆项目
git clone https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation

# 2. Python 环境
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

# 3. 前端
npm install
npm run build

# 4. PostgreSQL
sudo -u postgres psql -c "CREATE USER netops WITH PASSWORD '你的密码';"
sudo -u postgres psql -c "CREATE DATABASE netops OWNER netops;"

# 5. 环境配置
cp .env.example .env
# 编辑 .env：设置 DATABASE_URL、SECRET_KEY、CREDENTIAL_ENCRYPTION_KEY

# 6. CAP_NET_RAW（Linux，用于 ICMP ping）
sudo setcap cap_net_raw+ep $(readlink -f .venv/bin/python)

# 7. 启动
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8003 --workers 2
```

---

### License 配置

1. 向我们获取 `license.json` 文件
2. 放置到 `data/license.json`，或通过界面 **设置 → License** 上传
3. 平台启动时自动验证，日志中出现 `[License] [OK]` 表示激活成功

Docker 部署时，将文件复制到容器数据卷：

```bash
docker cp license.json netops-automation:/app/data/license.json
docker compose restart netops
```

---

### 版本升级

```bash
# Ubuntu systemd 部署
cd /opt/netops-automation
git pull
npm install && npm run build
pip install -r backend/requirements.txt
sudo systemctl restart netops

# Docker 部署
git pull
npm install && npm run build
docker compose up -d --build
```
