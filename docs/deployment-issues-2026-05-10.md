# 部署问题排查报告
**日期：** 2026-05-10  
**环境：** Ubuntu 24.04 LTS (VMware) + GitHub Codespaces  
**版本：** Nexora NetOps v0.1.1

---

## 问题汇总

### P0 — 阻断启动

#### 1. Python 版本不兼容（`.so` 文件）
**现象：** `ModuleNotFoundError: No module named 'license_auth.verifier'`  
**根因：** 公有仓库只编译了 Python 3.10 的 `.so`，但 Codespaces 和 Ubuntu 24.04 默认使用 Python 3.12，`.so` 文件名含版本号，Python 只加载匹配版本。  
**修复：** `release.yml` 改为同时编译 Python 3.10 / 3.11 / 3.12 三个版本。  
**预防：** `deploy-ubuntu.sh` 新增 `.so` 兼容性检查，版本不匹配时提前报错。

---

#### 2. DATABASE_URL 主机名 `db` 无法解析
**现象：** `could not translate host name "db" to address: Name or service not known`  
**根因：** `.env.example` 里 `DATABASE_URL` 使用 Docker Compose 内部服务名 `db`，在非 Docker 环境（Codespaces、裸机）无法解析。  
**修复（三层）：**
- `database.py`：检测非 docker-compose 环境时自动将 `@db:` 替换为 `@localhost:`
- `deploy-ubuntu.sh`：生成 `.env` 后强制替换 `@db:` → `@localhost:`
- `.env.example`：默认改为 `localhost`，Docker 部署时用户手动改回 `db`

---

#### 3. `.env` CRLF 换行符导致 `sed` 替换失败
**现象：** 部署脚本提示 `.env 已创建，但数据库密码需要手动更新`，`DATABASE_URL` 仍为 `YOUR_PASSWORD`  
**根因：** `.env.example` 在 Windows 开发机上编辑，带有 CRLF 换行符，`sed` 的 `^` 和 `$` 无法匹配带 `\r` 的行尾，所有替换静默失败。  
**修复：** `deploy-ubuntu.sh` 在 `cp .env.example .env` 后立即执行 `sed -i 's/\r$//'` 转换换行符。  
**临时解决：** 用 Python 替换绕过换行符问题：
```bash
python3 -c "
import re
with open('/opt/netops-automation/.env', 'rb') as f:
    content = f.read().decode('utf-8').replace('\r\n', '\n')
content = re.sub(r'^DATABASE_URL=.*$', 'DATABASE_URL=postgresql://netops:PASSWORD@localhost:5432/netops', content, flags=re.MULTILINE)
open('/opt/netops-automation/.env', 'wb').write(content.encode('utf-8'))
"
```

---

#### 4. `users` 表缺少 `created_at` 列
**现象：** `psycopg2.errors.UndefinedColumn: column "created_at" of relation "users" does not exist`  
**根因：** `users` 表的 `CREATE TABLE` 语句没有 `created_at` 列，但 seed data 的 INSERT 语句包含该列。`ensure_column` 在 seed data 之后执行，时序问题导致失败。  
**修复：** 在 `CREATE TABLE users` 语句中直接加入 `created_at TEXT`，并在 `ensure_column` 列表中也加上（保证旧库升级兼容）。  
**临时解决：**
```bash
sudo -u postgres psql -d netops -c "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TEXT;"
```

---

#### 5. Health Check 在 PostgreSQL 模式下误报 `database: missing`
**现象：** 后端正常运行，`/api/health` 返回 `"database":"missing"`  
**根因：** `_get_db_health()` 先检查 `os.path.exists(DB_PATH)`（SQLite 文件路径），PG 模式下该文件不存在，直接返回 `"missing"`，未尝试 PG 连接。  
**修复：** `health.py` 中先判断 `_USE_PG`，PG 模式直接尝试连接，不检查文件路径。

---

### P1 — 功能异常

#### 6. Machine ID 不匹配导致 License 无效
**现象：** License 页面显示有效，但所有功能被拦截，提示"高级特性"  
**根因：** VMware 虚机克隆或网卡重建后 MAC 地址变化，导致 machine_id 重新计算，与 License 绑定的 ID 不一致。  
**修复：** 在 `.env` 中设置 `MACHINE_ID_OVERRIDE` 固定为 License 绑定的值：
```bash
echo "MACHINE_ID_OVERRIDE=11D4-2CC9-0A0F-C312" >> /opt/netops-automation/.env
sudo systemctl restart netops
```
**预防：** 签发 License 前先从 `/api/license/machine-id` 获取真实 machine_id，再签发。

---

#### 7. License 上传后全局状态不刷新
**现象：** 上传 License 后 License 页面显示有效，但其他功能仍被拦截，需要刷新页面  
**根因：** `App.tsx` 的 `isLicenseValid` 只在登录时拉取一次，上传 License 后 `LicenseAdminTab` 没有通知全局状态更新。  
**修复：**
- `App.tsx`：`checkLicenseStatus` 改为每 60 秒轮询
- `LicenseAdminTab.tsx`：上传成功后调用 `onLicenseUpdate?.()` 回调
- `AppMainContent.tsx`：传入 `onLicenseUpdate={props.checkLicenseStatus}`

---

#### 8. 初始化向导设置的系统名称不生效
**现象：** Setup 向导中修改系统名称（如改为 "Cisco"），保存后 Sidebar 和 TopHeader 仍显示 "Nexora"  
**根因：** Sidebar、TopHeader 等组件硬编码了 `Nexora` 字符串，没有读取后端保存的 `system_name`。  
**修复：**
- `backend/api/system.py`：`/api/system/info` 接口新增 `system_name` 字段，从 `global_vars` 表读取
- `src/hooks/useSystem.ts`：`SystemInfo` 接口加入 `system_name`
- `AppSidebar/index.tsx`、`TopHeader.tsx`：硬编码 `Nexora` 改为 `systemInfo?.system_name || 'Nexora'`

---

### P2 — 部署体验

#### 9. `curl | bash` 管道模式静默退出
**现象：** 部署脚本在 PostgreSQL 安装步骤后无任何提示直接退出  
**根因：** `curl | bash` 管道模式下 stdin 被 curl 占用，`set -euo pipefail` 遇到任何错误立即退出，无错误提示。  
**修复：**
- 脚本开头加 `trap '_on_error $LINENO' ERR` 全局错误捕获，打印出错行号
- 检测管道模式时执行 `exec < /dev/tty` 重定向 stdin
- 文档改为推荐先下载再执行：`curl -fsSL -o /tmp/deploy.sh ... && bash /tmp/deploy.sh`

---

#### 10. 系统时间偏差导致 apt 源证书验证失败
**现象：** `apt-get update` 报 `Release 文件已经过期`，部署中断  
**根因：** VMware 虚机时钟未同步，系统时间比实际时间慢 3 天以上，apt 源的 Release 文件证书验证失败。  
**修复：**
- `deploy-ubuntu.sh` 新增时间偏差检测，偏差 > 24h 时自动同步
- `apt-get update` 加 `--allow-releaseinfo-change` 和 `-o Acquire::Check-Valid-Until=false` 容错选项  
**临时解决：**
```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
```

---

#### 11. PostgreSQL 用户已存在时密码未写入 `.env`
**现象：** 重复部署时提示 `数据库密码需要手动更新`  
**根因：** 脚本检测到 `netops` 用户已存在时跳过创建，`PG_PASS` 变量为空，导致 `DATABASE_URL` 写入占位符 `YOUR_PASSWORD`。  
**修复：** 用户已存在时检查 `.env` 里是否有有效密码，没有则重置 PG 密码并写入。

---

#### 12. `npm install --silent | tail -1` 在 pipefail 模式下误触发错误
**现象：** 部署在 `npm install` 步骤报 `exit code: 1`  
**根因：** `set -o pipefail` 下管道中任意命令失败都会触发 ERR，`tail -1` 本身可能返回非零，加上 `--silent` 隐藏了真实错误。  
**修复：** 改为 `npm install --prefer-offline 2>&1 | tail -5 || npm install 2>&1 | tail -10`，去掉 `--silent`，保留错误输出。

---

## 快速排查命令

```bash
# 查看后端日志
sudo journalctl -u netops -n 50 --no-pager

# 检查数据库连接
curl -s http://localhost/api/health | python3 -m json.tool

# 检查 machine_id
curl -s http://localhost/api/license/machine-id

# 检查 License 状态
curl -s http://localhost/api/license/status | python3 -m json.tool

# 解除登录锁定
sudo -u postgres psql -d netops -c "DELETE FROM login_failures WHERE username = 'admin';"

# 重置数据库（全新部署）
sudo systemctl stop netops
sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='netops';"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS netops;"
sudo -u postgres psql -c "CREATE DATABASE netops OWNER netops;"
sudo systemctl start netops
```

---

## 待优化项

| 优先级 | 问题 | 建议 |
|--------|------|------|
| P1 | ARM64 不支持 | 考虑 manylinux 编译或 Docker 多架构镜像 |
| P1 | CentOS 7 不支持 | 提供 manylinux2014 编译版本 |
| P2 | 多次部署时 PG 密码管理混乱 | 考虑将密码持久化到独立的 secrets 文件 |
| P2 | `middleware.py` 仍为明文 | 已加入编译列表，下次 release 生效 |
| P3 | health check 的 `database: missing` 误导性 | 已修复，PG 模式直接连接检测 |
