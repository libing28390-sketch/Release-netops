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

## Network Optimizations for Mainland China / 中国大陆部署网络优化

> [!TIP]
> **Docker Builds are Auto-optimized:**
> The `Dockerfile` has built-in optimizations for Chinese networks. It automatically configures **USTC mirror** for APT, **Aliyun mirror** for PyPI (pip), and **npmmirror** for Node.js dependencies. You do not need to customize mirrors manually during Docker builds.
> 
> **Docker 镜像构建已内置镜像源：**
> 项目的 `Dockerfile` 中已预配置国内镜像加速源。系统包安装自动使用 **中科大源 (USTC)**，Python 依赖包安装自动使用 **阿里云源 (Aliyun)**，前端依赖构建自动使用 **淘宝 NPM 镜像 (npmmirror)**，无需手动更改。

### Speeding Up Manual & Bare-Metal Deployments / 宿主机与手动部署加速建议

If you are performing a bare-metal deployment (via `./deploy-ubuntu.sh` or manually), we highly recommend setting up local mirrors on your host machine to prevent network timeouts:

如果您在宿主机上使用一键脚本或手动部署，为了避免发生网络超时、失败，建议先配置如下国内镜像源：

1. **Python pip mirror / 临时使用或永久配置 pip 国内源**
   ```bash
   # 永久设置 PyPI 镜像源（推荐阿里云或清华源）
   pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
   ```
2. **Node.js npm registry / 配置淘宝 NPM 镜像**
   ```bash
   # 永久设置 NPM 镜像源
   npm config set registry https://registry.npmmirror.com
   ```
3. **Ubuntu APT Source / 修改 Ubuntu APT 软件源**
   If `apt-get update` hangs, backup and replace `/etc/apt/sources.list` with Aliyun or Tsinghua mirrors.
   若宿主机 `apt-get update` 卡死，建议备份并替换 `/etc/apt/sources.list` 为阿里云或清华大学开源镜像源。

### Troubleshooting Docker Pull Failures / 解决 Docker 镜像拉取超时
When running `docker compose up -d`, you might encounter `context deadline exceeded` due to network blocks on Docker Hub. To solve this, configure a registry mirror in `/etc/docker/daemon.json`:

执行 `docker compose up -d` 时，如果遇到 `context deadline exceeded` 报错（由于 Docker Hub 受限导致基础镜像 `postgres` 或 `nginx` 拉取超时），请在 `/etc/docker/daemon.json` 中配置国内可用的镜像加速器：

```json
{
  "registry-mirrors": [
    "https://dockerpull.cn",
    "https://docker.unsee.tech",
    "https://docker.pullpic.ru"
  ]
}
```
After editing, restart the Docker daemon:
保存后，重启 Docker 守护进程使配置生效：
```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

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

> **Interactive Customization Wizard & Environment Setup:**
> When executing the script, an interactive startup prompt (with a 10-second timeout) allows you to seamlessly configure:
> - Custom PostgreSQL database password
> - Custom backend API listening port (default: 8003)
> - Custom external Nginx proxy port (default: 80)
> 
> You can also pre-configure your `.env` file manually (`cp .env.example .env`). The script will auto-detect and retain your pre-configured settings.

```bash
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

#### What the script does

1. Installs system packages: Python 3, Node.js 22, Nginx, PostgreSQL, libcap2-bin
2. Clones or synchronizes the latest repository from GitHub (`https://github.com/libing28390-sketch/Release-netops.git`)
3. Interactively requests custom database credentials & listening ports
4. Creates a Python virtual environment and installs `backend/requirements.txt`
5. Installs Node.js dependencies and builds the frontend (`dist/`)
6. Generates `.env` from `.env.example` with random encryption keys
7. Creates PostgreSQL database and sets up credentials
8. Sets `CAP_NET_RAW` on the venv Python binary (for ICMP ping)
9. Writes and enables an Nginx reverse proxy config on your chosen port
10. **systemd environments**: registers and starts a `netops.service` unit
11. **Container environments**: starts the backend with `nohup` and writes PID to `data/netops.pid`

#### After deployment

| Item | Value |
|------|-------|
| Access URL | `http://<server-ip>:<nginx-port>` |
| Default credentials | `admin / admin` |
| Backend port | 8003 (internal, not exposed) |
| Nginx port | User selected (default: 80) |
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

##### Step 1: Clone repository and prepare environment file
```bash
git clone https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation

# Copy environment template
cp .env.example .env
```

Open `.env` and configure:
- Custom PostgreSQL passwords/usernames.
- Security keys (`SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`).
- **Leave `MACHINE_ID_OVERRIDE` blank** for now.

##### Step 2: Start the containers
```bash
# Start all containers (frontend will automatically build inside the container)
docker compose up -d --build
```
Access the application at `http://<server-ip>`.

##### Step 3: Retrieve Machine ID and bind License (For non-trial licenses)
If you are using a licensed edition (Standard/Professional/Enterprise):
1. Visit `http://<server-ip>/api/license/machine-id` (or run `curl http://localhost/api/license/machine-id`) to retrieve your unique Machine ID.
2. Edit `.env` and set `MACHINE_ID_OVERRIDE=YOUR-COPIED-MACHINE-ID`.
3. Restart/recreate the containers to apply the configuration:
   ```bash
   docker compose up -d
   ```
4. Place your `license.json` file in `data/license.json` or upload it in the UI under **Settings → License**.

#### Environment variables reference

An example `.env` file structure:

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

#### Common commands

```bash
docker compose up -d --build     # Build and start
docker compose down              # Stop all containers
docker compose ps                # Container status
docker compose logs -f netops    # Backend logs
docker compose logs -f nginx     # Nginx logs
docker compose restart netops    # Restart backend only
```

#### Troubleshooting / FAQ

**1. Database Connection Error (Postgres Password Authentication Failed)**
*Cause:* You modified `POSTGRES_PASSWORD` in `.env` *after* starting the containers for the first time. The Postgres data volume is already initialized with the old password.
*Fix (Warning: this will delete all database data):*
```bash
docker compose down
docker volume rm netops-automation_netops-pgdata
docker compose up -d
```

**2. Web UI Login Incorrect (Forgot default admin password)**
*Cause:* The default login is `admin` / `admin`. If you changed it or the DB failed to initialize, you can't log in.
*Fix:* Use the same fix as above to completely reset the database and restore the default `admin` account.

**3. Website shows "502 Bad Gateway"**
*Cause:* The `netops` backend container failed to start or is still initializing.
*Fix:* Check the backend logs with `docker compose logs -f netops`. Look for missing `.env` variables or Python errors.

**4. Docker pull fails with `context deadline exceeded`**
*Cause:* Docker Hub is unreachable or timing out from your server's network.
*Fix:* Configure a Docker registry mirror in `/etc/docker/daemon.json` (see the top of this document for examples) and restart the Docker daemon.

**5. License Invalid / System Locked**
*Cause:* The `license.json` is missing from `data/`, or the `MACHINE_ID_OVERRIDE` in your `.env` doesn't match the license.
*Fix:* Verify your machine ID via `http://<server-ip>/api/license/machine-id` and ensure a matching `license.json` is placed in the `data/` folder.

#### Custom domain

Edit `nginx/nginx.conf`, change `server_name _` to your domain:

```nginx
server_name netops.example.com;
```

#### HTTPS / SSL

HTTPS is enabled by default in the Docker configuration. By default, the stack expects a certificate and key at `nginx/ssl/netops.crt` and `nginx/ssl/netops.key`.

To generate a secure self-signed certificate for testing or internal network access, run:
```bash
.venv/bin/python scripts/generate_ssl_cert.py  # or python scripts/generate_ssl_cert.py
```

To use your own custom/valid CA certificates:
1. Place your certificate file (`netops.crt`) and private key file (`netops.key`) in the `nginx/ssl/` directory.
2. Recreate the containers:
   ```bash
   docker compose down
   docker compose up -d
   ```

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
docker compose up -d --build

# Windows (GUI)
# 1. Right-click the system tray icon and click "Exit" to stop the running service.
# 2. Run the following command in the project root to fetch the latest changes (and NetOps.exe):
git pull
# 3. Double-click `start.bat` again. The graphical manager will automatically update dependencies and boot.
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
# 推荐：先下载再执行，国内极速直达
curl -fsSL -o /tmp/deploy.sh https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh
chmod +x /tmp/deploy.sh
bash /tmp/deploy.sh
```

也支持管道方式：
```bash
curl -fsSL https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh | bash
```

#### 已克隆项目目录内执行

> **交互式环境向导与参数自定义（全新亮点）：**
> 在执行部署脚本时，内置带 10 秒倒计时自动保护的交互式向导！支持直接在终端输入自定义：
> - 数据库 PostgreSQL 独立登录口令
> - 后端 API 内部监听端口（默认 8003）
> - 外部 Nginx 代理访问端口（默认 80）
> 
> 您也可在执行前提前配置 `.env` (`cp .env.example .env`)，部署脚本将完美检测并继承您的既有配置。

```bash
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

#### 脚本自动完成的步骤

1. 安装系统包：Python 3、Node.js 22、Nginx、PostgreSQL、libcap2-bin
2. 自动从 GitHub 极速拉取或同步最新仓库代码 (`https://github.com/libing28390-sketch/Release-netops.git`)
3. 交互式询问并设定自定义口令及端口
4. 创建 Python 虚拟环境并安装 `backend/requirements.txt`
5. 安装 Node.js 依赖并构建前端（`dist/`）
6. 从 `.env.example` 生成 `.env`，随机生成各类加密密钥
7. 初始化 PostgreSQL 数据库及授权
8. 为虚拟环境 Python 设置 `CAP_NET_RAW`（用于 ICMP ping）
9. 写入并启用 Nginx 反向代理配置（监听您设定的端口）
10. **systemd 环境**：注册并启动 `netops.service` 系统服务
11. **容器环境**：以 `nohup` 后台方式启动后端，PID 写入 `data/netops.pid`

#### 部署完成后

| 项目 | 值 |
|------|-----|
| 访问地址 | `http://<服务器IP>:<Nginx访问端口>` |
| 默认账号 | `admin / admin` |
| 后端端口 | 8003（内部，不对外暴露） |
| Nginx 端口 | 用户自定义（默认：80） |
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

##### 第一步：克隆项目并准备环境文件
```bash
git clone https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation

# 拷贝环境配置模版
cp .env.example .env
```

打开 `.env` 文件，配置如下参数：
- 数据库连接信息 (`POSTGRES_USER`, `POSTGRES_PASSWORD` 等)
- 安全密钥 (`SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`)
- **此时先保持 `MACHINE_ID_OVERRIDE` 为空**。

##### 第二步：启动所有容器
```bash
# 启动所有容器（前端会在 Docker 容器内自动构建，宿主机无需安装 Node.js/npm）
docker compose up -d --build
```
启动后，可通过浏览器访问 `http://<服务器IP>`。

##### 第三步：获取机器 ID 并绑定 License（非试用版必填）
如果您使用的是商业授权版本（标准版/专业版/企业版）：
1. 访问 `http://<服务器IP>/api/license/machine-id`（或在宿主机运行 `curl http://localhost/api/license/machine-id`）来获取这台机器的唯一机器码。
2. 编辑 `.env` 文件，将获取到的机器码填入 `MACHINE_ID_OVERRIDE=你的机器码`。
3. 运行以下命令应用并重启后端容器：
   ```bash
   docker compose up -d
   ```
4. 将厂商提供的 `license.json` 文件放置到 `data/license.json`（或登录系统后，在 **设置 → License** 界面上传）。

#### 环境变量参考

`.env` 配置文件结构参考：

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

#### 常用命令

```bash
docker compose up -d --build     # 构建并启动
docker compose down              # 停止所有容器
docker compose ps                # 查看容器状态
docker compose logs -f netops    # 查看后端日志
docker compose logs -f nginx     # 查看 Nginx 日志
docker compose restart netops    # 仅重启后端
```

#### 常见问题 (FAQ)

**1. 后端连不上数据库 (Postgres Password Authentication Failed)**
*原因*：你在**首次启动容器之后**，才修改了 `.env` 中的 `POSTGRES_PASSWORD`。由于 PostgreSQL 容器在首次启动时已经用当时的密码初始化了数据卷（Volume），后续修改不会自动同步。
*解决办法（注意：这会清空所有数据库数据！）：*
```bash
docker compose down
# 如果你 clone 的文件夹叫 netops-automation，前缀就是它
docker volume rm netops-automation_netops-pgdata
docker compose up -d
```

**2. Web 界面登录提示密码错误 (忘记 admin 密码)**
*原因*：系统默认管理员为 `admin` / `admin`。如果你改过密码然后忘记了，或者由于某些原因数据库未正常初始化。
*解决办法*：如果你是刚部署且没有重要数据，可以使用上面的命令彻底删除数据库数据卷，重新启动后会再次用 `admin` 账号进行初始化。

**3. 访问页面提示 502 Bad Gateway**
*原因*：后端的 `netops` 容器没有成功启动，或者还在启动加载中。
*解决办法*：使用 `docker compose logs -f netops` 查看后端报错日志。通常是因为缺少必要的 `.env` 配置，或者容器仍在重启，修复后重新启动即可。

**4. Docker 拉取镜像报 `context deadline exceeded`**
*原因*：国内网络拉取 Docker Hub 官方镜像超时或受限。
*解决办法*：请在 `/etc/docker/daemon.json` 中配置国内镜像加速器（详细步骤见本文档顶部的“网络优化”章节）。

**5. 提示授权无效 (License Invalid) / 系统被锁定**
*原因*：`data/license.json` 文件不存在，或者 `.env` 中的 `MACHINE_ID_OVERRIDE` 与当前机器不匹配。
*解决办法*：访问 `http://<服务器IP>/api/license/machine-id` 获取机器码，联系厂商生成匹配的 License 并在系统中上传。

#### 自定义域名

编辑 `nginx/nginx.conf`，将 `server_name _` 改为你的域名：

```nginx
server_name netops.example.com;
```

#### 启用 HTTPS

Docker 部署配置中已默认启用 HTTPS。默认情况下，系统要求在 `nginx/ssl/` 目录下放置 `netops.crt`（证书）和 `netops.key`（私钥）文件。

如需快速生成自签名证书以供测试或内网访问，请执行：
```bash
.venv/bin/python scripts/generate_ssl_cert.py  # 或 python scripts/generate_ssl_cert.py
```

若要配置您自己申请的受信任 CA 证书：
1. 将您的证书和私钥文件分别重命名为 `netops.crt` 和 `netops.key`，并放入项目目录下的 `nginx/ssl/` 目录中。
2. 重建并重启容器以应用配置：
   ```bash
   docker compose down
   docker compose up -d
   ```

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
docker compose up -d --build

# Windows 本地部署 (GUI)
# 1. 右键系统托盘图标，点击“退出 (Exit)”以完全关闭运行中的服务。
# 2. 在项目根目录执行以下命令拉取最新代码（会自动下载最新 NetOps.exe）：
git pull
# 3. 重新双击运行根目录下的 `start.bat` 即可，图形化向导会自动处理后续的环境校验与启动。
```

---

### Windows Deployment & Desktop Integration

You can run the application directly on Windows as a zero-configuration local server with a system tray controller.

#### 0. Get the Windows Release Code
Before starting, clone the **Windows-specific release branch** (`windows`) to avoid downloading unnecessary Linux/Docker dependencies:
```powershell
git clone -b windows https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation
```

#### 1. Setup Environment & Dependencies
1. **Prepare Python & Node.js**: Ensure Python 3.10+ and Node.js are installed on your machine.
2. **Setup Virtualenv & Requirements**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r backend/requirements.txt
   ```
3. **Build Frontend**:
   ```powershell
   npm install
   npm run build
   ```
4. **Configure Database (SQLite)**: By default, if the `DATABASE_URL` environment variable is not defined or commented out in your `.env` file, the platform automatically initializes and uses a local SQLite database at `data/netops.db` (zero configuration needed).

#### 2. Run & Integrate (Two Modes)

##### Option A: Interactive Command Prompt (Foreground Mode)
1. Double-click `start.bat` in the root folder.
2. Select **[1] 启动 NetOps (在前台控制台运行)**.
3. The server starts in the terminal and your default browser opens to `http://127.0.0.1:5010`. Keep the terminal window open to keep the service running.

##### Option B: System Tray & Background Mode (Recommended Desktop Experience)
1. Double-click `start.bat` in the root folder.
2. Select **[2] 创建桌面快捷方式 (后台无窗口运行)**. This will:
   - Install desktop tray dependencies (`pystray`).
   - Create a desktop shortcut named **NetOps 运维平台** with a custom network topology icon.
3. Double-click the new desktop shortcut. The server starts silently in the background (no console windows). A network topology icon appears in your Windows system tray, and your browser opens to `http://127.0.0.1:5010`.
4. To stop the service, right-click the system tray icon and choose **退出 (Exit)**.

---

### Windows 本地部署与桌面集成指南

您可以在 Windows 系统上直接将项目作为本地服务运行，并利用 Windows 系统托盘在后台进行静默管理。

#### 0. 获取 Windows 专属发布代码
开始之前，请克隆 **Windows 专属发布分支** (`windows`)，以避免下载冗余的 Linux/Docker 依赖：
```powershell
git clone -b windows https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation
```

#### 1. 初始化依赖环境
1. **安装环境要求**：确保本地已安装 Python 3.10+ 和 Node.js。
2. **创建虚拟环境并安装 Python 依赖**：
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r backend/requirements.txt
   ```
3. **构建前端静态资源**（只需构建一次，后续后端会自动托管）：
   ```powershell
   npm install
   npm run build
   ```
4. **配置数据库（SQLite 零配置）**：默认情况下，如果 `.env` 配置文件中的 `DATABASE_URL` 被注释或未配置，系统会自动切换为轻量级 SQLite 数据库（存储于 `data/netops.db`），无需安装和运行 PostgreSQL。

#### 2. 启动与管理（两种运行模式）

##### 方式 A：前台命令行模式
1. 双击运行根目录下的 `start.bat`。
2. 输入选项 `1` 选择 **[1] 启动 NetOps (在前台控制台运行)**。
3. 系统会在黑窗口中启动服务，并自动打开默认浏览器访问 `http://127.0.0.1:5010`。此命令行窗口必须保持开启，服务才会运行。

##### 方式 B：后台系统托盘模式（推荐桌面体验）
1. 双击运行根目录下的 `start.bat`。
2. 输入选项 `2` 选择 **[2] 创建桌面快捷方式 (后台无窗口运行)**。该步骤将：
   - 自动检测并安装托盘管理包（`pystray`）。
   - 在您的 Windows 桌面上生成一个名为 **NetOps 运维平台** 的快捷方式，并绑定专属网络拓扑图标。
3. 双击运行桌面上的 **NetOps 运维平台** 快捷方式。系统将以静默模式在后台启动（不弹出任何黑色控制台），并在右下角系统托盘生成专属图标，随后自动调起默认浏览器打开 `http://127.0.0.1:5010`。
4. 若需停止服务，只需在系统托盘右键该图标并点击 **退出 (Exit)** 即可。

