# Nexora Windows 一键部署

适合 Windows x64 本地部署。产品界面、托盘和向导统一使用 **Nexora** 品牌；现有 Windows 发布包仍使用 `NetOps.exe` 作为兼容启动文件名，`start.bat` 也会继续识别它。

Windows 客户端不需要预装 Docker。向导会准备 Python、完整 Node.js、Python 依赖和前端构建工具；本机 PostgreSQL 缺少 `pgvector` 时，还会自动下载匹配版本的预编译扩展、请求 UAC 管理员权限完成安装并重启 PostgreSQL 服务。

## 新机器要求

- Windows 10/11 64 位。
- 将发布目录放在当前用户可写的位置，例如 `C:\Nexora`，不要直接放到受限的 `Program Files` 目录。
- 首次部署需要网络访问 Python、Node.js、PyPI 和 PostgreSQL 下载地址，并允许 PostgreSQL 安装时的 UAC 提权。
- PostgreSQL 17.x（新安装由向导使用 PostgreSQL 17.6；已有 PostgreSQL 13–18 也可被识别）。
- 本机 PostgreSQL 不要求预先手工安装 `pgvector`；向导会按 PostgreSQL 主版本自动处理 `pgvector 0.8.6`，并检查 `pg_trgm`。
- 一个已创建的业务数据库（默认名称 `netops`）和可登录账号，或一个有 `CREATEDB` 权限、可以连接维护库 `postgres` 的账号。

Python 和 Node.js 可以由向导自动处理：

- Python：复用 3.10–3.12；没有兼容版本时下载 3.11.9。
- Node.js：仅在前端 `dist/` 不存在时复用系统 Node.js 22+；没有兼容版本时，向导会安装完整的官方 Node.js 22.22.2 x64 MSI，不再使用便携版 ZIP。
- Python 后端依赖以及 PySide6、Pillow、pystray 会安装到项目的 `.venv`，不会写入系统 Python 环境。

## PostgreSQL 初始化

当前向导新装的是 PostgreSQL 17.6，并会在本机 PostgreSQL 缺少 `vector` 时自动下载与主版本匹配的 `pgvector 0.8.6` Windows 资产。向导会在下载后校验固定 SHA-256，使用 UAC 管理员权限将 `vector.dll`、`vector.control` 和全部 `vector--*.sql` 复制到 PostgreSQL 安装目录，并重启对应服务。目标库不存在时，会在账号有 `CREATEDB` 权限且能连接维护库 `postgres` 的情况下创建目标库，然后自动创建 `vector` 和 `pg_trgm`。

Windows Release ZIP 会预置 PostgreSQL 17 的 pgvector 资产；如果是源码目录或使用单独的 `NetOps.exe`，向导会按 PostgreSQL 主版本从固定的 GitHub Release 地址下载。PostgreSQL 17.0–17.2 不适合当前 Windows pgvector 二进制，应先升级到 17.3 或更高版本；新装流程默认使用 17.6。

在 PostgreSQL 17 中按实际账号执行以下操作（可以使用 pgAdmin 或 `psql`）：

```sql
-- 如果数据库和账号已经存在，或准备让向导自动创建，请不要重复执行对应语句。
CREATE ROLE nexora LOGIN PASSWORD '替换为高强度密码';
CREATE DATABASE netops OWNER nexora;

\c netops
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

确认扩展和版本：

```sql
SELECT version();

SELECT name, default_version
FROM pg_available_extensions
WHERE name IN ('vector', 'pg_trgm')
ORDER BY name;
```

如果 `vector` 不在 `pg_available_extensions` 中，需要先安装与 PostgreSQL 版本匹配的 Windows pgvector 二进制包，再重启 PostgreSQL 服务。详细安装与排错步骤请参考 [Windows pgvector 安装与配置手册](./windows_pgvector_guide.md)。即使 AI 开关默认关闭，当前 PostgreSQL 迁移仍会检查 `vector` 和 `pg_trgm`。

## 安装步骤

1. 克隆 Windows 发布分支，或解压 Windows 发布包：

   ```powershell
   git clone -b windows https://github.com/libing28390-sketch/Release-netops.git nexora-automation
   cd nexora-automation
   ```

   国内网络可以使用：

   ```powershell
   git clone -b windows https://gitee.com/leerbon/netops.git nexora-automation
   ```

2. 如果是本机 PostgreSQL，直接继续即可：向导会检查服务，必要时安装 PostgreSQL 17.6，并自动安装匹配的 pgvector；如果是远程 PostgreSQL，请先由数据库管理员准备 `vector` 和 `pg_trgm`。
3. 双击根目录的 `NetOps.exe`，或运行 `start.bat`。
4. 在向导中选择 PostgreSQL，填写主机、端口、用户名、密码和数据库名。默认本机参数是 `127.0.0.1:5432 / netops`。
5. 向导会创建 `.venv`、安装依赖；如果 `dist/` 不存在，还会安装前端依赖并执行构建。
6. 部署完成后点击“启动平台客户端”，托盘程序会启动后端。浏览器访问 `http://127.0.0.1:5010`。
7. 默认账号为 `admin / admin`，首次登录后必须立即修改密码。

向导会把数据库配置写入项目根目录的 `.env`。生产或小团队环境还必须替换 `SECRET_KEY` 和 `CREDENTIAL_ENCRYPTION_KEY`，不要保留模板中的占位值。

## 远程 PostgreSQL

如果 Windows 只运行客户端、数据库在 Docker 或 Linux 服务器上，请在向导中填写远程 PostgreSQL 地址。向导检测到远程主机时不会在本机安装或修改 PostgreSQL；远程数据库仍必须具备受支持的 PostgreSQL、`vector`、`pg_trgm`，并已创建目标数据库。若扩展缺失，向导会明确提示数据库管理员处理。

## 验收检查

在目标数据库执行：

```sql
SELECT version();
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm')
ORDER BY extname;
SELECT MIN(version), MAX(version), COUNT(*) FROM schema_migrations;
```

预期结果是 PostgreSQL 17.x、两个扩展均存在，并且迁移版本达到当前发布版本。若启动日志出现 `POSTGRES_EXTENSION_MISSING`，优先检查 pgvector 是否安装到了 PostgreSQL 17 的目录，以及当前账号是否有 `CREATE EXTENSION` 权限。

Windows 后端实际监听 `0.0.0.0:5010`，浏览器默认使用 `127.0.0.1:5010`。只允许本机访问时，应使用 Windows 防火墙限制 5010 入站；需要局域网访问时再按实际网段放行。

## 日常使用与数据重置

- 日常双击 `NetOps.exe` 或 `start.bat`，已存在的 `.venv` 和 `dist/` 会复用。
- 右键托盘图标可以启动、停止或重启后端服务。
- “清理数据”只针对当前 `DATABASE_URL` 指向的业务数据库执行操作，不会删除附件、日志或 `.env`。
- PostgreSQL 模式下清理前必须创建 `pg_dump` 备份；清理完成后会重新执行迁移并恢复默认管理员 `admin / admin`。

## 已有 Windows 用户升级

### 推荐：完整发布包升级

本次平台升级可能包含后端代码、桌面托盘代码、数据库迁移和 `NetOps.exe`。因此推荐使用 Windows 分支或完整 Windows ZIP，不要只替换一个 exe：

1. 退出 Nexora 托盘程序，并确认后端服务已经停止。
2. 先备份数据库（PostgreSQL 使用 `pg_dump`），同时保留项目根目录的 `.env`、`data/`、`backup/` 和 `desktop/desktop_settings.ini`。
3. 如果目录来自 Git：

   ```powershell
   git pull origin windows
   ```

   如果使用 ZIP，则将新包解压到新目录，再把上述配置和数据文件复制过去；不要覆盖新包中的 `backend/`、`desktop/`、`src/` 和 `NetOps.exe`。

4. 重新运行 `start.bat` 或 `NetOps.exe`。向导会复用有效的 `.venv`，环境失效时重建；如果本次版本修改了 `backend/requirements.txt`，先执行 `.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`，再启动客户端。后端启动时会执行未完成的数据库迁移。
5. 登录后检查版本号和 AI/知识库功能；出现迁移或扩展错误时先不要执行“清理数据”。

### 托盘内“检查更新”的范围

“关于 → 检查更新”目前直接访问 `https://api.github.com/repos/libing28390-sketch/Release-netops/releases`，再从 GitHub Release 下载 `NetOps.exe`，通过临时 Windows `.cmd` 等待旧进程退出后重启。它会保留 `.env`、`.venv`、`data/` 和数据库，但**不会同步后端源码、托盘源码、前端资源或数据库迁移文件**，所以只能作为启动器补丁，不能代替完整平台升级。

这条在线链路没有内置 Gitee 自动切换或重试镜像。在中国大陆网络环境中，GitHub API 或 Release 下载可能受到 DNS、连接超时、代理策略和 TLS 检查影响，表现为检查失败或下载失败；下载失败时不会替换现有 `NetOps.exe`。此时使用最新 `NetOps-Windows.zip` 或企业内部制品包做完整升级；如果组织维护了同步的 Gitee `windows` 分支，也可以执行：

```powershell
git remote set-url origin https://gitee.com/leerbon/netops.git
git pull origin windows
```

注意：当前 GitHub Actions 只负责推送 GitHub Release 仓库，并不会自动同步 Gitee。Gitee 分支是否包含最新 Windows 构建，需要发布人员确认；配置了 `BAIDU_PAN_TOKEN` 的发布任务还会上传 Windows ZIP，可用于受限网络下的离线分发。客户端的“自动检查更新”设置目前不改变上述手动检查链路。

当前客户端版本为 `1.0.7`。如果托盘提示没有新版本，请使用最新 Windows ZIP 或执行 `git pull origin windows`；GitHub Release 尚未发布对应构建时，在线更新不会生效。

## 重新打包

在仓库根目录执行：

```powershell
pyinstaller NetOps.spec
```

产物为 `dist/NetOps.exe`。该文件名是历史兼容入口，客户端界面和产品名称均为 Nexora。
