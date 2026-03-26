# NetPilot / NetOps Automation Platform

English | 中文

NetPilot is a full-stack network operations platform for device inventory, monitoring, automation, configuration backup, compliance auditing, and operational traceability.

NetPilot 是一个面向网络运维场景的全栈平台，覆盖设备资产管理、运行监控、自动化执行、配置备份、合规审计与操作追踪。

## English

### Overview

NetPilot is built for network engineers who need a unified console to manage multi-vendor infrastructure. It combines operational visibility with automation workflows so common daily tasks can be completed in one place instead of switching between multiple tools.

### Core Capabilities

- **Dashboard** — Operational overview with device status donut chart, job trends, compliance trends, and real-time KPIs
- **Multi-vendor device inventory** with platform, model, software, site, and role metadata
- **Interface monitoring** with traffic, bandwidth utilization, status changes, and flap detection
- **Automation center** for direct execution, playbooks, and execution history
- **Configuration center** for backup, snapshot browsing, diff comparison, search, and rollback workflows
- **Config drift detection** — Scan all devices for running-config changes, color-coded diff view, selective line-level rollback preview
- **Capacity planning & forecasting** — CPU/memory/link utilization trends, 30-day linear forecast, days-to-threshold risk assessment
- **IP/VLAN management (IPAM)** — Subnet CRUD with utilization bars, IP address assignment, conflict detection
- **Compliance auditing** with findings, severity breakdown, and remediation-oriented views
- **Alert center** with alert desk, rule management, and maintenance windows
- **Reports center** with KPI cards, job/compliance trend charts, and multi-sheet XLSX export
- **Audit logs and user management** for operational accountability and access control
- **XLSX export** available across alerts, audit logs, compliance findings, and reports

### Technology Stack

- Frontend: React 19, TypeScript, Vite, TailwindCSS, Recharts
- Backend: Python, FastAPI, SQLite
- Network automation: Netmiko, Scrapli, SNMP-based telemetry collection
- Runtime model: Vite frontend in development, Python backend serving APIs and production runtime

### Project Structure

```text
netops-automation/
├── backend/                  # Python backend
│   ├── api/                  # REST API routes
│   ├── core/                 # Config and logging
│   ├── data/                 # Local backend runtime data
│   ├── drivers/              # Device access drivers
│   ├── models/               # Database models
│   ├── schemas/              # Pydantic schemas
│   ├── services/             # Business services
│   ├── database.py           # Database bootstrap
│   ├── main.py               # FastAPI entrypoint
│   └── requirements.txt      # Python dependencies
├── src/                      # React frontend source
│   ├── components/           # Reusable UI components
│   ├── App.tsx               # Main application shell
│   ├── i18n.tsx              # Language resources
│   └── main.tsx              # Frontend entrypoint
├── data/                     # Runtime data directory
├── cleanup-ports.js          # Local port cleanup helper
├── deploy-ubuntu.sh          # Ubuntu deployment helper
├── DEPLOY.md                 # Deployment guide
├── package.json              # Node scripts and dependencies
└── vite.config.ts            # Frontend build configuration
```

### Quick Start

#### Prerequisites

- Node.js 18+
- Python 3.10+
- Git

#### Setup

```bash
git clone https://github.com/libing28390-sketch/netsops.git
cd netsops

# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

# Frontend dependencies
npm install
```

#### Environment Files and Git Ignore

- Copy `.env.example` to `.env` and fill in your local values before production-like deployment.
- Keep `.env.example` in the repository as a template so teammates know required environment variables.
- Keep `.gitignore` in the repository to avoid committing sensitive files (for example `.env`) and local artifacts (`node_modules`, build output, caches, logs).

#### Development

```bash
npm run dev
```

Default development endpoints:

- Frontend: http://localhost:4300
- Backend API: http://localhost:8003

#### Build

```bash
npm run build
```

### CI (GitHub Actions)

- Frontend workflow: `.github/workflows/frontend-build-check.yml`
	- Runs on changes to frontend-related files in `main` push and pull requests
	- Executes `npm ci`, `npm run lint`, and `npm run build`
- Backend workflow: `.github/workflows/backend-pytest-check.yml`
	- Runs on changes to backend-related files in `main` push and pull requests
	- Installs `backend/requirements.txt` and runs `pytest`
	- Strict policy: no tests or test failures both fail CI

### npm Scripts

- `npm run dev`: Start backend and frontend together
- `npm run cleanup`: Clean occupied local dev ports
- `npm run dev:frontend`: Start Vite only
- `npm run dev:backend`: Start Python backend only
- `npm run build`: Build frontend assets
- `npm run start`: Run production flow
- `npm run lint`: TypeScript type check

### Deployment

See [DEPLOY.md](DEPLOY.md) for Windows and Ubuntu deployment instructions.

### Notes

- This repository ignores local virtual environments, local SQLite runtime files, backups, logs, and editor-specific settings.
- The platform is intended for internal operations and lab or enterprise network automation scenarios.

## 中文说明

### 项目简介

NetPilot 是一个面向网络工程师和运维团队的统一运维平台，目标是把常见的网管工作流集中到一个控制台中完成，包括设备台账、运行监控、自动化执行、配置备份、合规检查和审计追踪。

### 主要功能

- **运维看板** — 设备状态甜甜圈图、作业趋势、合规趋势、实时 KPI 卡片
- **多厂商设备资产管理**，支持平台、型号、版本、站点、角色等信息维护
- **接口监控**，支持流量、带宽利用率、状态变化和 flap 检测
- **自动化中心**，支持直接执行、场景编排、Playbook 和执行历史
- **配置中心**，支持备份、快照浏览、差异对比、搜索和回滚流程
- **配置漂移检测** — 全量扫描设备配置变化，彩色 diff 视图，支持选择性行级回滚预览
- **容量规划与预测** — CPU/内存/链路利用率趋势，30 天线性预测，距阈值天数风险评估
- **IP/VLAN 资源管理（IPAM）** — 子网增删改查（含利用率进度条）、IP 地址分配、冲突检测
- **合规审计**，支持发现项、严重级别统计和整改视图
- **告警中心**，含告警工作台、规则管理和维护期管理
- **运维报表中心**，KPI 卡片、作业/合规趋势图表，多 Sheet XLSX 导出
- **审计日志与用户管理**，满足运维留痕和权限控制要求
- **XLSX 导出**，覆盖告警、审计日志、合规发现项和报表

### 技术栈

- 前端：React 19、TypeScript、Vite、TailwindCSS、Recharts
- 后端：Python、FastAPI、SQLite
- 网络自动化：Netmiko、Scrapli、SNMP 数据采集

### 目录结构

```text
netops-automation/
├── backend/                  # Python 后端
│   ├── api/                  # API 路由
│   ├── core/                 # 配置与日志
│   ├── data/                 # 后端本地运行数据
│   ├── drivers/              # 设备访问驱动
│   ├── models/               # 数据模型
│   ├── schemas/              # Pydantic 模型
│   ├── services/             # 业务服务
│   ├── database.py           # 数据库初始化
│   ├── main.py               # FastAPI 启动入口
│   └── requirements.txt      # Python 依赖
├── src/                      # React 前端源码
│   ├── components/           # UI 组件
│   ├── App.tsx               # 主应用容器
│   ├── i18n.tsx              # 国际化配置
│   └── main.tsx              # 前端入口
├── data/                     # 运行时数据目录
├── cleanup-ports.js          # 本地端口清理脚本
├── deploy-ubuntu.sh          # Ubuntu 部署脚本
├── DEPLOY.md                 # 部署说明文档
├── package.json              # Node 依赖与脚本
└── vite.config.ts            # 前端构建配置
```

### 快速开始

#### 环境要求

- Node.js 18 及以上
- Python 3.10 及以上
- Git

#### 安装步骤

```bash
git clone https://github.com/libing28390-sketch/netsops.git
cd netsops

# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

# 安装前端依赖
npm install
```

#### 环境变量与 Git 忽略规则

- 在接近生产的部署场景中，请先复制 `.env.example` 为 `.env`，并填写本地真实参数。
- 建议保留仓库中的 `.env.example`，用于告知协作者项目所需的环境变量键名。
- 建议保留仓库中的 `.gitignore`，用于避免提交敏感信息（如 `.env`）和本地产物（如 `node_modules`、构建产物、缓存、日志）。

#### 开发启动

```bash
npm run dev
```

默认开发访问地址：

- 前端：http://localhost:4300
- 后端 API：http://localhost:8003

#### 构建

```bash
npm run build
```

### CI（GitHub Actions）

- 前端工作流：`.github/workflows/frontend-build-check.yml`
	- 在 `main` 分支的 push / pull request 且涉及前端相关文件变更时触发
	- 执行 `npm ci`、`npm run lint`、`npm run build`
- 后端工作流：`.github/workflows/backend-pytest-check.yml`
	- 在 `main` 分支的 push / pull request 且涉及后端相关文件变更时触发
	- 安装 `backend/requirements.txt` 并执行 `pytest`
	- 严格策略：无测试或测试失败都会导致 CI 失败

### 常用脚本

- `npm run dev`：同时启动前端和后端
- `npm run cleanup`：清理本地开发端口
- `npm run dev:frontend`：仅启动前端
- `npm run dev:backend`：仅启动后端
- `npm run build`：构建前端静态资源
- `npm run start`：生产模式启动
- `npm run lint`：TypeScript 类型检查

### 部署说明

Windows 和 Ubuntu 的部署步骤请查看 [DEPLOY.md](DEPLOY.md)。

### Windows 代理配置（V2Ray: 127.0.0.1:10808）

当出现“浏览器可访问外网，但 Git/npm/pip 等命令行工具无法访问外网”时，可执行以下步骤统一代理。

#### 一键应用（普通 PowerShell）

```powershell
# 1) WinINET（系统/桌面应用常用）
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "socks=127.0.0.1:10808;http=127.0.0.1:10808;https=127.0.0.1:10808" /f

# 2) 用户环境变量（新开终端生效）
setx HTTP_PROXY "socks5://127.0.0.1:10808"
setx HTTPS_PROXY "socks5://127.0.0.1:10808"
setx ALL_PROXY "socks5://127.0.0.1:10808"
setx NO_PROXY "localhost,127.0.0.1,::1"

# 3) Git 全局代理
git config --global http.proxy socks5h://127.0.0.1:10808
git config --global https.proxy socks5h://127.0.0.1:10808

# 4) npm 代理
npm config set proxy "http://127.0.0.1:10808"
npm config set https-proxy "http://127.0.0.1:10808"
```

#### WinHTTP（管理员 PowerShell）

WinHTTP 影响系统服务和部分只走 WinHTTP 的工具，必须在“管理员身份”PowerShell 执行：

```powershell
netsh winhttp set proxy 127.0.0.1:10808 "localhost;127.0.0.1"
netsh winhttp show proxy
```

如果出现 `拒绝访问 (5)`，说明当前终端不是管理员权限。

#### 配置验证

```powershell
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer
git config --global --get http.proxy
git config --global --get https.proxy
npm config get proxy
npm config get https-proxy
netsh winhttp show proxy
```

#### pip 安装报错：Missing dependencies for SOCKS support

pip 在本机已经配置了用户级镜像源时，应优先直接使用本地 pip 配置文件，不必额外依赖代理。

如果当前终端设置了以下环境变量：

```powershell
$env:HTTP_PROXY = "socks5://127.0.0.1:10808"
$env:HTTPS_PROXY = "socks5://127.0.0.1:10808"
$env:ALL_PROXY = "socks5://127.0.0.1:10808"
```

即使本地 pip 配置文件已经指向国内镜像，以上环境变量仍然会影响 pip 的网络访问；某些 Windows 环境中的 pip 会因为未安装 SOCKS 传输依赖而报错：`Missing dependencies for SOCKS support`。

优先做法是在当前 PowerShell 会话中临时清空代理变量，让 pip 直接使用本地配置文件中的国内镜像：

```powershell
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

如果你明确需要通过本地代理转发，再临时切换为 HTTP 代理后安装：

```powershell
$env:HTTP_PROXY = "http://127.0.0.1:10808"
$env:HTTPS_PROXY = "http://127.0.0.1:10808"
$env:ALL_PROXY = "http://127.0.0.1:10808"
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

#### 回滚（取消代理）

```powershell
# WinINET
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f

# 环境变量
setx HTTP_PROXY ""
setx HTTPS_PROXY ""
setx ALL_PROXY ""
setx NO_PROXY ""

# Git / npm
git config --global --unset http.proxy
git config --global --unset https.proxy
npm config delete proxy
npm config delete https-proxy

# WinHTTP（管理员）
netsh winhttp reset proxy
```

### 补充说明

- 仓库已忽略本地虚拟环境、SQLite 运行文件、备份文件、日志和编辑器配置。
- 本项目适用于实验环境、内网运维平台场景，以及企业网络自动化原型和内部平台建设。
