# NetOps 项目代码统计报告

> 统计日期：2026-05-12  
> 统计范围：项目源码（排除 `node_modules`、`.venv`、`dist`、`__pycache__`、`.git`）

---

## 一、总览

| 指标 | 数值 |
|------|------|
| **源码总行数** | **102,238 行** |
| **源码总文件数** | **263 个** |
| 主要编程语言 | Python · TypeScript / TSX |
| 前后端比例 | 前端 60% · 后端 38% · 其他 2% |

---

## 二、按语言分布

| 语言 / 类型 | 文件数 | 代码行数 | 占比 |
|-------------|-------:|--------:|-----:|
| **TypeScript / TSX**（前端） | 141 | 60,602 | 59.3% |
| **Python**（后端） | 111 | 39,227 | 38.4% |
| **CSS** | 2 | 1,172 | 1.1% |
| **Markdown**（文档） | 9 | 1,832 | 1.8% |
| **Shell Script** | 2 | 685 | 0.7% |
| **YAML**（CI/CD） | 5 | 247 | 0.2% |
| **配置文件**（JSON/HTML/Dockerfile 等） | 7 | 305 | 0.3% |
| **Nginx 配置** | 1 | 75 | 0.1% |
| **requirements.txt** | 1 | 40 | <0.1% |
| **合计** | **279** | **104,185** | 100% |

> 注：Markdown 含 `docs/` 目录（5 文件 913 行）+ 根目录（4 文件 919 行）。

---

## 三、后端 Python 详细分布（39,227 行）

| 模块目录 | 文件数 | 代码行数 | 说明 |
|----------|-------:|--------:|------|
| `backend/api/` | 30 | 15,248 | FastAPI 路由层（30 个 API 模块） |
| `backend/services/` | 23 | 9,899 | 业务逻辑服务层 |
| `backend/main.py` | 1 | 1,763 | 应用入口、调度器、后台任务 |
| `backend/database.py` | 1 | 2,141 | 数据库初始化、Schema 定义 |
| `backend/drivers/` | 7 | 815 | 设备驱动（Netmiko / Paramiko） |
| `backend/core/` | 7 | 504 | 核心工具（加密、RBAC、TextFSM、调度器） |
| `backend/engine/` | 11 | 420 | 执行引擎（Orchestrator、驱动注册） |
| `backend/models/` | 1 | 24 | 数据模型 |
| `backend/tests/` 等其他 | ~30 | ~8,413 | 测试、脚本、scratch |

**最大单文件：**

| 文件 | 行数 |
|------|-----:|
| `backend/api/playbooks.py` | ~3,800 |
| `backend/api/devices.py` | ~2,500 |
| `backend/database.py` | 2,141 |
| `backend/main.py` | 1,763 |
| `backend/services/scheduler_service.py` | ~900 |
| `backend/services/operational_data_service.py` | ~380 |

---

## 四、前端 TypeScript/TSX 详细分布（60,602 行）

| 目录 | 文件数 | 代码行数 | 说明 |
|------|-------:|--------:|------|
| `src/pages/` | 43 | 35,248 | 页面组件（Tab 页面，功能最密集） |
| `src/components/` | 61 | 16,578 | 通用 UI 组件库 |
| `src/hooks/` | 20 | 3,253 | 自定义 React Hooks |
| `src/` 根文件 | 5 | 5,065 | `App.tsx`、`main.tsx`、`i18n.tsx` 等 |
| `src/utils/` | 9 | 395 | 工具函数 |
| `src/store/` | 1 | 51 | Redux Store |
| `src/lib/` | 1 | 8 | 库入口 |
| `src/types/` | 1 | 4 | 类型定义 |

**最大单文件（估算）：**

| 文件 | 行数（约） |
|------|----------:|
| `src/pages/AutomationHistoryTab.tsx` | ~990 |
| `src/pages/InventoryDevicesTab.tsx` | ~900+ |
| `src/pages/AutomationPlaybooksTab.tsx` | ~800+ |
| `src/pages/TextFSMTemplatesTab.tsx` | ~450 |

---

## 五、功能模块代码量估算

| 功能模块 | 涉及文件 | 估算行数 |
|----------|----------|--------:|
| 自动化执行引擎（Playbook + 定时作业） | `playbooks.py` + `scheduler_service.py` + `automation_service.py` + 前端 | ~8,000 |
| 设备管理 & 运营数据采集 | `devices.py` + `operational_data_service.py` + 前端 | ~6,000 |
| 数据库 Schema & 初始化 | `database.py` | 2,141 |
| 应用主入口 & 后台任务 | `main.py` | 1,763 |
| PAM 特权访问管理 | `pam.py` + `PAMAuditTab.tsx` | ~2,500 |
| 变更单管理 | `change_orders.py` + `ChangeOrderTab.tsx` | ~2,000 |
| TextFSM 解析模板 | `textfsm_templates.py` + `core/textfsm.py` + `TextFSMTemplatesTab.tsx` | ~1,200 |
| 告警 & 监控 | `alerts.py` + `monitoring.py` + 前端 | ~3,000 |
| 拓扑图 | `topology.py` + `TopologyPage.tsx` | ~2,000 |
| IPAM / IP 定位 | `ipam.py` + `ip_locator.py` + 前端 | ~2,500 |
| 配置备份 & Diff | `configs.py` + `config_drift.py` + 前端 | ~2,000 |
| 用户 & RBAC | `users.py` + `core/rbac.py` + 前端 | ~1,500 |
| CI/CD & 部署 | `.github/workflows/` + `deploy-ubuntu.sh` + `Dockerfile` | ~1,000 |

---

## 六、关键技术栈

**后端**
- Python 3.11+，FastAPI，SQLite（`aiosqlite`）
- Netmiko（网络设备 SSH）、Paramiko（Linux SSH）
- APScheduler（定时任务）、ntc-templates / TextFSM（CLI 解析）
- JWT 认证、AES 加密凭据存储

**前端**
- React 18 + TypeScript，Vite 构建
- Tailwind CSS，Framer Motion，Lucide Icons
- Redux Toolkit，React Router，Recharts / D3
- WebSocket（实时执行日志流）

**基础设施**
- Docker + Docker Compose，Nginx 反向代理
- GitHub Actions（pytest + 前端构建 CI）

---

## 七、代码规模参考对比

| 项目规模参考 | 代码行数 |
|-------------|--------:|
| 小型工具项目 | < 5,000 |
| 中型内部系统 | 5,000 – 30,000 |
| **NetOps（本项目）** | **~102,000** |
| 大型企业系统 | 100,000 – 500,000 |

NetOps 已达到**中大型企业内部系统**的代码规模，功能覆盖网络运维全生命周期。

---

*报告由 Kiro 自动生成，统计时间 2026-05-12*
