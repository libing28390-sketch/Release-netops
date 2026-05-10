# 部署问题排查报告
**日期：** 2026-05-10  
**环境：** Ubuntu 24.04 LTS (VMware) + GitHub Codespaces  
**版本：** Nexora NetOps v0.1.1  
**状态：** ✅ 全部已修复并验证

---

## 问题汇总

### P0 — 阻断启动

#### 1. Python 版本不兼容（`.so` 文件）
**现象：** `ModuleNotFoundError: No module named 'license_auth.verifier'`  
**根因：** 公有仓库只编译了 Python 3.10 的 `.so`，但 Codespaces 和 Ubuntu 24.04 默认使用 Python 3.12，`.so` 文件名含版本号，Python 只加载匹配版本。  
**修复：** `release.yml` 改为同时编译 Python 3.10 / 3.11 / 3.12 三个版本，每次编译前清理 `build/` 目录避免版本混用。  
**预防：** `deploy-ubuntu.sh` 新增 `.so` 兼容性检查，版本不匹配时提前报错并列出可用版本。安装依赖后再做一次真实 `import` 验证。

---

#### 2. DATABASE_URL 主机名 `db` 无法解析
**现象：** `could not translate host name "db" to address: Name or service not known`  
**根因：** `.env.example` 里 `DATABASE_URL` 使用 Docker Compose 内部服务名 `db`，在非 Docker 环境（Codespaces、裸机）无法解析。  
**修复（三层）：**
- `database.py`：检测非 docker-compose 环境时自动将 `@db:` 替换为 `@localhost:`（判断条件改为同时有 `/.dockerenv` 和 `POSTGRES_USER` 环境变量才认为是 compose 环境）
- `deploy-ubuntu.sh`：生成 `.env` 后强制替换 `@db:` → `@localhost:`，且不管 `.env` 是新建还是已存在都执行
- `.env.example`：默认改为 `localhost`，Docker 部署时用户手动改回 `db`

---

#### 3. `.env` CRLF 换行符导致 `sed` 替换失败
**现象：** 部署脚本提示 `.env 已创建，但数据库密码需要手动更新`，`DATABASE_URL` 仍为 `YOUR_PASSWORD`  
**根因：** `.env.example` 在 Windows 开发机上编辑，带有 CRLF 换行符，`sed` 的 `^` 和 `$` 无法匹配带 `\r` 的行尾，所有替换静默失败。  
**修复：** `deploy-ubuntu.sh` 在 `cp .env.example .env` 后立即执行 `sed -i 's/\r$//'` 转换换行符，且对已存在的 `.env` 也执行同样转换。  
**临时解决：** 用 Python 替换绕过换行符问题：
```bash
python3 -c "
import re
with open('/opt/netops-automation/.env', 'rb') as f:
    content = f.read().decode('utf-8').replace('\r\n', '\n')
content = re.sub(r'^DATABASE_URL=.*$',
                 'DATABASE_URL=postgresql://netops:PASSWORD@localhost:5432/netops',
                 content, flags=re.MULTILINE)
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
# 先查当前 machine_id
curl -s http://localhost/api/license/machine-id

# 设置 override（使用 License 里绑定的值）
echo "MACHINE_ID_OVERRIDE=11D4-2CC9-0A0F-C312" >> /opt/netops-automation/.env
sudo systemctl restart netops
```
**预防：** 签发 License 前先从 `/api/license/machine-id` 获取真实 machine_id，再签发。VMware 环境建议在 `.env` 里固定 `MACHINE_ID_OVERRIDE`。

---

#### 7. License 上传后全局状态不刷新
**现象：** 上传 License 后 License 页面显示有效，但其他功能仍被拦截，需要刷新页面  
**根因：** `App.tsx` 的 `isLicenseValid` 只在登录时拉取一次，上传 License 后 `LicenseAdminTab` 没有通知全局状态更新。  
**修复：**
- `App.tsx`：`checkLicenseStatus` 改为每 60 秒轮询
- `LicenseAdminTab.tsx`：上传成功后调用 `onLicenseUpdate?.()` 回调
- `AppMainContent.tsx`：传入 `onLicenseUpdate={props.checkLicenseStatus}`

---

#### 8. License 功能门控只在前端，后端 API 无保护
**现象：** 试用版只授权 4 个功能，但所有 API 接口均可直接调用，绕过前端限制即可使用全部功能  
**根因：** 所有 API 路由均使用裸 `APIRouter()`，没有 `require_feature` 依赖，License 功能门控仅在前端 `App.tsx` 做了页面跳转拦截。  
**修复（三层防护）：**

**第一层：`main.py` 路由三层注册**
```python
# 无需 License：health、users、setup、license、system 等
# 需要 License：devices、jobs、assets 等基础操作
app.include_router(devices_router, prefix="/api", dependencies=[Depends(require_license)])
# Feature-gated：每个功能模块绑定对应 feature
app.include_router(automation_router, prefix="/api", dependencies=[Depends(require_feature("automation"))])
app.include_router(change_orders_router, prefix="/api", dependencies=[Depends(require_feature("change_orders"))])
# ... 其他模块类似
```

**第二层：`middleware.py`（编译进 `.so`）内嵌 URL→feature 映射表**
```python
_FEATURE_REQUIRED = (
    ("/api/automation",    "automation"),
    ("/api/change-orders", "change_orders"),
    # ... 完整映射
)
```
中间件层面拦截，即使 `main.py` 的 `dependencies` 被删除，`.so` 内部仍会拦截。

**第三层：`verifier.py`（编译进 `.so`）`bootstrap_license_protection`**
- 在 `.so` 内部强制注册 `LicenseMiddleware`，删除 `main.py` 里的 `add_middleware` 调用无效
- 启动时建立 `main.py` 等关键文件的 hash 基线
- 每 5 分钟检查文件完整性，检测到篡改立即返回 License invalid

---

#### 9. 初始化向导设置的系统名称不生效
**现象：** Setup 向导中修改系统名称（如改为 "Cisco"），保存后 Sidebar 和 TopHeader 仍显示 "Nexora"  
**根因：** Sidebar、TopHeader 等组件硬编码了 `Nexora` 字符串，没有读取后端保存的 `system_name`。  
**修复：**
- `backend/api/system.py`：`/api/system/info` 接口新增 `system_name` 字段，从 `global_vars` 表读取
- `src/hooks/useSystem.ts`：`SystemInfo` 接口加入 `system_name`
- `AppSidebar/index.tsx`、`TopHeader.tsx`：硬编码 `Nexora` 改为 `systemInfo?.system_name || 'Nexora'`

---

### P2 — 部署体验

#### 10. `curl | bash` 管道模式静默退出
**现象：** 部署脚本在 PostgreSQL 安装步骤后无任何提示直接退出  
**根因：** `curl | bash` 管道模式下 stdin 被 curl 占用，`set -euo pipefail` 遇到任何错误立即退出，无错误提示。  
**修复：**
- 脚本开头加 `trap '_on_error $LINENO' ERR` 全局错误捕获，打印出错行号
- 检测管道模式时执行 `exec < /dev/tty` 重定向 stdin
- 文档改为推荐先下载再执行：
```bash
curl -fsSL -o /tmp/deploy.sh https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh
chmod +x /tmp/deploy.sh
bash /tmp/deploy.sh
```

---

#### 11. 系统时间偏差导致 apt 源证书验证失败
**现象：** `apt-get update` 报 `Release 文件已经过期`，部署中断  
**根因：** VMware 虚机时钟未同步，系统时间比实际时间慢 3 天以上，apt 源的 Release 文件证书验证失败。  
**修复：**
- `deploy-ubuntu.sh` 新增时间偏差检测，偏差 > 24h 时自动同步
- `apt-get update` 加 `--allow-releaseinfo-change` 和 `-o Acquire::Check-Valid-Until=false` 容错选项  
**临时解决：**
```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
sleep 5 && date
```

---

#### 12. PostgreSQL 用户已存在时密码未写入 `.env`
**现象：** 重复部署时提示 `数据库密码需要手动更新`  
**根因：** 脚本检测到 `netops` 用户已存在时跳过创建，`PG_PASS` 变量为空，导致 `DATABASE_URL` 写入占位符 `YOUR_PASSWORD`。  
**修复：** 用户已存在时检查 `.env` 里是否有有效密码，没有则重置 PG 密码并写入；已有有效密码则提取复用，不重置。

---

#### 13. `npm install --silent | tail -1` 在 pipefail 模式下误触发错误
**现象：** 部署在 `npm install` 步骤报 `exit code: 1`  
**根因：** `set -o pipefail` 下管道中任意命令失败都会触发 ERR，`tail -1` 本身可能返回非零，加上 `--silent` 隐藏了真实错误。  
**修复：** 改为 `npm install --prefer-offline 2>&1 | tail -5 || npm install 2>&1 | tail -10`，去掉 `--silent`，保留错误输出。

---

#### 14. OS 兼容性检测缺失
**现象：** 在 CentOS 7 或不支持的系统上运行脚本，报 `apt-get: command not found` 等错误  
**修复：** `deploy-ubuntu.sh` 新增 OS 检测，读取 `/etc/os-release`：
- CentOS 7 / RHEL 7：直接 `fail` 并提示迁移到 Rocky Linux 8+
- RHEL 8+ / Rocky / AlmaLinux：给出警告并建议使用 Docker 部署
- 未知发行版：给出警告后继续

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

# 修复 DATABASE_URL（CRLF 问题）
python3 -c "
import re
with open('/opt/netops-automation/.env', 'rb') as f:
    content = f.read().decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
content = re.sub(r'^DATABASE_URL=.*$',
                 'DATABASE_URL=postgresql://netops:YOUR_PASS@localhost:5432/netops',
                 content, flags=re.MULTILINE)
open('/opt/netops-automation/.env', 'wb').write(content.encode('utf-8'))
print('Done')
"

# 重置数据库（全新部署）
sudo systemctl stop netops
sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='netops';"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS netops;"
sudo -u postgres psql -c "CREATE DATABASE netops OWNER netops;"
sudo systemctl start netops
sleep 8 && curl -s http://localhost/api/health
```

---

## License 安全防护层级（最终状态）

```
攻击者行为                    被哪一层拦截
──────────────────────────────────────────────────────────
直接调用未授权 API            → middleware.so 内嵌映射表拦截（第一道）
删除 main.py 的 dependencies  → middleware.so 映射表仍然生效
删除 main.py 的 add_middleware → verifier.so bootstrap 强制注册
修改 main.py 绕过验证         → verifier.so 每 5 分钟检查文件 hash
伪造 License 文件             → RSA-PSS 签名验证，私钥只在开发者手中
复制 License 到其他机器       → machine_id 绑定，不匹配则拒绝
```

---

## 待优化项

| 优先级 | 问题 | 建议 |
|--------|------|------|
| P1 | ARM64 不支持 | 考虑 manylinux 编译或 Docker 多架构镜像 |
| P1 | CentOS 7 不支持 | 提供 manylinux2014 编译版本覆盖 glibc 2.17 |
| P2 | 多次部署时 PG 密码管理混乱 | 考虑将密码持久化到独立的 secrets 文件 |
| P2 | Trial License 未绑定 machine_id | 建议 trial 也绑定，防止无限传播 |
| P3 | LD_PRELOAD 劫持 .so | 可在 verifier.so 内检测 LD_PRELOAD 环境变量 |
