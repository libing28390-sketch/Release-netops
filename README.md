# Nexora NetOps Platform

[English](#english) | [中文](#中文说明)

> Version 1.0.1 · Community Edition

Nexora is a full-stack network operations platform covering device inventory, real-time monitoring, automation, configuration backup, compliance auditing, and operational traceability.

Nexora 是一个面向网络运维场景的全栈平台，覆盖设备资产管理、运行监控、自动化执行、配置备份、合规审计与操作追踪。

---

## System Requirements / 系统要求

### Supported Operating Systems / 支持的操作系统

| OS | Version | Architecture | Notes |
|----|---------|--------------|-------|
| Ubuntu | 20.04 LTS | x86_64 | ✅ Recommended / 推荐 |
| Ubuntu | 22.04 LTS | x86_64 | ✅ Recommended / 推荐 |
| Ubuntu | 24.04 LTS | x86_64 | ✅ Supported / 支持 |
| Debian | 11 (Bullseye) | x86_64 | ✅ Supported / 支持 |
| Debian | 12 (Bookworm) | x86_64 | ✅ Supported / 支持 |
| RHEL / Rocky Linux / AlmaLinux | 8.x | x86_64 | ✅ Supported / 支持 |
| RHEL / Rocky Linux / AlmaLinux | 9.x | x86_64 | ✅ Supported / 支持 |
| CentOS Stream | 8, 9 | x86_64 | ✅ Supported / 支持 |
| GitHub Codespaces | — | x86_64 | ✅ Supported / 支持 |
| Docker (any host OS) | Engine 20.10+ | x86_64 | ✅ Supported / 支持 |
| **CentOS** | **7.x** | x86_64 | ❌ Not supported / 不支持 |
| ARM64 / aarch64 | any | arm64 | ❌ Not supported / 不支持 |
| Windows (native) | 10 / 11 / Server | x86_64 | ✅ Supported / 一键图形部署 (GUI) |
| macOS (native) | any | — | ❌ Not supported / 不支持 |

> **Why CentOS 7 is not supported:** The compiled `.so` files require glibc ≥ 2.28. CentOS 7 ships glibc 2.17 and reached End-of-Life in June 2024. Migrate to Rocky Linux 8+ or AlmaLinux 8+.
>
> **为什么不支持 CentOS 7：** 编译的 `.so` 文件需要 glibc ≥ 2.28，CentOS 7 自带 glibc 2.17，且已于 2024 年 6 月停止维护。建议迁移到 Rocky Linux 8+ 或 AlmaLinux 8+。

---

### Software Requirements / 软件要求

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| Python | 3.10 | 3.12 | 3.10 / 3.11 / 3.12 all supported |
| Node.js | 18.x | 22.x LTS | Required for frontend build only |
| PostgreSQL | 14 | 17 | SQLite fallback available for dev/test |
| Nginx | 1.18 | 1.27 | Reverse proxy, included in deploy script |
| glibc | 2.28 | 2.35+ | Determines OS compatibility |
| Docker Engine | 20.10 | 26.x | Docker deployment only |
| Docker Compose | v2.0 | v2.27+ | Docker deployment only |

---

### Hardware Requirements / 硬件要求

The platform runs a background SNMP polling loop (concurrency: 20 devices simultaneously, batch size: 50) and collects interface telemetry every 5 seconds. Resource usage scales with managed device count.

平台后台运行 SNMP 轮询（并发 20 台设备，批次 50 台）并每 5 秒采集一次接口遥测数据，资源消耗随管理设备数量线性增长。

#### Minimum / 最低配置

> Suitable for evaluation, lab environments, or ≤ 20 devices.
> 适用于评估、实验室环境或管理设备数 ≤ 20 台。

| Resource | Requirement |
|----------|-------------|
| CPU | 2 cores / 2 核 |
| RAM | 2 GB |
| Disk | 20 GB (SSD recommended) |
| Network | 100 Mbps, reachable to managed devices |

#### Recommended / 推荐配置

> Suitable for production with 20–200 managed devices.
> 适用于生产环境，管理设备数 20–200 台。

| Resource | Requirement |
|----------|-------------|
| CPU | 4 cores / 4 核 |
| RAM | 4 GB |
| Disk | 50 GB SSD |
| Network | 1 Gbps, reachable to managed devices |

#### Large-scale / 大规模配置

> Suitable for 200–500+ managed devices with full telemetry, compliance scanning, and frequent automation jobs.
> 适用于 200–500+ 台设备，开启全量遥测、合规扫描和高频自动化作业。

| Resource | Requirement |
|----------|-------------|
| CPU | 8 cores / 8 核 |
| RAM | 8 GB |
| Disk | 100 GB SSD |
| Network | 1 Gbps, low-latency to managed devices |

#### Disk space breakdown / 磁盘空间说明

| Data type | Retention | Estimated size (100 devices) |
|-----------|-----------|------------------------------|
| Raw interface telemetry | 48 hours (default) | ~500 MB |
| Aggregated telemetry (1-min) | 365 days (default) | ~2 GB |
| Configuration snapshots | Manual cleanup | ~1 GB |
| PostgreSQL base | — | ~500 MB |
| Application + frontend | — | ~300 MB |
| **Total estimate** | | **~4.5 GB** |

> Retention periods are configurable via `TELEMETRY_RAW_RETENTION_HOURS` and `TELEMETRY_ROLLUP_RETENTION_DAYS` in `.env`.
>
> 保留时长可通过 `.env` 中的 `TELEMETRY_RAW_RETENTION_HOURS` 和 `TELEMETRY_ROLLUP_RETENTION_DAYS` 调整。

#### Network requirements / 网络要求

| Requirement | Detail |
|-------------|--------|
| Management plane access | SSH (TCP 22) to all managed devices |
| SNMP polling | UDP 161 to all managed devices |
| Outbound webhook (optional) | HTTPS 443, for alert notifications |
| Browser to platform | TCP 80 (or 443 with SSL) |
| Platform to PostgreSQL | TCP 5432 (localhost or internal network) |

---

## English

### Core Features

The platform is organised into **11 modules** that mirror the navigation layout:

#### 1. Real-time Monitoring (`/monitor/...`)
- **Overview** (`/monitor/overview`): Operations dashboard — device status, recent automation jobs, upcoming scheduled tasks.
- **Monitoring Center** (`/monitor/telemetry`): NOC command center — host telemetry, performance trends, live alert stream.
- **Server Monitoring** (`/monitor/servers`): Per-server SSH/Shell CPU, memory, disk, and key service telemetry.
- **Network Monitoring** (`/monitor/networks`): Per-device SNMP/CLI traffic, errors, and drop rate telemetry.
- **Topology** (`/monitor/topology`): Auto-discovered LLDP/CDP physical link map, drag-and-drop layout.
- *API Endpoints*: `/api/health`, `/api/monitoring`, `/api/device_health`, `/api/topology`

#### 2. Terminal Access (`/access/...`)
- **Operation Workspace** (`/access/workspace`): Unified asset gateway — launch web SSH sessions through the controlled PAM proxy.
- **PAM Audit** (`/access/pam-audit`): Active session monitor + history archive with command audit and asciinema replay.
- *API Endpoints*: `/api/access`, `/api/pam`

#### 3. Alerts (`/alerts/...`)
- **Alert Center** (`/alerts/desk`): Real-time alert desk with assignment, acknowledge, resolve workflow.
- **Alert History** (`/alerts/history`): Closed-alert archive with filters and export.
- **Alert Rules** (`/alerts/rules`): Threshold and trigger rule management for CPU / memory / interfaces / temperature / hosts.
- **Maintenance** (`/alerts/maintenance`): Maintenance window management — silence alerts during planned changes.
- *API Endpoints*: `/api/alerts`

#### 4. Assets & Config (`/assets/...`)
- **Asset Dashboard** (`/assets/dashboard`): Physical asset registry — vendor, model, serial number, lifecycle status, location.
- **Network Devices** (`/assets/devices`): Logical device list with platform, status, credentials, server-side paging.
- **Servers** (`/assets/servers`): Linux / Windows server inventory.
- **NPA Path Diagnostics** (`/assets/diagnose`): Network path telemetry and multi-hop diagnostics overlay.
- **Network Facts (NSOT)** (`/assets/nsot`): Network source-of-truth database for devices and configurations.
- **IP Toolbox** (`/assets/toolbox`): IP locator (find switch ports), connectivity probes, ARP cache, and MAC change history.
- **Tags** (`/assets/tags`): Tag taxonomy — vendor, location, role, environment groupings used across the platform.
- *API Endpoints*: `/api/assets`, `/api/devices`, `/api/ip_locator`, `/api/tags`

#### 5. CMDB Core (`/cmdb/...`)
- **Credentials** (`/cmdb/credentials`): Secure credential vault (encrypted at rest using AES-256-GCM).
- **Rack Layout** (`/cmdb/racks`): 2D rack visualisation with U-position drag-and-drop.
- **Sites** (`/cmdb/sites`): Site profiles and geographical mapping.
- **VRFs** (`/cmdb/vrfs`): Logical router VRF partitions.
- **VLANs** (`/cmdb/vlans`): VLAN subnet allocations.
- **Tenants** (`/cmdb/tenants`): Tenant profiles for multi-tenancy access.
- *API Endpoints*: `/api/credentials`, `/api/racks`, `/api/cmdb`

#### 6. IPAM (`/ipam/...`)
- **Prefixes** (`/ipam/prefixes`): IP prefix subnets allocation hierarchy.
- **IP Addresses** (`/ipam/ips`): Individual IP address assignments and usage.
- **IP Pools** (`/ipam/pools`): IP address pools management.
- **VIP Mgmt** (`/ipam/vips`): Virtual IP allocations for cluster servers.
- **DHCP Leases** (`/ipam/dhcp`): DHCP leases tracking.
- **Utilization** (`/ipam/utilization`): IP prefix space utilization reporting.
- **IP Reconciliation** (`/ipam/reconciliation`): Automatic IP audit and reconciliation center.
- *API Endpoints*: `/api/ipam`

#### 7. Configuration (`/config/...`)
- **Backup Center** (`/config/backup`): Manual / on-demand running-config backup, snapshot browser, per-device history.
- **Backup Schedule** (`/config/schedule`): Cron-based recurring backup jobs with execution log.
- **Config Diff** (`/config/diff`): Side-by-side or unified diff between any two snapshots, color-coded line-level view.
- **Config Search** (`/config/search`): Full-text grep across **all** snapshots (every device × every version).
- **Templates** (`/config/templates`): Vendor-specific configuration template library with variable substitution.
- *API Endpoints*: `/api/configs`, `/api/templates`, `/api/config_drift`

#### 8. Automation (`/automation/...`)
- **Automation Tasks** (`/automation/tasks`): Direct execution + Quick Playbook + scenario library, real-time WebSocket stream of per-device output.
- **Inspection Overview** (`/automation/inspections`): Trigger ad-hoc network health inspections, full-fleet snapshot view.
- **Inspection Records** (`/automation/records`): Archive of inspection runs with downloadable XLSX / HTML / PDF / JSON reports.
- **Execution Schedules** (`/automation/schedules`): One-shot inspection plans within a defined time window.
- **Execution History** (`/automation/history`): Playbook execution history with per-device drill-down, raw output, rerun.
- **Scheduled Jobs** (`/automation/scheduled-jobs`): Recurring (cron / interval) automation jobs — backup, inspection, custom scripts.
- **Inspection Metrics** (`/automation/metrics`): Catalog of inspection probes (SNMP OID, CLI command, SSH script).
- **Parse Templates** (`/automation/textfsm`): TextFSM template manager for normalising vendor CLI output.
- **Operations / Scripts** (`/automation/scripts`): Submit / approve / publish workflow for shell, Python, and CLI scripts.
- *API Endpoints*: `/api/automation`, `/api/playbooks`, `/api/scheduled_jobs`, `/api/inspections`, `/api/textfsm_templates`

#### 9. Tickets / Change Orders (`/change-orders/...`)
- **New Order** (`/change-orders/new`): Wizard-driven change request — scenario, target devices, schedule, attachments.
- **My Todo / Group Todo / My Drafts / All Orders / My Focus / My Participated**: Filtered views over the change-order workflow.
- **Per-order detail**: Initial review → final approval → implementation with control-sheet enforcement, command preview, rollback plan, execution log.
- *API Endpoints*: `/api/change-orders`

#### 10. Capacity & Reports (`/capacity/...`)
- **Capacity** (`/capacity/analysis`): CPU / memory / interface utilisation trends, 30-day linear forecast, days-to-threshold risk score.
- **Reports** (`/capacity/reports`): KPI cards + trend charts + multi-sheet XLSX export.
- *API Endpoints*: `/api/capacity`, `/api/reports`

#### 11. Platform Management (`/management/...`)
- **Audit Logs** (`/management/audit`): Full operational audit trail — login, config change, automation execution, PAM session, deletion.
- **Users** (`/management/users`): User CRUD, role assignment (Administrator / Operator / Viewer), group membership, MFA seed.
- **Password Rotation** (`/management/credentials`): Vault-style scheduled password rotation for managed devices.
- *API Endpoints*: `/api/audit`, `/api/users`, `/api/system`

### Technology Stack

- **Frontend**: React 19, TypeScript, Vite, TailwindCSS, Recharts
- **Backend**: Python 3.10+, FastAPI, Uvicorn
- **Database**: PostgreSQL 17 (production) / SQLite (fallback)
- **Network Automation**: Netmiko, Scrapli, SNMP telemetry


### Production Pre-flight Checklist

Before exposing the service to real users, walk through this list. The bundled `scripts/preflight-check.sh` script automates most of these checks and fails the deployment pipeline if anything is wrong.

```bash
cd /opt/nexora-automation
bash scripts/preflight-check.sh
```

The checklist itself:

1. **Replace every `__CHANGE_ME__*` value in `.env`** — `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `DATABASE_URL`. Use `openssl rand -hex 32` for the keys and `openssl rand -hex 16` for the DB password. The `deploy-ubuntu.sh` script does this on a fresh install; a manual `cp .env.example .env` does **not**.
2. **Change the default admin password** (`admin / admin`) to a strong one immediately after first login. The backend will refuse to boot in production mode if `SECRET_KEY` or `CREDENTIAL_ENCRYPTION_KEY` look like placeholders.
3. **Verify HTTPS** — Nginx must terminate TLS in production. Run `sudo certbot --nginx -d <your-domain>` after the first deploy if you have not already.
4. **Confirm the backend binds to loopback only** — the systemd unit shipped by `deploy-ubuntu.sh` uses `--host 127.0.0.1`. If you start the backend manually, set `HOST=127.0.0.1` so external traffic must come through Nginx.
5. **Install daily backups** — `sudo bash scripts/install-daily-backup.sh` writes a `pg_dump` cron job to `/etc/cron.daily/netops-backup` and keeps 30 days of compressed dumps under `/var/backups/netops/`.
6. **Install log rotation (container/bare-metal mode only)** — `sudo cp scripts/netops.logrotate /etc/logrotate.d/netops`. systemd installs go through journald and don't need this.
7. **Review the firewall** — only the Nginx port (80 / 443) and SSH should be reachable from outside; PostgreSQL (5432) must stay on `localhost`.
8. **Disable trial / test data** — if you ran any automated demo seed, remove its rows before going live.

> 中文版 checklist 见下方「上线前自检清单」。

---

### Deployment

> 📁 **Per-method deployment guides** are organized under [`docs/deploy/`](docs/deploy/README.md): [Windows](docs/deploy/windows.md) · [Docker](docs/deploy/docker.md) · [Ubuntu](docs/deploy/ubuntu.md). The sections below remain the canonical reference.

#### Option 1 — Windows One-Click GUI Deploy (Recommended for Windows)

You can deploy and run NetOps on Windows using the graphical manager:

1. Clone the **Windows-specific release branch** (`windows`) of the repository:
   ```powershell
   git clone -b windows https://github.com/libing28390-sketch/Release-netops.git nexora-automation
   cd nexora-automation
   ```
2. Double-click `start.bat` in the root folder.
3. The graphical setup wizard (`NetOps.exe`) will launch. It automatically detects, downloads, and silently installs all required runtimes (Python, Node.js, PostgreSQL/SQLite, and Python packages) and boots up the platform.
4. Once completed, your browser will open to `http://127.0.0.1:5010`. You can monitor and control the application using the network topology system tray icon in the taskbar.

After installation, open the desktop manager's **About** page and click **Check for Updates**. The client checks the public Windows Releases, downloads a newer `NetOps.exe` in the background, then closes, replaces the executable, and restarts automatically. This requires a published Windows Release containing the `NetOps.exe` asset.

---

#### Option 2 — Ubuntu One-Click (Recommended for Linux)

Supports Ubuntu 20.04 / 22.04 / 24.04, GitHub Codespaces, and Docker containers.
The script auto-detects the environment and uses `systemd` or `service` accordingly.

**On a fresh server (nothing pre-installed):**

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

**Inside an existing cloned directory:**

> **Interactive Customization & Environment Configuration:**
> The deployment script features an elegant interactive startup wizard with a 10-second auto-timeout. When running the script, you will be interactively prompted to customize key environment settings:
> - Custom PostgreSQL password (or auto-generate)
> - Custom backend API port (default: 8003)
> - Custom Nginx public port (default: 80)
> 
> Alternatively, you can pre-configure your `.env` file manually (`cp .env.example .env`). The deployment script will detect and preserve any existing custom settings.

```bash
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

The script handles everything automatically:
- Installs system dependencies (Python, Node.js 22, Nginx, PostgreSQL)
- Clones/Updates repository from GitHub (`https://github.com/libing28390-sketch/Release-netops.git`)
- Interactively prompts for custom database credentials & ports
- Creates a Python virtual environment and installs all dependencies
- Builds the frontend production bundle
- Generates `.env` with random encryption keys
- Configures Nginx as a reverse proxy on your selected port
- Registers and starts the backend as a systemd service (or background process in containers)

After deployment, access the platform at `http://<server-ip>:<nginx-port>`.

Default credentials: `admin / admin` — **change immediately after first login.**

---

#### Option 3 — Docker Compose

Requires Docker and Docker Compose. Includes PostgreSQL, backend, and Nginx in one stack.

##### Step 1: Clone repository and prepare environment file
```bash
git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
cd nexora-automation

# The script creates .env, generates missing secrets, builds the images,
# and starts PostgreSQL, NetOps, and Nginx.
bash scripts/deploy-docker.sh install
```

Before exposing the service publicly, review `.env` and configure:
- Custom PostgreSQL passwords/usernames.
- Security keys (`SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`).
- Set `TLS_COMMON_NAME` to the deployment domain or server IP. If no certificate is supplied, Docker generates a self-signed fallback certificate on startup; replace it with a trusted certificate for production.

Access the application at `https://localhost`. The browser will warn about trust when Docker generated the fallback self-signed certificate.

The Docker project is named `nexora`. It creates `nexora-netops`, `nexora-nginx`, and `nexora-db` containers, `nexora-netops` / `nexora-nginx` build images, and `nexora-data`, `nexora-backup`, `nexora-pgdata`, and `nexora-dist` volumes. The Compose service key `netops` and PostgreSQL database name `netops` remain unchanged for application compatibility.

##### Updating an existing Docker deployment

The public release repository is rebuilt with a sanitized Git history, so a normal `git pull` may fail after a release. The helper below explicitly switches `origin` to `https://github.com/libing28390-sketch/Release-netops.git` before synchronizing. It discards changes to tracked source files; `.env`, Docker volumes, and files under `nginx/ssl/` are preserved. A timestamped `.env` backup is created automatically. The script compares the source tree before rebuilding, so an unchanged release skips image pulls, builds, and container recreation. Add `--force` when a full rebuild is required.

```bash
cd /path/to/nexora-automation
bash scripts/deploy-docker.sh update

# Optional: force a full image rebuild and container recreation
bash scripts/deploy-docker.sh update --force
```

Do not run `docker compose down -v` during an upgrade: `-v` deletes the PostgreSQL, application-data, and backup volumes.

To intentionally reset this Compose project's containers, volumes, local build images, and generated TLS files, then install from the latest public release again:

```bash
bash scripts/deploy-docker.sh reset-data --yes
bash scripts/deploy-docker.sh install
```

**Common Docker commands:**

```bash
docker compose up -d --build     # Build and start
docker compose down              # Stop all containers
docker compose logs -f netops    # Backend logs
docker compose logs -f nginx     # Nginx logs
docker compose restart netops    # Restart backend
```

---

#### Option 4 — Manual Setup

**Prerequisites:** Node.js 18+, Python 3.10+, PostgreSQL 17

> [!NOTE]
> For Windows native deployment, it is highly recommended to clone the Windows-specific branch to get Windows-specific tray control tools (e.g. `NetOps.exe`):
> `git clone -b windows https://github.com/libing28390-sketch/Release-netops.git nexora-automation`

```bash
git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
cd nexora-automation

# Python environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

# Frontend
npm install
npm run build

# Environment
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, CREDENTIAL_ENCRYPTION_KEY

# Start
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8003
```

---

### Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | SQLite fallback |
| `SECRET_KEY` | Session signing key — **must be changed** | placeholder |
| `CREDENTIAL_ENCRYPTION_KEY` | Device credential encryption key — **must be changed** | placeholder |
| `ENVIRONMENT` | `production` or `development` | `development` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `*` in dev |
| `MACHINE_ID_OVERRIDE` | Override machine fingerprint (Docker/Cloud) | auto-detected |
| `LICENSE_FILE_PATH` | Path to license.json | `data/license.json` |
| `ALERT_NOTIFY_WEBHOOK_URL` | Webhook for alert notifications | empty |
| `PLATFORM_URL` | "Go to platform" button URL in alerts | empty |
| `TELEMETRY_RAW_RETENTION_HOURS` | Raw telemetry retention (hours) | `48` |
| `TELEMETRY_ROLLUP_RETENTION_DAYS` | Aggregated telemetry retention (days) | `365` |

---

### Project Structure

```text
nexora-automation/
├── backend/
│   ├── api/                  # REST API routes
│   ├── core/                 # Config, logging, RBAC
│   ├── drivers/              # Device drivers (Netmiko / Scrapli)
│   ├── engine/               # Automation execution engine
│   ├── models/               # Database models
│   ├── schemas/              # Pydantic schemas
│   ├── services/             # Business services (SNMP, alerts, etc.)
│   ├── database.py           # PG / SQLite dual-backend
│   ├── main.py               # FastAPI entrypoint
│   └── requirements.txt
├── src/                      # React frontend source
├── nginx/                    # Nginx config for Docker deployment
├── data/                     # Runtime data (license.json, logs)
├── backup/                   # Configuration backup storage
├── deploy-ubuntu.sh          # Ubuntu / Codespaces one-click deploy
├── docker-compose.yml        # Docker stack (PG + backend + Nginx)
├── Dockerfile
├── .env.example
├── package.json
└── vite.config.ts
```

---

## 中文说明

> 完整的系统要求（操作系统、软件、硬件、网络）请参阅上方 [System Requirements / 系统要求](#system-requirements--系统要求) 章节。

### 主要功能

平台分为 **11 个模块**，与导航菜单一一对应：

#### 1. 实时监控（`/monitor/...`）
- **运营总览**（`/monitor/overview`）：运维看板 — 设备状态、最近自动化作业、即将进行的任务、合规 KPI。
- **监控中心**（`/monitor/telemetry`）：NOC 指挥中心 — 平台宿主机遥测、CPU/内存/磁盘性能趋势图、实时告警流。
- **服务器监控**（`/monitor/servers`）：单机服务器 SSH/Shell 遥测 — CPU、内存、磁盘、关键服务。
- **网络监控**（`/monitor/networks`）：单机网络设备 SNMP/CLI 遥测 — 接口流量、错包、丢包。
- **网络拓扑**（`/monitor/topology`）：LLDP/CDP 自动发现的物理链路图，支持拖拽布局。
- *后端 API 接口*：`/api/health`、`/api/monitoring`、`/api/device_health`、`/api/topology`

#### 2. 终端接入（`/access/...`）
- **操作工作台**（`/access/workspace`）：资产统一入口 — 通过受控 PAM 代理打开 Web SSH 会话。
- **受控审计**（`/access/pam-audit`）：实时活动会话监控 + 历史归档，含命令审计与 asciinema 录像回放。
- *后端 API 接口*：`/api/access`、`/api/pam`

#### 3. 告警处置（`/alerts/...`）
- **告警中心**（`/alerts/desk`）：实时告警工作台，支持指派、确认、解决工作流。
- **历史告警**（`/alerts/history`）：已关闭告警归档，支持过滤与导出。
- **告警规则**（`/alerts/rules`）：CPU/内存/接口/温度/主机等阈值与触发规则管理。
- **维护期**（`/alerts/maintenance`）：维护窗口管理，变更期间静默告警。
- *后端 API 接口*：`/api/alerts`

#### 4. 资产与配置（`/assets/...`）
- **资产管理**（`/assets/dashboard`）：物理资产台账 — 厂商、型号、序列号、生命周期状态、位置。
- **网络设备**（`/assets/devices`）：逻辑设备列表，含平台、状态、凭据，支持服务端分页。
- **服务器**（`/assets/servers`）：Linux / Windows 服务器清单。
- **NPA 智能路径诊断**（`/assets/diagnose`）：多跳转发路径性能探测与拓扑展示。
- **网络事实库**（`/assets/nsot`）：网络配置与数据源单一真实性源。
- **IP 工具箱**（`/assets/toolbox`）：IP 定位（找出某 IP 落在哪个交换机端口）、连通性探测、ARP 缓存、MAC 变更历史。
- **标签管理**（`/assets/tags`）：标签分类系统 — 厂商、位置、角色、环境，跨平台复用。
- *后端 API 接口*：`/api/assets`、`/api/devices`、`/api/ip_locator`、`/api/tags`

#### 5. CMDB 基础数据（`/cmdb/...`）
- **凭据中心**（`/cmdb/credentials`）：统一管理设备访问凭据（AES-256-GCM 硬件加密存储）。
- **机柜管理**（`/cmdb/racks`）：2D 机架可视化，U 位拖拽，电力 / 空间核算。
- **站点管理**（`/cmdb/sites`）：管理设备所在数据中心与站点分布。
- **VRFs 管理**（`/cmdb/vrfs`）：Logical 设备 VRF 实例配置。
- **VLANs 管理**（`/cmdb/vlans`）：CMDB 中的 VLAN 配置与子网关系。
- **租户管理**（`/cmdb/tenants`）：实现多租户资源隔离与所有权限制。
- *后端 API 接口*：`/api/credentials`、`/api/racks`、`/api/cmdb`

#### 6. IP 地址管理（`/ipam/...`）
- **Prefix管理**（`/ipam/prefixes`）：子网分配树形层级管理。
- **IP地址**（`/ipam/ips`）：具体 IP 地址登记、空闲检测与利用率。
- **地址池**（`/ipam/pools`）：动态 IP 分配池。
- **VIP管理**（`/ipam/vips`）：虚 IP 绑定记录。
- **DHCP租约**（`/ipam/dhcp`）：动态 DHCP 租用记录展示。
- **利用率分析**（`/ipam/utilization`）：IP 段消耗进度条与容量规划。
- **IP对账中心**（`/ipam/reconciliation`）：冲突检测、活跃度扫描与异常对账。
- *后端 API 接口*：`/api/ipam`

#### 7. 配置管理（`/config/...`）
- **备份中心**（`/config/backup`）：手动 / 即时备份 running-config，快照浏览，按设备查看历史。
- **备份计划**（`/config/schedule`）：基于 cron 的周期性备份作业，含执行日志。
- **配置对比**（`/config/diff`）：任意两个快照的并列 / 统一 diff，行级彩色差异。
- **配置搜索**（`/config/search`）：全量快照（所有设备 × 所有版本）的全文 grep。
- **配置模板**（`/config/templates`）：多厂商配置模板库，支持变量替换与回滚指令。
- *后端 API 接口*：`/api/configs`、`/api/templates`、`/api/config_drift`

#### 8. 自动化（`/automation/...`）
- **自动化任务**（`/automation/tasks`）：直接执行 + Quick Playbook + 场景库，WebSocket 实时返回每台设备输出。
- **巡检概览**（`/automation/inspections`）：按需触发网络健康巡检，全网快照视图。
- **巡检记录**（`/automation/records`）：巡检执行历史归档，可下载 XLSX / HTML / PDF / JSON 报表。
- **执行计划**（`/automation/schedules`）：在指定时间窗口内执行的一次性巡检计划。
- **执行历史**（`/automation/history`）：Playbook 执行历史，可下钻到单台设备、查看原始输出、重跑。
- **定时作业**（`/automation/scheduled-jobs`）：周期性（cron / interval）自动化作业 — 备份、巡检、自定义脚本。
- **巡检指标**（`/automation/metrics`）：巡检探针目录（SNMP OID / CLI 命令 / SSH 脚本）— 定义"健康"在每个平台的具体含义。
- **解析模板**（`/automation/textfsm`）：TextFSM 模板管理，将厂商 CLI 输出标准化。
- **操作管理**（`/automation/scripts`）：Shell / Python / CLI 脚本的提交→审核→发布全流程。
- *后端 API 接口*：`/api/automation`、`/api/playbooks`、`/api/scheduled_jobs`、`/api/inspections`、`/api/textfsm_templates`

#### 9. 工单管理（`/change-orders/...`）
- **新建工单**（`/change-orders/new`）：向导式变更申请 — 场景、目标设备、排期、附件。
- **工单过滤筛选**：个人待办 / 组内待办 / 草稿箱 / 全部工单 / 我的关注 / 我参与的等多维视图。
- **工单详情**：初审 → 终审 → 实施全流程，含控制单强制项、命令预览、回滚方案、执行日志。
- *后端 API 接口*：`/api/change-orders`

#### 10. 容量与报表（`/capacity/...`）
- **容量分析**（`/capacity/analysis`）：CPU / 内存 / 接口利用率趋势，30 天线性预测，距阈值天数风险评分。
- **报表中心**（`/capacity/reports`）：KPI 卡片 + 趋势图表 + 多 Sheet XLSX 导出。
- *后端 API 接口*：`/api/capacity`、`/api/reports`

#### 11. 平台管理（`/management/...`）
- **审计日志**（`/management/audit`）：全量运维操作留痕 — 登录、配置变更、自动化执行、PAM 会话、删除操作。
- **用户管理**（`/management/users`）：用户增删改查，角色（Administrator / Operator / Viewer）与组管理，MFA 种子。
- **凭据轮换**（`/management/credentials`）：类 Vault 的设备口令周期性轮换。
- *后端 API 接口*：`/api/audit`、`/api/users`、`/api/system`

### 技术栈

- **前端**：React 19、TypeScript、Vite、TailwindCSS、Recharts
- **后端**：Python 3.10+、FastAPI、Uvicorn
- **数据库**：PostgreSQL 17（生产）/ SQLite（回退）
- **网络自动化**：Netmiko、Scrapli、SNMP 遥测采集


### 上线前自检清单

正式商用前请按以下清单逐项确认。仓库自带 `scripts/preflight-check.sh` 脚本可自动检测大部分项，并在发现问题时返回非 0 退出码（适合接入 CI / 发布流水线）：

```bash
cd /opt/nexora-automation
bash scripts/preflight-check.sh
```

清单本身：

1. **替换 `.env` 中所有 `__CHANGE_ME__*` 占位符**：`SECRET_KEY`、`CREDENTIAL_ENCRYPTION_KEY`、`POSTGRES_PASSWORD`、`DATABASE_URL`。两个 key 用 `openssl rand -hex 32` 生成，数据库密码用 `openssl rand -hex 16`。`deploy-ubuntu.sh` 全新部署时会自动生成；手工 `cp .env.example .env` 则**不会**。
2. **首次登录立即改 admin 密码**：默认 `admin / admin`，强口令替换后再开放访问。后端在 `ENVIRONMENT=production` 模式下检测到 key 仍是占位符会**拒绝启动**。
3. **启用 HTTPS**：生产环境必须用 Nginx 终结 TLS。首次部署后跑 `sudo certbot --nginx -d <你的域名>`。
4. **确认后端绑定回环地址**：`deploy-ubuntu.sh` 写入的 systemd 单元已经是 `--host 127.0.0.1`；手工启动则需 `HOST=127.0.0.1`，外部流量必须走 Nginx。
5. **安装每日备份**：`sudo bash scripts/install-daily-backup.sh` 会写入 `/etc/cron.daily/netops-backup`，每天 `pg_dump` 到 `/var/backups/netops/`，保留 30 天。
6. **安装日志轮转（容器 / 裸机模式）**：`sudo cp scripts/netops.logrotate /etc/logrotate.d/netops`。systemd 安装走 journald，无需配置。
7. **检查防火墙**：仅放行 Nginx 端口（80 / 443）和 SSH；PostgreSQL（5432）必须只监听 `localhost`。
8. **清理试用数据**：如果运行过 demo seed，上线前删除相关测试数据。

---

### 部署方式

> 📁 **按部署方式拆分的导航指南**见 [`docs/deploy/`](docs/deploy/README.md)：[Windows](docs/deploy/windows.md) · [Docker](docs/deploy/docker.md) · [Ubuntu](docs/deploy/ubuntu.md)。下方各小节仍是权威说明。

> [!IMPORTANT]
> **中国大陆部署建议 / Network Optimization for China Mainland:**
> 由于国内网络限制，在部署过程中可能会遇到 APT、npm、pip 或 Docker 镜像拉取超时。本项目已在 Docker 构建阶段默认内置了国内镜像源（USTC/Aliyun/npmmirror）。若在宿主机上手动部署或遇到 Docker 镜像拉取超时（`context deadline exceeded`），请务必参考 [DEPLOY.md 中的中国大陆网络优化说明](DEPLOY.md#network-optimizations-for-mainland-china---中国大陆部署网络优化) 配置国内镜像加速器。

#### 方式一 — Windows 一键图形化部署（Windows 推荐）

您可以在 Windows 系统上通过专属的图形化部署管理器一键完成安装和运行：

1. 克隆发布库的 **Windows 专属发布分支** (`windows`)：
   ```powershell
   git clone -b windows https://github.com/libing28390-sketch/Release-netops.git nexora-automation
   cd nexora-automation
   ```
2. 双击运行根目录下的 `start.bat`。
3. 系统会自动调起图形部署向导（`NetOps.exe`），自动检测并静默下载、安装全部所需环境（Python、Node.js、PostgreSQL/SQLite 数据库及各端依赖包），并自动完成前端编译与平台启动。
4. 部署完成后，系统会自动打开默认浏览器并访问 `http://127.0.0.1:5010`。后续您可以通过系统右下角托盘图标进行日常控制与退出。

---

#### 方式二 — Ubuntu 一键部署（Linux 推荐）

支持 Ubuntu 20.04 / 22.04 / 24.04、GitHub Codespaces 及 Docker 容器环境。
脚本自动检测运行环境，在标准系统中使用 `systemd`，在容器中使用 `service` + 后台进程。

**全新服务器（什么都不用预装）：**

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

**已克隆项目目录内执行：**

> **交互式环境引导与配置自定义（全新亮点）：**
> 本一键部署脚本内置带 10 秒倒计时自动保护的交互式向导！在执行脚本启动时，支持直接在命令行终端交互式自定义：
> - 自定义 PostgreSQL 数据库密码（或留空自动生成强密码）
> - 自定义后端 API 监听端口（默认 8003）
> - 自定义外部 Nginx 代理访问端口（默认 80）
> 
> 此外，您也可以在执行前将 `.env.example` 复制为 `.env` 并提前填入自定义变量。部署脚本会自动检测并完美继承您的既有环境配置！

```bash
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

脚本自动完成以下所有步骤：
- 安装系统依赖（Python、Node.js 22、Nginx、PostgreSQL）
- 自动从 GitHub 极速源拉取/同步最新代码 (`https://github.com/libing28390-sketch/Release-netops.git`)
- 交互式询问并注入数据库口令及监听端口
- 创建 Python 虚拟环境并安装全部依赖
- 构建前端生产版本
- 自动生成 `.env`，随机生成各类加密密钥
- 配置 Nginx 反向代理（监听您选择的外部端口）
- 注册并启动后端服务（systemd 服务或容器后台进程）

部署完成后访问 `http://<服务器IP>:<Nginx访问端口>`。

默认账号：`admin / admin`，**首次登录后请立即修改密码。**

---

#### 方式三 — Docker Compose 部署

包含 PostgreSQL、后端、Nginx 三个容器，无需安装 Node.js/npm/Python 等环境，一条命令启动完整环境。

##### 第一步：克隆项目并准备环境文件
```bash
git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
cd nexora-automation

# 拷贝环境配置模版
cp .env.example .env
```

打开 `.env` 文件，配置如下参数：
- 数据库连接信息 (`POSTGRES_USER`, `POSTGRES_PASSWORD` 等)
- 安全密钥 (`SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`)
- 将 `TLS_COMMON_NAME` 设置为部署域名或服务器 IP。如果没有提供证书，Docker 会在启动时自动生成自签名备用证书；生产环境请替换为可信证书。

##### 第二步：启动所有容器
```bash
# 脚本会自动初始化 .env、构建镜像并启动所有容器
bash scripts/deploy-docker.sh install
```
启动后，可通过浏览器访问 `https://localhost`。使用 Docker 自动生成的自签名证书时，浏览器会显示信任警告。

##### 更新已有 Docker 部署

公开发布仓库每次发布都会使用经过脱敏的新 Git 历史，因此普通的 `git pull` 在发布后可能失败。请在现有部署目录中执行以下命令。`git reset --hard` 会覆盖已跟踪源码的本地修改，但不会删除 `.env`、Docker 数据卷以及 `nginx/ssl/` 下的证书文件。

```bash
cd /path/to/nexora-automation

# 可选：备份本地环境配置
cp .env .env.backup

# 将已跟踪源码同步为公有仓库最新版本；无源码变化时会跳过构建和重建容器
bash scripts/deploy-docker.sh update

# 如需强制重新构建镜像并重建容器
bash scripts/deploy-docker.sh update --force

# 检查升级后的容器和日志
docker compose ps
docker compose logs --tail=100 netops nginx
```

升级时不要执行 `docker compose down -v`：`-v` 会删除 PostgreSQL、应用数据和备份数据卷。

**常用 Docker 命令：**

```bash
docker compose up -d --build     # 构建并启动
docker compose down              # 停止所有容器
docker compose logs -f netops    # 查看后端日志
docker compose logs -f nginx     # 查看 Nginx 日志
docker compose restart netops    # 重启后端
```

---

#### 方式四 — 手动部署

**前置条件**：Node.js 18+、Python 3.10+、PostgreSQL 17

> [!NOTE]
> 对于 Windows 本地部署，强烈建议克隆 Windows 专属分支以获取桌面托盘管理程序（如 `NetOps.exe`）：
> `git clone -b windows https://github.com/libing28390-sketch/Release-netops.git nexora-automation`

```bash
git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
cd nexora-automation

# Python 环境
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

# 前端
npm install
npm run build

# 环境配置
cp .env.example .env
# 编辑 .env：设置 DATABASE_URL、SECRET_KEY、CREDENTIAL_ENCRYPTION_KEY

# 启动
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8003
```

---

### 环境变量说明

将 `.env.example` 复制为 `.env` 后按需修改：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | 回退到 SQLite |
| `SECRET_KEY` | 会话签名密钥，**必须修改** | 占位符 |
| `CREDENTIAL_ENCRYPTION_KEY` | 设备凭据加密密钥，**必须修改** | 占位符 |
| `ENVIRONMENT` | `production` 或 `development` | `development` |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔） | 开发模式为 `*` |
| `MACHINE_ID_OVERRIDE` | 覆盖机器指纹（Docker/云环境使用） | 自动检测 |
| `LICENSE_FILE_PATH` | license.json 文件路径 | `data/license.json` |
| `ALERT_NOTIFY_WEBHOOK_URL` | 告警通知 Webhook 地址 | 空 |
| `PLATFORM_URL` | 告警通知中"前往平台"按钮跳转地址 | 空 |
| `TELEMETRY_RAW_RETENTION_HOURS` | 原始遥测数据保留时长（小时） | `48` |
| `TELEMETRY_ROLLUP_RETENTION_DAYS` | 聚合遥测数据保留时长（天） | `365` |

---

### 目录结构

```text
nexora-automation/
├── backend/
│   ├── api/                  # REST API 路由
│   ├── core/                 # 配置、日志、RBAC
│   ├── drivers/              # 设备驱动（Netmiko / Scrapli）
│   ├── engine/               # 自动化执行引擎
│   ├── models/               # 数据模型
│   ├── schemas/              # Pydantic 模型
│   ├── services/             # 业务服务（SNMP、告警等）
│   ├── database.py           # PG / SQLite 双后端
│   ├── main.py               # FastAPI 启动入口
│   └── requirements.txt
├── src/                      # React 前端源码
├── nginx/                    # Docker 部署 Nginx 配置
├── data/                     # 运行时数据（license.json、日志）
├── backup/                   # 配置备份存储
├── deploy-ubuntu.sh          # Ubuntu / Codespaces 一键部署脚本
├── docker-compose.yml        # Docker 编排（PG + 后端 + Nginx）
├── Dockerfile
├── .env.example
├── package.json
└── vite.config.ts
```

---

### 常见问题

**Q: 部署脚本在 GitHub Codespaces 或容器里失败，提示 systemd 不可用？**

脚本已自动检测容器环境，会切换到 `service` 命令启动 PostgreSQL，并以 `nohup` 后台进程方式运行后端。如果仍然失败，请确认使用的是最新版本的 `deploy-ubuntu.sh`。

**Q: 如何查看后端运行日志？**

- systemd 环境：`sudo journalctl -u netops -f`
- 容器/Codespaces：`tail -f data/netops.log`
- Docker：`docker compose logs -f netops`

**Q: 如何升级到新版本？**

```bash
# Ubuntu systemd 部署
cd /opt/nexora-automation
git pull
npm install && npm run build
pip install -r backend/requirements.txt
sudo systemctl restart netops

# Docker 部署
cd /path/to/nexora-automation
bash scripts/deploy-docker.sh update

# Windows 本地部署 (GUI)
# 1. 右键系统托盘图标，点击“退出 (Exit)”以完全关闭运行中的服务。
# 2. 在项目根目录执行以下命令拉取最新代码（会自动下载最新 NetOps.exe）：
git pull
# 3. 重新双击运行根目录下的 `start.bat` 即可，图形化向导会自动处理后续的环境校验与启动。
```
