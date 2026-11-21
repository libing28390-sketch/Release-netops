# 8. 自动化产品使用手册 (Automation)

自动化模块是 Nexora 平台的执行核心，支持批量下发网络指令、执行巡检脚本、模板解析配置以及编排复杂的串并行割接场景。

![自动化](file:///e:/data/netsops/docs/images/automation_tasks.png)

## 1. 核心功能概述

本模块包含以下子菜单：
1. **任务执行 (Job Execution)**：即时批量下发单行或多行命令行脚本到指定设备组。
2. **场景与剧本编排 (Scenarios & Playbooks)**：定义任务的执行顺序和参数变量，支持干跑 (Dry-Run) 和自动解析回显。
3. **定时任务 (Scheduled Jobs)**：设定 Cron 周期任务，如定期轮询收集链路光衰、凌晨自动执行密码轮换等。
4. **设备巡检 (Inspections)**：批量运行自动化巡检报告，采用 TextFSM 等模板解析器自动将命令回显结构化。

---

## 2. 详细操作步骤

### 2.1 任务批量下发 (Job Execution)
* **执行工作流**：
  1. 进入 **自动化 -> 任务执行** 看板。
  2. 选择目标设备（支持按站点、厂商标签进行快速筛选过滤）。
  3. 输入待下发的 CLI 命令集（如 `display current-configuration | include ospf`）。
  4. 点击 **“执行”**。系统会拉起异步执行进程。在下方列表中能看到每台设备的执行进度。
  5. 双击列表行可以调出明细对话框，显示设备 SSH 交互的完整原生回显。

### 2.2 多品牌巡检与 TextFSM 模板结构化
网络命令的回显通常是杂乱的无结构化文本，Nexora 提供结构化巡检机制：
* **结构化解析**：
  在 **自动化 -> TextFSM 模板** 页面中维护了不同厂商的解析规则文件（例如解析 `show ip interface brief` 为包含 `interface`、`ip_address`、`status`、`protocol` 的 JSON 数据结构）。
* **自动化巡检**：
  定期触发巡检任务后，巡检引擎调用 TextFSM 进行格式化分析，直接输出符合 JSON 标准的结构化报表，免去了网络工程师手动通过正则分析文本的麻烦。
* 任务调度与定时计划的实现细节可参考后端服务 [scheduler_service.py](file:///e:/data/netsops/backend/services/scheduler_service.py) 以及 API 端点 [scheduled_jobs.py](file:///e:/data/netsops/backend/api/scheduled_jobs.py)。
