# Nexora 前后端技术栈详尽报告

本报告详细列出了 Nexora 项目在前端和后端所采用的核心框架、库及网络自动化专业依赖。

## 一、前端技术栈 (Frontend Tech Stack)
前端基于现代化的 React 与构建工具生态，主要侧重于单页应用 (SPA) 体验和数据可视化。

### 1. 核心框架与构建
*   **React (v19.0.0)**: 构建用户界面的核心 UI 库，使用了最新的 React 19 版本。
*   **TypeScript (~5.8.2)**: 提供强类型的 JavaScript 超集，保障代码的类型安全。
*   **Vite (v6.2.0)**: 新一代前端构建工具，提供极速的本地开发服务器和打包能力。
*   **React Router DOM (v7.13.1)**: 前端路由库，处理多页面切换与单页应用的导航。

### 2. 样式与设计
*   **TailwindCSS (v4.1.14)**: 实用优先的 CSS 框架，利用 `@tailwindcss/vite` 插件无缝集成，用于快速编写组件样式和响应式布局。
*   **Lucide React (v0.546.0)**: 高质量、一致性的图标库，为各类按钮、菜单提供 SVG 图标。

### 3. 数据可视化与图表
*   **Recharts (v3.7.0)**: 基于 React 和 D3 的组合式图表库，用于绘制趋势图、容量规划折线图、设备状态甜甜圈图等。
*   **D3.js (v7.9.0)**: 强大的数据驱动文档库，主要用于项目中网络拓扑图的精细化物理节点渲染和连接线绘制。

### 4. 交互与工具库
*   **@dnd-kit/core & utilities**: 现代化、轻量级的拖拽组件库，支持复杂的拖拽交互。
*   **Motion (v12.23.24)**: (可能为 Framer Motion 或相似的动画库) 用于在组件切换和微交互时提供平滑的动画效果。
*   **uuid**: 用于生成唯一标识符（例如前端生成的表单行或新记录 ID）。
*   **html2canvas & html-to-image**: 用于将前端的视图（如拓扑图、报表）直接生成并导出为图片。
*   **xlsx**: 用于纯前端生成和导出多 sheet 的运维统计 Excel 数据表。
*   **@google/genai**: 引入了生成式 AI 库，可能用于助手、智能化解释或代码生成功能。

---

## 二、后端技术栈 (Backend Tech Stack)
后端主要由 Python 编写，围绕 RESTful 接口、网络协议交互以及异步任务调度展开。

### 1. 核心 Web 框架与数据库
*   **FastAPI**: 极速的现代 Python Web 框架，基于 ASGI 标准，天生支持异步，用于提供应用的所有 REST API。
*   **Uvicorn**: 异步的 ASGI 服务器，用于承载 FastAPI 应用的运行。
*   **SQLAlchemy**: Python 领域最强大的 ORM 框架，负责实体模型到关系型数据库的映射。
*   **SQLite / PostgreSQL**: 本地默认使用 SQLite，但依赖库包含 `psycopg2-binary`，表明具备并支持切换至生产级 PostgreSQL。
*   **Pydantic & Pydantic-Settings**: 用于严密的请求/响应数据结构定义、校验以及项目环境配置（`.env`）管理。

### 2. 网络自动化与设备通信核心
*   **Netmiko**: 用于网络设备的 SSH 交互并执行 CLI 命令，支持海量不同厂商设备的并发连接。
*   **Scrapli & Scrapli-Community**: 更轻量、速度极快的网络设备 SSH/Telnet 并发异步交互库。
*   **PureSNMP (>=2.0)**: 纯 Python 实现的无 C 库依赖的 SNMP 协议库，用于采集设备健康状态（CPU、内存）及接口指标。
*   **Ping3 / AsyncSSH**: 用于探测设备存活（ICMP Ping）及纯底层的 SSH 通信。

### 3. 数据解析与处理
*   **TextFSM**: 配合模板引擎，将网络设备返回的非结构化 CLI 文本（如 `show interfaces`）解析为结构化字典数据（JSON）。
*   **NTC-Templates**: TextFSM 的模板集合包，自带大量的各厂商常见命令解析模板。
*   **Jinja2**: 模板渲染引擎，主要用于动态生成网络设备配置脚本与 Playbook 参数渲染。

### 4. 任务调度与系统
*   **APScheduler & Croniter**: 轻量级进程内任务调度器，支持 Cron 表达式，用于执行定时配置备份、自动巡检和采集作业。
*   **Celery & Redis**: 强大的分布式任务队列及消息中间件引擎（作为高级调度机制后备）。
*   **Psutil**: 获取后端宿主机系统运行参数（如 CPU、磁盘占用），用于应用自身的健康自检。

### 5. 安全与网络扩展
*   **Bcrypt & Cryptography**: 用户密码加密存储校验与敏感数据（如网络设备密码）的对称/非对称加解密保护。
*   **Slowapi**: FastAPI 的限流扩展，用于保护 API，防止高频接口刷库或 DDoS 攻击。
*   **Httpx**: 现代化的全功能 HTTP 客户端，支持同步及异步的 HTTP 接口请求。
