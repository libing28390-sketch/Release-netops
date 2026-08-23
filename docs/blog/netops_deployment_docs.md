# Nexora NetOps 部署与集成深度解析指南（Windows / Docker）

本指南旨在详细梳理 **Nexora NetOps** 在 Windows 本地环境以及 Linux Docker Compose 生产环境的部署架构、安装步骤、自动化机制、常见问题及高级配置。系统在生产和部署环境中**一律采用 PostgreSQL** 作为核心关系数据库。

---

## 一、 系统架构与部署方案总览

在正式开始之前，我们需要了解 Nexora 的基本服务构成：

```
                    ┌──────────────────────────┐
                    │        用户浏览器          │
                    └─────────────┬────────────┘
                                  │
                                  ▼ (Port 80/443 或 5010)
                    ┌──────────────────────────┐
                    │      Nginx / Web 代理    │
                    └──────┬─────────────┬─────┘
                           │             │
         (静态资源 /assets) │             │ (反向代理 /api /api/ws)
                           ▼             ▼
                    ┌────────────┐ ┌───────────┐
                    │ 前端静态包 │ │  FastAPI  │
                    │ (React 19) │ │  Backend  │
                    └────────────┘ └─────┬─────┘
                                         │
                                         ▼ (Port 5432)
                                   ┌───────────┐
                                   │  数据库   │
                                   │ (Postgres)│
                                   └───────────┘
```

根据运行环境及使用场景，平台主要提供以下三种部署方式：

| 部署方式 | 适合场景 | 关键入口文件/目录 | 数据库选项 | 特点 |
| :--- | :--- | :--- | :--- | :--- |
| **Windows 图形化/一键部署** | 个人电脑、本地实验、Windows 裸机、小团队，希望零门槛一键双击运行。 | `NetOps.exe`（兼容入口）, `start.bat`, `desktop/` | PostgreSQL 17 + `pgvector` + `pg_trgm` | **Nexora PySide6 托盘及暗黑模式向导**。自动安装/检测运行依赖；PostgreSQL 扩展需要预先安装，向导负责登录、建库并校验扩展。 |
| **Docker Compose 容器部署** | Linux 服务器、生产环境、云原生部署，希望隔离服务且易于维护。 | `docker-compose.yml`, `Dockerfile`, `scripts/deploy-docker.sh` | PostgreSQL 17 | **三容器架构一键拉起**。支持在线构建，也支持镜像归档后离线导入，内置 HTTPS 加密和卷级持久化。 |
| **Ubuntu 一键脚本部署** | Ubuntu 裸机服务器，想要以 Nginx 反向代理 + systemd 原生服务运行。 | `deploy-ubuntu.sh` | PostgreSQL | **Shell 脚本交互式向导**。自动化配置系统包、虚拟环境、SSL、systemd 服务以及 logrotate 等。 |

---

## 二、 Windows 本地部署与桌面集成（Desktop Integration）

Windows 部署支持两种主流模式：**小白用户的图形向导一键部署**，以及**运维人员的命令行桌面集成模式**。其核心亮点在于深度适配了 Windows 托盘及自服务机制。

### 1. 专属分支准备
由于 Windows 包含桌面端全部源码和托盘工具资产，建议使用专门的 `windows` 分支：
* **GitHub 克隆**：
  ```powershell
  git clone -b windows https://github.com/libing28390-sketch/Release-netops.git nexora-automation
  cd nexora-automation
  ```
* **Gitee 国内镜像克隆**（访问更快）：
  ```powershell
  git clone -b windows https://gitee.com/leerbon/netops.git nexora-automation
  cd nexora-automation
  ```

---

### 2. 模式 A：Windows 一键图形化向导（推荐）

#### ① 运行入口
双击项目根目录下的 **`NetOps.exe`** （历史兼容文件名，界面品牌为 Nexora），或双击运行 `start.bat`。

#### ② 自动向导流程（Dark-Mode Setup Wizard）
如果是首次启动，`NetOps.exe` 将会弹出基于 **PySide6 编写的 premium 精美暗黑风格图形部署向导**：
1. **运行环境检测**：向导会自动校验本地环境，支持兼容的 Python 版本范围（`3.10` ~ `3.12`，含两端）以及 Node.js 版本（`18+`）。如果检测到未安装，向导会提供一键下载并静默部署 Fallback 包（如 Python 3.11.9）。
2. **数据库配置**：平台强制绑定 **PostgreSQL 17.x**。若本地 `5432` 未响应，向导可以下载并静默安装官方 PostgreSQL 17.2；该安装包不包含 `pgvector`。用户需要另外安装与 PG17 匹配的 `pgvector`，并确保 `pg_trgm` 可用。向导会实际登录数据库，缺库时尝试建库，再创建/校验这两个扩展。
3. **依赖构建**：自动在本地创建 Python 虚拟环境（`.venv`），利用虚拟环境的 `pip` 安装 `backend/requirements.txt`；同时自动调用 `npm ci --include=dev` 并运行前端编译流程（`npm run build`）。
4. **服务启动与浏览器拉起**：向导环境验证完成后，在完成页点击“启动平台客户端”，系统开启后台托盘并打开默认浏览器访问 `http://127.0.0.1:5010`。
5. **后续使用**：下次启动 `NetOps.exe` 时，系统会复用已存在的 `.venv` 和 `.env`，重新验证数据库并同步 Nexora 桌面快捷方式，然后启动客户端。

---

### 3. 模式 B：手动命令行部署与快捷启动

如果您是技术栈人员，希望以命令行前台或注册本地托盘运行，可以按照以下步骤手动操作：

#### ① 依赖环境初始化
1. 确保安装了 Python 3.10-3.12、Node.js 20+、PostgreSQL 17.x，以及与 PG17 匹配的 `pgvector` 和 `pg_trgm`。
2. 创建虚拟环境并安装 Python 包：
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r backend/requirements.txt
   ```
3. 构建前端资源：
   ```powershell
   npm ci --include=dev
   npm run build
   ```
4. 数据库配置：在项目根目录复制生成 `.env` 文件，并正确配置 `DATABASE_URL` 指向您的 PostgreSQL 实例：
   ```env
   DATABASE_URL=postgresql://netops:your-password@localhost:5432/netops
   ```

#### ② 启动方式
当前 `start.bat` 不再提供旧版的 `[1]/[2]` 交互菜单：它优先启动根目录的 `NetOps.exe`，不存在时再回退到 `.venv` 或系统 Python 执行 `desktop/launcher.py`。首次完成配置后，向导会尝试创建 **“Nexora 运维平台”** 桌面快捷方式。

如果需要前台查看日志，可直接使用兼容的 `NetOps.exe` 启动器并查看向导日志；不要把旧文档中的 `[1]/[2]` 选择当作当前流程。

---

### 4. 桌面托盘控制面板（`desktop_tray.py`）

右键托盘图标可以拉起 Enterprise 级别的托盘控制面板（900x620 大屏 Fluent Design 亚克力半透明风格布局），核心功能如下：
* **一键诊断套件**：提供诊断日志收集，点击后自动将系统日志、数据库基本信息及状态打包成 zip，方便排障。
* **实时日志过滤**：可在托盘界面中直接查看后端运行日志，支持日志级别及关键字过滤。
* **开机自启动配置**：可在托盘偏好设置中一键配置或取消 Windows 注册表开机自启 (`winreg` 控制)。
* **数据库清理与恢复出厂**：
  * 清理数据会对 `DATABASE_URL` 对应的 PostgreSQL 数据库执行重建还原。
  * 系统会强行先调用 `pg_dump` 备份，备份成功才执行清理，备份文件保存在 `data/backups/database-reset/`。
  * 拒绝清理系统预置库（如 `postgres`、`template0` 等），仅重建 `public` schema 空间，不影响本地物理文件、授权文件及 `.env`。
  * 重建后默认管理员账号重置为 `admin / admin`。

---

### 4. Windows 用户升级与网络同步

Windows 有两种升级路径，范围不同：

* **完整升级（推荐）**：退出托盘程序并备份 PostgreSQL 后，使用 `git pull origin windows` 或最新 `NetOps-Windows.zip`。保留 `.env`、`data/`、`backup/` 和 `desktop/desktop_settings.ini`，让新包覆盖 `backend/`、`desktop/`、`src/` 和 `NetOps.exe`；有效的 `.venv` 可以复用，但如果 `backend/requirements.txt` 发生变化，需要重新安装依赖；后端启动时会执行未完成的数据库迁移。
* **托盘“检查更新”**：当前直接访问 GitHub Releases API，下载 GitHub Release 中的 `NetOps.exe`，只替换启动器。它不会同步后端、前端、托盘脚本或数据库迁移，不能代替完整升级。

GitHub 在线更新在国内网络环境下可能因 DNS、连接超时、代理或 TLS 拦截失败。更新失败时不会替换当前客户端，建议改用可访问的 Windows ZIP/内部制品包；若所在环境维护了同步的 Gitee `windows` 分支，也可以在该来源执行 `git pull origin windows`。当前发布工作流不会自动把 Release 同步到 Gitee，Gitee 是否有最新 Windows 分支需要发布人员单独确认。构建流程在配置了 `BAIDU_PAN_TOKEN` 时还会把 Windows ZIP 上传到百度网盘，可作为离线分发来源。

## 三、 Linux Docker Compose 生产部署

对于需要多厂商适配、大规模资产巡检、自动化诊断和高稳定性的生产环境，推荐采用 Docker Compose 方案。

### 1. 容器服务构成

Nexora 在 Docker 编排中采用三容器解耦架构：

| 容器名称 | 镜像来源 | 对外/对内端口 | 挂载卷/说明 |
| :--- | :--- | :--- | :--- |
| **`db`** | 本地 `docker/postgres/Dockerfile` 构建的 `nexora-postgres:latest`（pgvector + pg_trgm） | 内网监听 `5432` | 挂载 `nexora-pgdata` 卷，存储核心关系数据库数据。 |
| **`netops`** | 本地 `Dockerfile` 编译镜像 | 内部 `8003` | 挂载本地 `data/` 目录；运行基于 FastAPI 的后端业务逻辑。 |
| **`nginx`** | `nginx:1.27-alpine` | 宿主机映射 `80` (HTTP) / `443` (HTTPS) | 挂载 `nginx/nginx.conf` 及 SSL 目录，负责反向代理、WebSocket 代理和前端 React 静态资源分发。 |

---

### 2. 极速安装与部署

#### 步骤一：克隆仓库并初始化环境
```bash
git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
cd nexora-automation
cp .env.example .env
```

#### 步骤二：配置 `.env` 环境变量
编辑 `.env` 文件，生产环境**必须修改**以下安全敏感参数：
```env
# 1. 数据库配置
POSTGRES_USER=postgres
POSTGRES_PASSWORD=【在此输入高强度数据库密码】
POSTGRES_DB=netops

# 2. 安全加固（必须更换为随机的、长位数密钥）
SECRET_KEY=【在此生成高强度JWT加密密钥】
CREDENTIAL_ENCRYPTION_KEY=【在此生成32位资产凭据加密密钥】

# 3. 授权绑定（暂且留空，等第一步部署后获取 Machine ID 填入）
MACHINE_ID_OVERRIDE=
```

#### 步骤三：启动容器（使用自动化辅助脚本）
NetOps 提供了 `scripts/deploy-docker.sh` 用于规范化启动：
```bash
bash scripts/deploy-docker.sh install
```
*该命令会自动检查本地 Docker 环境、一键生成密钥证书目录、自动在前端容器内完成打包构建、拉取基础镜像并拉起服务。*

启动成功后，通过浏览器访问 `http://<服务器IP>`（或您配置的自定义端口）即可，初始账号密码为 `admin / admin`。

---

### 3. 

2. ```json
   
   }
   ```

---

### 4. 高级生产配置与管理

#### ① 证书配置 (HTTPS/SSL)
Docker 环境默认强制启用 HTTPS 访问。系统期望的证书存放路径为本地项目目录下的 `nginx/ssl/netops.crt` (证书) 和 `nginx/ssl/netops.key` (私钥)。
* **生成测试自签名证书**：
  若在内网测试或无 CA 证书，可执行以下命令快速生成强加密的测试证书：
  ```bash
  # 如果宿主机有 Python 虚拟环境
  .venv/bin/python scripts/generate_ssl_cert.py
  ```
* **配置自有企业 CA 证书**：
  直接将正式证书和私钥文件重命名为 `netops.crt` 和 `netops.key` 并移入 `nginx/ssl/`，然后执行以下命令应用：
  ```bash
  docker compose down
  docker compose up -d
  ```

#### ② 常用维护命令
```bash
docker compose up -d --build     # 重新编译前端/后端并拉起容器（升级用）
docker compose down              # 停止所有服务容器并释放网络
docker compose ps                # 查看容器运行状态与端口映射
docker compose logs -f netops    # 持续查看后端 FastAPI 业务日志
docker compose logs -f nginx     # 持续查看 Web Nginx 反向代理日志
docker compose restart netops    # 仅重启后端容器
```

#### ③ 安全升级流程
更新平台源码与镜像：
```bash
# 执行 Docker 一键安全更新脚本（脚本会自动留存您的 .env、容器卷与 nginx/ssl 证书文件，不丢失数据）
bash scripts/deploy-docker.sh update

# 如果需要强制无缓存全量重新构建镜像：
bash scripts/deploy-docker.sh update --force
```

#### ④ 数据重置 (Reset Data)
如果需要清空所有的本地容器、网桥、构建镜像及数据卷：
```bash
bash scripts/deploy-docker.sh reset-data
# 或者自动化执行（不进行交互式 y/n 确认）：
bash scripts/deploy-docker.sh reset-data --yes
```
> [!CAUTION]
> 重置操作是不可逆的，它会彻底删除 PostgreSQL 数据卷 `nexora-pgdata`。请谨慎在生产环境下操作。
