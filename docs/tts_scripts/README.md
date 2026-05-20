# 🎙️ Net Sops 44个功能模块视频演示与配音脚本索引库

> **文档用途**：用于指导 Google Cloud TTS 配音生成与独立画面录屏。
> **建议制作流程**：按表格中的【模块分段】分别转换语音音频 -> 分别录制屏幕画面 -> 在剪辑软件中对齐音画。
> **预估总时长**：约 25 分钟。

## 📋 功能模块导航总表

### 1. 实时监控 (REAL-TIME MONITORING)

- [运营总览 (Dashboard Overview)](./realtime_monitor_overview.md)
- [监控中心 (Telemetry Monitoring)](./realtime_monitor_telemetry.md)
- [网络拓扑 (Dynamic Network Topology)](./realtime_monitor_topology.md)

### 2. 终端接入 (TERMINAL ACCESS)

- [操作工作台 (Operation Workspace)](./terminal-access_access_workspace.md)
- [受控审计 (PAM Audit & Session Replay)](./terminal-access_access_pam_audit.md)

### 3. 告警处置 (ALERTS MANAGEMENT)

- [告警中心 (Alert Center Desk)](./alerts_desk.md)
- [历史告警 (Alert History Archive)](./alerts_history.md)
- [告警规则 (Custom Alert Rules)](./alerts_rules.md)
- [维护期管理 (Maintenance Windows)](./alerts_maintenance.md)

### 4. 资产与配置 (ASSETS & CONFIGURATION)

- [资产管理 (Assets Management Dashboard)](./assets-config_assets_dashboard.md)
- [网络设备 (Network Devices Directory)](./assets-config_assets_devices.md)
- [接口监控 (Interface Performance)](./assets-config_assets_interfaces.md)
- [服务器 (Server Resources Monitor)](./assets-config_assets_servers.md)
- [IP/VLAN管理 (IPAM & Subnet Planner)](./assets-config_assets_ipam.md)
- [IP 工具箱 (IP Toolbox Quick Actions)](./assets-config_assets_toolbox.md)
- [标签管理 (Tags Management Editor)](./assets-config_assets_tags.md)
- [机柜管理 (Interactive Rack Layout)](./assets-config_assets_racks.md)

### 5. 配置管理 (CONFIGURATION MANAGEMENT)

- [备份中心 (Config Backup Center)](./config-mgmt_config_backup.md)
- [备份计划 (Config Backup Scheduler)](./config-mgmt_config_schedule.md)
- [配置对比 (Config Diff Engine)](./config-mgmt_config_diff.md)
- [配置搜索 (Config Global Search)](./config-mgmt_config_search.md)
- [配置模板 (Jinja2 Configuration Templates)](./config-mgmt_config_templates.md)

### 6. 自动化 (AUTOMATION PIPELINE)

- [自动化任务 (Playbook Tasks Execution)](./automation_tasks.md)
- [巡检概览 (Inspection Dashboard)](./automation_inspections.md)
- [巡检记录 (Inspection Run Records)](./automation_records.md)
- [执行计划 (Execution Schedules Organizer)](./automation_schedules.md)
- [执行历史 (Execution History Details)](./automation_history.md)
- [定时作业 (Cron Runner Status)](./automation_scheduled_jobs.md)
- [巡检指标 (Inspection Metrics Analyzer)](./automation_metrics.md)
- [解析模板 (TextFSM Parsing Rules)](./automation_textfsm.md)
- [操作管理 (Custom Operations Scripts)](./automation_scripts.md)

### 7. 工单管理 (CHANGE ORDERS & TICKETS)

- [新建工单 (Create New Change Order)](./tickets_change_orders_new.md)
- [个人待办 (My Pending Tasks)](./tickets_change_orders_my_todo.md)
- [组内待办 (Group Tasks Queue)](./tickets_change_orders_group_todo.md)
- [我参与的 (My Participated Orders)](./tickets_change_orders_participated.md)
- [我的关注 (My Starred Favorites)](./tickets_change_orders_focus.md)
- [全部工单 (All Change Orders Board)](./tickets_change_orders_all.md)
- [草稿箱 (My Saved Drafts)](./tickets_change_orders_drafts.md)

### 8. 容量与报表 (CAPACITY & REPORTS)

- [容量分析 (Capacity Planning Analyzer)](./capacity_analysis.md)
- [报表中心 (Unified Reports Center)](./capacity_reports.md)

### 9. 平台管理 (PLATFORM ADMINISTRATION)

- [审计日志 (Unified Audit Logs)](./management_audit.md)
- [用户管理 (RBAC User & Groups Mgmt)](./management_users.md)
- [凭据轮换 (Automated Credentials Rotation)](./management_credentials.md)
- [授权管理 (License Entitlement Manager)](./management_license.md)

---

## 🎬 视频剪辑与视觉排版指南 (Fonts & Styling)

为了让您的演示视频在视觉上完美匹配 NetSops 平台的**极简、未来感、亮青色深色系**科技美学，建议在剪辑时使用以下排版参数：

### 🅰️ 视频字体选型方案
* **中文正文/字幕**：**`OPPO Sans`** 或 **`HarmonyOS Sans` (鸿蒙黑体)**  
  这两款字体系专门为高精细度屏幕设计的现代几何无衬线体。笔画干净利落，字形略微扁宽，在深色或多图视频背景下识别度极高，天生带有一种高级科技硬件的质感。
* **中英文标题/数字卡片**：**`Alibaba PuHuiTi` (阿里巴巴普惠体 2.0 / 3.0 - Bold)** 或 英文 **`Inter`**  
  中英文字形极具现代雕刻感，Bold 字重在制作转场标题时视觉冲击力极强。
* **代码段/黑屏终端演示**：**`JetBrains Mono`** 或 **`Fira Code`**  
  专为程序员和网络工程师打造的代码等宽字体，数字 `0` 和字母 `O` 区分极其明显，字符线条挺拔，天生带有高科技“极客”光环。

### 🎨 字幕排版设置 (剪映/PR)
1. **字号大小**：正文字幕字号控制在 `12` 到 `14` 之间，不要太大，保证画面主体突出。字间距推荐拉宽 `2` 到 `3` 像素，显得呼吸感十足。
2. **文字配色**：一律使用**纯白 (`#FFFFFF`)**。当说到核心亮点词（如“秒级”、“一键点击”）时，可将该词颜色改为**亮青色 (`#00F2FE` 或 `#00E5FF`)**，与 NetSops 的青色调 UI 遥相呼应。
3. **描边与投影**：选择**无描边**，但开启**极淡的黑色柔和阴影**（不透明度 `15% - 20%`，模糊度 `10 - 15`）。在白屏网页和黑屏终端下都极其清晰且高雅。


