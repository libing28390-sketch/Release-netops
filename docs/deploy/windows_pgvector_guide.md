# Windows 环境下 PostgreSQL 安装与配置 pgvector 扩展操作手册

本手册适用于在 Windows 环境下部署或运行 Nexora / NetOps 时，因数据库缺少 `pgvector` 扩展导致服务启动失败、数据库迁移中断（报错如 `MissingPostgreSQLExtension: PostgreSQL extension 'vector' is unavailable` 或 `RuntimeError: Database migrations are incomplete; pending versions: (138, ...)`）的处理指南。

---

## 1. 背景与问题说明

Nexora 知识引擎与智能检索（RAG）功能在 PostgreSQL 数据库中强依赖 `vector` (pgvector) 与 `pg_trgm` 扩展。

PostgreSQL 官方 Windows 安装包（EnterpriseDB）自带了 `pg_trgm`，但**默认不包含 `pgvector` 扩展**。因此在首次部署或拉取包含新迁移的代码后，若本地 PostgreSQL 未安装 pgvector，启动后端时会自动触发保护拦截并抛出错误。

---

## 2. 安装前确认

### 2.1 确认 PostgreSQL 版本与安装路径
- 默认安装路径通常为：
  - PostgreSQL 18: `C:\Program Files\PostgreSQL\18\`
  - PostgreSQL 17: `C:\Program Files\PostgreSQL\17\`
- 服务名称通常为：`postgresql-x64-18` 或 `postgresql-x64-17`。

---

## 3. 安装方法

### 方法一：下载预编译二进制包（推荐，简单快速）

由于 pgvector 官方仓库未直接打包 Windows Release，推荐使用 GitHub 社区维护的预编译包：

1. **下载预编译包**：
   - 访问 GitHub Releases：[https://github.com/andreiramani/pgvector_pgsql_windows/releases](https://github.com/andreiramani/pgvector_pgsql_windows/releases)
   - 根据本地 PostgreSQL 版本下载对应的压缩包（例如 `pgvector_v0.8.6_pg18_x64.zip` 或 `pg17` 版本）。

2. **解压并复制文件**：
   解压后将文件分别复制到 PostgreSQL 的对应目录中（需要管理员权限）：

   | 文件 | 目标安装路径（以 PG18 为例） |
   | :--- | :--- |
   | `vector.dll` | `C:\Program Files\PostgreSQL\18\lib\` |
   | `vector.control` | `C:\Program Files\PostgreSQL\18\share\extension\` |
   | `vector--*.sql`（所有 SQL 脚本） | `C:\Program Files\PostgreSQL\18\share\extension\` |

   *(注：若使用 PostgreSQL 17，请将上述路径中的 `18` 替换为 `17`)*

3. **重启 PostgreSQL 服务**（见后文第 4 节）。

---

### 方法二：通过 Visual Studio 源码编译（官方标准流程）

若开发机已安装 **Visual Studio 2019/2022** 并勾选了 **“使用 C++ 的桌面开发”**：

1. 以**管理员身份**打开 **x64 Native Tools Command Prompt for VS**。
2. 设置 PostgreSQL 根目录环境变量：
   ```cmd
   set "PGROOT=C:\Program Files\PostgreSQL\18"
   ```
   *(若为 PG17 请设置为 `C:\Program Files\PostgreSQL\17`)*
3. 克隆源码并编译安装：
   ```cmd
   cd %TEMP%
   git clone --branch v0.8.6 https://github.com/pgvector/pgvector.git
   cd pgvector
   nmake /F Makefile.win
   nmake /F Makefile.win install
   ```

---

## 4. 重启 PostgreSQL 服务

复制或编译完成后，需要重启 PostgreSQL 服务使扩展生效。

### 方式 A：通过图形界面（推荐）
1. 按快捷键 `Win + R` 打开“运行”窗口，输入 `services.msc` 并回车。
2. 在服务列表中按字母 `P` 找到 `postgresql-x64-18`（或对应版本号）。
3. **右键**该服务，点击 **“重新启动”**。

### 方式 B：通过管理员 PowerShell
以管理员身份打开 PowerShell，执行：
```powershell
Restart-Service postgresql-x64-18
```

### 方式 C：通过管理员 CMD
以管理员身份打开 CMD，执行：
```cmd
net stop postgresql-x64-18 && net start postgresql-x64-18
```

---

## 5. 验证与数据库迁移恢复

### 5.1 验证扩展是否就绪
使用 pgAdmin 或 `psql` 连接数据库，执行以下查询：
```sql
SELECT name, default_version, installed_version 
FROM pg_available_extensions 
WHERE name IN ('vector', 'pg_trgm');
```
**预期输出**：`vector` 和 `pg_trgm` 均出现在列表中，且 `default_version` 显示具体版本（如 `0.8.6`）。

### 5.2 重新启动系统
扩展就绪后，直接在项目根目录下正常启动开发或生产环境：
```bash
npm run dev
```
后端启动时 `init_db()` 会自动检测并顺序执行剩余的数据库迁移（如 138 ~ 144），迁移完成后各服务即可正常提供服务。

---

## 6. 常见排错

1. **复制文件时提示“没有权限”**：
   `C:\Program Files` 属于系统保护目录，复制或覆盖文件时请在 UAC 弹窗中点击“继续”，或以管理员身份运行文件管理器/终端。
2. **`CREATE EXTENSION vector;` 报错找不到模块**：
   检查 `vector.dll` 是否确实位于 `PostgreSQL\XX\lib\` 目录下，并确保下载的 pgvector 大版本（PG17 / PG18）与当前运行的 PostgreSQL 一致。
3. **不想在 Windows 本机配置 PostgreSQL**：
   可直接使用项目内置的 Docker PostgreSQL 镜像（已预装 pgvector 与 pg_trgm）：
   ```bash
   docker compose up -d db
   ```
