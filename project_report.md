# Nexora (网络自动化运维平台) 项目报告

## 1. 项目概述
**Nexora** 是一个面向网络工程师和运维团队的全栈、一体化网络自动化运维平台（NetOps Automation Platform）。该项目的主要目标是将常见的网络运维工作流集中到一个单一的控制台中，提供包含设备资产管理、运行监控、自动化执行、配置备份、合规检查和操作审计等一站式能力。

## 2. 技术栈与架构设计
该项目采用前后端分离的主流 Web 技术栈，结合专业的网络自动化和数据采集库，实现全周期的网络运维功能。

### 前端 (Frontend)
- **核心框架**: React 19, TypeScript
- **构建工具**: Vite 6
- **样式与UI**: TailwindCSS (v4), Lucide React (图标)
- **可视化与组件**: Recharts, D3 (用于网络拓扑/图表渲染), dnd-kit (拖拽组件)
- **路由**: React Router DOM 7

### 后端 (Backend)
- **核心框架**: Python 3.10+, FastAPI (提供 RESTful API)
- **数据库**: SQLite (本地运行), SQLAlchemy (ORM), Pydantic (数据校验与序列化)
- **网络自动化协议与库**: 
  - CLI/SSH: `netmiko`, `scrapli`, `asyncssh`
  - 结构化解析: `textfsm`, `ntc-templates`
  - SNMP监控: `puresnmp`
- **后台任务与调度**: `apscheduler`, `croniter` (定时任务), `celery` & `redis` (依赖库有引入支持异步任务)
- **鉴权与安全**: `bcrypt`, `cryptography`

## 3. 核心功能模块分析
基于前端的 `src/pages` 和后端的 `backend/api` 及 `services` 代码结构，项目主要划分为以下几个核心模块：

### 3.1 资产与拓扑管理 (Inventory & Topology)
- **设备台账 (`AssetManagementTab`, `InventoryDevicesTab`)**: 支持多厂商设备台账维护，包含设备平台、型号、站点、角色等元数据管理。
- **机架管理 (`RackManagementTab`)**: 用于数据中心机房物理维度的资产管理。
- **拓扑发现与展示 (`TopologyPage`, `TopologyGraph`)**: 自动渲染和动态检视网络拓扑关系。

### 3.2 监控与健康检查 (Monitoring & Health)
- **接口监控 (`InterfaceMonitoringTab`)**: 提供接口级别的流量监控、带宽利用率、状态改变和端口震荡（Flap）检测。
- **设备健康度 (`DeviceHealthTab`)**: 基于 CPU、内存和链路数据的采集，实时展现设备健康状态。
- **容量规划 (`CapacityPlanningTab`)**: 基于历史性能数据进行 30 天的线性趋势预测和资源阈值评估。

### 3.3 自动化与配置中心 (Automation & Configuration)
- **配置备份与比对 (`ConfigBackupTab`, `ConfigDiffViewTab`, `ConfigDriftTab`)**: 周期性备份设备配置，提供历史版本快照比对，并能全局扫描配置漂移并给出彩色差异视图。
- **自动化执行 (`AutomationExecuteTab`, `AutomationPlaybooksTab`)**: 支持单点命令执行、场景化编排以及基于 Playbook 的批处理作业。

### 3.4 IPAM 与网络寻址 (IPAM & Locators)
- **IP/VLAN 管理 (`IPVlanTab`)**: 具有 IP 子网和 VLAN 资源的 CRUD 能力，支持使用进度条展现 IP 分配情况与冲突检测。
- **IP定位 (`IPLocatorPage`)**: 在全网范围内通过 MAC 或 IP 地址快速定位终端接入的交换机及具体端口。

### 3.5 告警、合规与运维支持 (Alerts, Compliance & Ops)
- **告警中心 (`AlertDeskTab`, `AlertRulesTab`)**: 聚合全网告警并提供告警规则与维护期设定。
- **合规审计 (`ComplianceTab`, `InspectionTab`)**: 提供针对网络配置的标准检查并输出整改建议。
- **变更与排期 (`ChangeOrderTab`, `ScheduledJobsTab`)**: 运维变更工单和自动调度任务的管理。

## 4. 目录与代码结构

```text
netops-automation/
├── backend/                  # Python 后端目录
│   ├── api/                  # FastAPI 路由控制器 (如 devices.py, configs.py, automation.py)
│   ├── core/                 # 核心配置和日志逻辑
│   ├── data/                 # 本地 SQLite 数据和运行时产物存储
│   ├── drivers/              # 针对具体网络设备的交互驱动层
│   ├── models/               # SQLAlchemy 数据模型
│   ├── schemas/              # Pydantic 响应与请求模型
│   ├── services/             # 业务逻辑服务层 (如 snmp_service, ipam_service 等)
│   ├── database.py           # 数据库连接初始化
│   ├── main.py               # FastAPI 启动主入口
│   └── requirements.txt      # 后端依赖清单
├── src/                      # React 前端源码
│   ├── components/           # 复用级 UI 模态框、卡片和图表组件 (如 Sidebar, CustomCommandModal)
│   ├── pages/                # 路由映射的各个核心功能页面视图
│   ├── hooks/                # React 自定义 Hook
│   ├── lib/                  # 第三方库封装或通用逻辑
│   ├── App.tsx               # 根组件和主路由配置
│   └── main.tsx              # React 挂载点
├── data/                     # 全局运行时数据目录
├── deploy-ubuntu.sh          # Linux 环境的一键部署脚本
├── docker-compose.yml        # 容器化部署配置
├── package.json              # 前端及开发脚本依赖配置
└── vite.config.ts            # Vite 构建配置
```

## 5. 部署与 CI/CD 策略
- **开发环境**: 提供了便利的 `concurrently` 脚本 (`npm run dev`)，实现通过一条命令同时启动 Vite 前端服务和 FastAPI 后端服务。
- **生产环境与部署**: 
  - 前端支持被 Vite 编译为静态资源。
  - 项目配置了 `docker-compose.yml` 和 `Dockerfile` 用于容器化部署，并含有专门针对 Ubuntu 系统的部署脚本 `deploy-ubuntu.sh`。
- **持续集成 (CI)**: 利用 GitHub Actions 针对不同维度的修改进行了校验防护。
  - 前端流程 (`frontend-build-check.yml`): `lint` 静态分析与 `build` 构建验证。
  - 后端流程 (`backend-pytest-check.yml`): 自动化安装环境并执行 `pytest` 单元测试，配置了严苛的测试失败即拦截的策略。
