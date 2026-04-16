# NetOps Automation 部署指南

## 项目概述

| 组件 | 技术栈 | 端口 |
|------|--------|------|
| 前端 | React 19 + TypeScript + Vite + TailwindCSS | 4300 (dev) |
| 后端 | Python FastAPI + Uvicorn | 8004 |
| 数据库 | PostgreSQL 17 (默认) / SQLite (fallback) | 5432 |
| SNMP | pysnmp 7.x | - |

## 项目结构

```
netops-automation/
├── backend/              # Python 后端
│   ├── main.py           # FastAPI 入口 + 状态监控
│   ├── database.py       # 数据库管理 (PG/SQLite 双后端)
│   ├── api/              # API 路由
│   ├── core/             # 配置与日志
│   ├── drivers/          # 设备驱动 (Netmiko/Scrapli)
│   ├── models/           # 数据模型
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # SNMP 服务等
│   └── requirements.txt  # Python 依赖
├── src/                  # React 前端
│   ├── App.tsx           # 主应用组件
│   ├── main.tsx          # 入口
│   ├── i18n.tsx          # 国际化
│   └── components/       # UI 组件
├── data/                 # 日志与本地数据目录
├── backup/               # 配置备份目录
├── package.json          # Node.js 依赖与脚本
├── vite.config.ts        # Vite 配置
└── docker-compose.yml    # Docker 编排 (含 PostgreSQL)
```

---

## Windows 部署

### 前置条件

- **Node.js** ≥ 18（推荐通过 https://nodejs.org 安装 LTS 版本）
- **Python** ≥ 3.10（推荐通过 https://www.python.org 安装，安装时勾选 "Add to PATH"）
- **Git**（可选，用于克隆仓库）

### 安装步骤

```powershell
# 1. 克隆项目
git clone https://github.com/libing28390-sketch/netsops.git netops-automation
cd netops-automation

# 2. 创建 Python 虚拟环境
py -3 -m venv .venv

# 3. 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 4. 安装 Python 依赖
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 5. 安装 Node.js 依赖
npm install
```

### 启动开发环境

```powershell
# 一键启动（前端 + 后端）
npm run dev

# 或者分别启动
npm run dev:backend:win     # 仅后端
npm run dev:frontend        # 仅前端
```

### 生产构建与运行

```powershell
npm run start:win
# 或
npm run build              # 构建前端
.venv\Scripts\python.exe backend\main.py   # 启动后端（同时 serve 前端）
```

### Windows 特有注意事项

1. **防火墙**：首次运行时 Windows Defender 可能弹出网络访问提示，需要允许 Python 和 Node.js 的网络访问
2. **ping3 权限**：`ping3` 库在 Windows 上通常可直接使用，无需额外权限
3. **端口占用**：如遇端口被占用，运行 `npm run cleanup` 或手动查看：
   ```powershell
   netstat -ano | findstr :8004
   taskkill /PID <pid> /F
   ```
4. **PowerShell 执行策略**：如果 `\.venv\Scripts\Activate.ps1` 报错，先执行：
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

---

## Ubuntu 部署

### 前置条件

```bash
# 安装 Node.js (通过 nvm，推荐)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash
source ~/.bashrc
nvm install 22

# 安装 Python 和系统依赖
sudo apt update
sudo apt install python3 python3-venv python3-dev build-essential
```

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/libing28390-sketch/netsops.git netops-automation
cd netops-automation

# 2. 创建 Python 虚拟环境
python3 -m venv .venv

# 3. 激活虚拟环境
source .venv/bin/activate

# 4. 安装 Python 依赖
pip install -r backend/requirements.txt

# 5. 安装 Node.js 依赖
npm install
```

### 启动开发环境

```bash
# 一键启动（前端 + 后端）
npm run dev

# 或者分别启动
npm run dev:backend:linux   # 仅后端
npm run dev:frontend        # 仅前端
```

### 生产构建与运行

```bash
npm run start:linux
# 或
npm run build
.venv/bin/python backend/main.py
```

### Ubuntu 特有注意事项

1. **ping3 需要 RAW 权限**：Linux 上发送 ICMP 包需要特权，有两种方式：
   ```bash
   # 方式 A：给 Python 添加 CAP_NET_RAW 能力（推荐）
   sudo setcap cap_net_raw+ep $(readlink -f .venv/bin/python)

   # 方式 B：以 root 运行（不推荐）
   sudo .venv/bin/python backend/main.py
   ```
2. **防火墙**：Ubuntu 默认 UFW 可能阻止外部访问：
   ```bash
   sudo ufw allow 'Nginx Full'   # 生产：80/443
   sudo ufw allow 4300/tcp       # 仅开发时需要
   ```
3. **端口占用**：查看和清理端口：
   ```bash
   lsof -i :8004
   kill -9 <pid>
   # 或直接
   npm run cleanup
   ```
4. **Vite watcher 限制**：如果 `npm run dev` 在 Ubuntu 上报 `ENOSPC: System limit for number of file watchers reached`，本项目已在 `vite.config.ts` 中忽略 `.venv/`、`backend/`、`backup/`、`data/` 等目录。拉取最新代码后重试；如果宿主机 watcher 上限仍然偏低，可额外执行：
   ```bash
   echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
   echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf
   sudo sysctl -p
   ```
5. **后台运行（生产）**：使用 systemd 服务：
   ```bash
   # 创建服务文件
   sudo tee /etc/systemd/system/netops.service > /dev/null <<EOF
   [Unit]
   Description=NetOps Automation Platform
   After=network.target

   [Service]
   Type=simple
   User=$USER
   WorkingDirectory=$(pwd)
   ExecStart=$(pwd)/.venv/bin/python backend/main.py
   Restart=always
   RestartSec=5
   Environment=NODE_ENV=production
   Environment=PYTHONPATH=backend
   AmbientCapabilities=CAP_NET_RAW

   [Install]
   WantedBy=multi-user.target
   EOF

   sudo systemctl daemon-reload
   sudo systemctl enable netops
   sudo systemctl start netops
   ```

---

## 通用说明

### npm 脚本一览

| 命令 | 说明 |
|------|------|
| `npm run dev` | 一键启动开发环境（自动检测平台） |
| `npm run dev:backend:win` | 仅启动后端（Windows） |
| `npm run dev:backend:linux` | 仅启动后端（Ubuntu/Linux） |
| `npm run dev:frontend` | 仅启动前端开发服务器 |
| `npm run build` | 构建前端生产版本到 `dist/` |
| `npm run start` | 构建 + 启动生产模式（自动检测平台） |
| `npm run clean` | 删除 `dist/` 构建目录 |

### 默认账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin | Administrator |

### 环境变量 (.env)

从 `.env.example` 复制并按需修改：

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# Linux / macOS
cp .env.example .env
```

建议至少检查并按需修改以下变量：
```env
# 应用基础配置
SECRET_KEY=change-this-in-production
CREDENTIAL_ENCRYPTION_KEY=change-me-to-a-random-secret
ENVIRONMENT=production

# 跨域与平台跳转
CORS_ORIGINS=http://localhost:4300
PLATFORM_URL=

# 高频原始接口遥测保留时长（小时）
TELEMETRY_RAW_RETENTION_HOURS=48

# 1分钟聚合遥测保留时长（天）
TELEMETRY_ROLLUP_RETENTION_DAYS=365

# 接口 DOWN 告警开关
ALERT_INTERFACE_DOWN_ENABLED=true

# 接口带宽利用率告警阈值（百分比）
ALERT_INTERFACE_UTIL_THRESHOLD=85

# 主机资源告警阈值（百分比）
ALERT_CPU_THRESHOLD=90
ALERT_MEMORY_THRESHOLD=90

# 告警通知 Webhook（可填写企业微信机器人地址）
ALERT_NOTIFY_WEBHOOK_URL=
```

### 访问地址

- 开发模式：http://localhost:4300（Vite 代理 API 到 8004）
- 生产模式（直连后端）：http://localhost:8004（`npm run start` / `python backend/main.py`）
- Nginx 反向代理部署：http://localhost:8080（Ubuntu 一键部署默认端口，可通过 `NGINX_PORT` 修改）
- Docker 模式：http://localhost:8080（Nginx 容器 → netops 容器）

---

## 一键部署（推荐）

### 方式 A：已克隆项目

```bash
cd netops-automation
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

### 方式 B：全新服务器（真正一键）

无需手动 git clone，脚本自动完成克隆 + 部署：

```bash
# 一行命令，什么都不用装
curl -fsSL https://raw.githubusercontent.com/libing28390-sketch/netsops/main/deploy-ubuntu.sh | bash
```

或者手动指定安装目录：

```bash
# 下载脚本后执行（默认安装到 /opt/netops-automation）
curl -fsSL -o deploy.sh https://raw.githubusercontent.com/libing28390-sketch/netsops/main/deploy-ubuntu.sh
chmod +x deploy.sh
INSTALL_DIR=/opt ./deploy.sh
```

脚本会自动完成：Git 安装 → 项目克隆 → Python/Node 安装 → 依赖 → 前端构建 → Nginx 反向代理 → systemd 服务注册。

部署完成后通过 `http://<服务器IP>:8080` 访问（Nginx 8080 端口 → 后端 8004）。

> 如需修改 Nginx 监听端口，在运行部署脚本前设置 `NGINX_PORT` 环境变量，如：`NGINX_PORT=80 ./deploy.sh`

---

## Docker 部署

### 快速启动（已有代码）

```bash
cd netops-automation
npm install && npm run build
docker compose up -d --build
```

### 全新服务器一键 Docker 部署

```bash
# 1. 安装 Docker（如未安装）
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录使 docker 组生效，或执行: newgrp docker

# 2. 安装 Git 并克隆项目
sudo apt-get update -qq && sudo apt-get install -y -qq git nodejs npm
git clone https://github.com/libing28390-sketch/netsops.git netops-automation
cd netops-automation

# 3. 构建前端 + 启动容器
npm install && npm run build
docker compose up -d --build

# 4. 查看状态
docker compose ps
docker compose logs -f
```

### 架构说明

```
用户 → Nginx (:8080) → FastAPI (:8004)
              │
              ├── /assets/  → 本地 dist/ 静态文件（缓存 365 天）
              ├── /api/*    → 反向代理到 netops 容器
              ├── /ws       → WebSocket 代理
              └── /*        → SPA 回退 index.html
```

### 自定义域名

编辑 `nginx/nginx.conf`，将 `server_name _` 改为你的域名：
```nginx
server_name netops.example.com;
```

### 启用 HTTPS

1. 将证书放入 `nginx/ssl/` 目录
2. 取消 `docker-compose.yml` 中 SSL volume 注释
3. 在 `nginx/nginx.conf` 中添加 SSL 配置块

### 环境变量

```bash
# .env 文件
CREDENTIAL_ENCRYPTION_KEY=your-random-secret-key
CORS_ORIGINS=https://netops.example.com
```

### 常用 Docker 命令

```bash
docker compose up -d --build   # 构建并启动
docker compose down            # 停止
docker compose logs -f nginx   # 查看 Nginx 日志
docker compose logs -f netops  # 查看后端日志
docker compose restart nginx   # 重启 Nginx
```

---

## PostgreSQL 数据库

默认使用 PostgreSQL。如设置了 `DATABASE_URL=postgresql://...` 环境变量，系统自动启用 PG；未设置时 fallback 到 SQLite。

### 1. 安装 PostgreSQL

```bash
# Ubuntu
sudo apt install postgresql postgresql-contrib
sudo systemctl enable postgresql

# 创建数据库和用户
sudo -u postgres psql -c "CREATE USER netops WITH PASSWORD 'your-secure-password';"
sudo -u postgres psql -c "CREATE DATABASE netops OWNER netops;"
```

### 2. 配置环境变量

在 `.env` 文件中添加：

```env
DATABASE_URL=postgresql://netops:your-secure-password@localhost:5432/netops
```

或设置系统环境变量：

```bash
export DATABASE_URL="postgresql://netops:your-secure-password@localhost:5432/netops"
```

> 设置 `DATABASE_URL` 后，系统自动使用 PostgreSQL；不设置则使用默认 SQLite。

### 3. 初始化

首次启动时，系统自动在 PostgreSQL 中创建所有表结构，无需手动迁移。

### 4. Docker 部署

`docker-compose.yml` 已内置 PostgreSQL 服务，`docker compose up -d --build` 即可启动完整环境。

### 注意事项

- 首次启动自动建表，无需迁移脚本
- 切换回 SQLite 只需删除 `DATABASE_URL` 环境变量
- PostgreSQL 驱动 `psycopg2-binary` 已包含在 requirements.txt 中

