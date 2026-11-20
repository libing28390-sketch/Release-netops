# 实施计划：Grafana大盘优化与旧SNMP下线

- **任务编号**：`plan_20260919_1100_01_Grafana大盘优化与旧SNMP下线`
- **对应 Walkthrough**：`docs/walkthrough/walkthrough_20260919_1100_01_Grafana大盘优化与旧SNMP下线.md`
- **创建时间**：2026-09-19 11:00

---

## 1. 任务目标与问题背景

用户基于 Grafana 运行界面反馈了以下 6 项核心问题与优化诉求：
1. **`asset_id` 替换为 `hostname`**：Grafana 各大盘和表格中展示了内部 UUID `asset_id`（如 `asset-8ed0cde1955`），不符合运维习惯，需统一替换为可读的 `hostname`（设备名称）。
2. **站点要用名称而不是站点ID**：顶部下拉过滤项当前显示 `site-4cb4ad17a9f3` 内部 ID，要求展示人类可读的真实站点名称（如 `武汉数据中心`、`北京总部` 等）。
3. **筛选支持更多选择选项**：当前仅有站点和设备单/多选，要求扩展支持“厂商（`vendor`）”、“设备角色（`role`）”等更丰富、联动的筛选维度。
4. **接口流量 Top 20 瘦身**：`04 接口流量与健康` 大盘中“端口带宽利用率 Top 20”和“端口错误与丢弃排行 Top 20”展示了过多冗余字段（`Time`, `asset_id`, `job`, `nexora_asset_id` 等），需要评估并精简，只保留关键字段（设备名称、管理 IP、端口号、指标数值）。
5. **下线旧版 SNMP 模板页面**：全面下线废弃的 `/management/snmp-metric-templates` 路由及侧边栏菜单入口，统一收拢到 `/monitoring` 云原生监控平台。
6. **评估并建设独立的互联网出口 Dashboard**：针对 `/monitor/outbound`，评估建立独立的 Grafana 互联网出口大盘的可行性与方案。

---

## 2. 详细技术方案设计

### 2.1 需求 1 & 4：表格字段瘦身与 `asset_id` 替换为 `hostname`
- **根因分析**：
  - VictoriaMetrics 返回的时间序列默认包含全部元数据标签（`asset_id`, `hostname`, `instance`, `job`, `nexora_asset_id`, `tenant_id`, `site_id`, `vendor` 等）。
  - Grafana 默认表格面板未配置 `transformations` 时，会按照英文字母顺序平铺展示所有标签，导致 `asset_id` 赫然在列并排在最前，而 `hostname` 被挤到后面。
- **解决方案**：
  1. **PromQL 层面聚合收敛**：
     - “端口带宽利用率 Top 20”：使用 `topk(20, max by (hostname, instance, ifIndex) ((rate(ifHCInOctets{...}[5m]) * 8) / (ifHighSpeed * 1000000) * 100))`，自动剥离无用内部标签。
     - “端口错误与丢弃排行 Top 20”：使用 `topk(20, sum by (hostname, instance, ifIndex) (rate(ifInErrors{...}[5m]) + rate(ifOutErrors{...}[5m]) + rate(ifInDiscards{...}[5m])))`。
  2. **Grafana 表格面板配置 Organize 变换**：
     - 显式隐藏：`Time`, `__name__`, `asset_id`, `nexora_asset_id`, `job`, `tenant_id`, `site_id`, `role`, `platform` 等。
     - 列重命名与顺序规范化：
       - `hostname` -> `设备名称` (排在第 1 列)
       - `instance` -> `管理 IP` (排在第 2 列)
       - `ifIndex` -> `端口号 (ifIndex)` (排在第 3 列)
       - `Value` -> `带宽利用率` / `错误/丢弃率 (pps)` (排在第 4 列)
  3. **vmagent relabel 清理**：
     - 在 `vmagent/scrape.yml` 中将 `labeldrop` 正则调整为 `regex: "nexora_auth|nexora_.*"`，在采集阶段将内部临时 `nexora_*` 前缀标签全量剥离。

### 2.2 需求 2：站点名称 (`site_name`) 全链路透传
- **当前断点**：
  - `monitoring_compiler.py` 在生成 `vmagent` targets 时只注入了 `nexora_site_id`，缺乏 `nexora_site_name`。
  - `devices` 表中保存的是 `site`，需关联 `sites` 表获取规范的 `site_name`。
- **改造方案**：
  1. `backend/api/monitoring_v1.py`：在 `_load_compile_inputs` 查询设备时关联 `sites` 表：`COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END, '默认站点') AS site_name`。
  2. `backend/services/monitoring_compiler.py`：
     - 在 `Assignment` 数据类中加入 `site_name: str = ""` 属性。
     - 在 `render_target_snapshot` 中输出 `"nexora_site_name": site_name`。
     - 在 `render_vmagent_config` 中增加 relabel 映射：`{"source_labels": ["nexora_site_name"], "target_label": "site_name"}`。
  3. `monitoring/vmagent/scrape.yml`：增加 `nexora_site_name` -> `site_name` 映射。
  4. `generate_dashboards.py`：所有仪表盘的 `site` 变量定义从 `label_values(ifOperStatus, site_id)` 升级为 `label_values(ifOperStatus, site_name)`，下拉菜单直接展示规范人类可读的站点名称！

### 2.3 需求 3：扩展筛选维度（厂商 vendor、角色 role、设备 hostname）
- **改造方案**：
  - 在 `01 网络总览`、`02 设备详情`、`03 无线专网`、`04 接口流量` 以及新建的 `06 互联网出口` 大盘中，建立级联变量体系：
    1. **`site` (站点)**：`label_values(ifOperStatus, site_name)`，支持 All / 多选。
    2. **`vendor` (厂商)**：`label_values(ifOperStatus{site_name=~"$site"}, vendor)`，支持 All / 多选。
    3. **`role` (设备角色)**：`label_values(ifOperStatus{site_name=~"$site",vendor=~"$vendor"}, role)`，支持 All / 多选。
    4. **`device` (设备名称)**：`label_values(ifOperStatus{site_name=~"$site",vendor=~"$vendor",role=~"$role"}, hostname)`，支持 All / 多选（单机详情大盘为单选）。
  - 各面板 PromQL 过滤器统一支持：`{site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"}`。

### 2.4 需求 5：下线旧版 `/management/snmp-metric-templates`
- **清理方案**：
  1. `src/components/AppSidebar/navConfig.ts`：移除 `snmp-metric-templates` 菜单项。
  2. `src/components/DeviceFormModal.tsx`：更新提示文本，将跳转链接由旧页面更新为 `/monitoring`（云原生统一监控）。
  3. `src/utils/routeContext.ts`：将 `/management/snmp-metric-templates` 平滑重定向映射至 `activeTab = 'monitoring'`。
  4. `src/components/AppMainContent.tsx`：清理旧组件渲染分支。
  5. `src/utils/routeContext.test.ts`：同步更新路由重定向断言。

### 2.5 需求 6：评估并建设独立的互联网出口 Dashboard
- **可行性与价值评估**：
  - **评估结论**：**极力推荐并实施**。
  - **原因**：当前 `/monitor/outbound`（OutboundHealthPage）偏重于“业务探测与可用性”（HTTP/DNS/PING 延迟、失败率），而互联网出口链路（WAN / Gateway）带宽负荷、流量走势、突发拥塞、丢包错包是网络运维第一关注点。将其从全网庞杂的 `04 接口流量`（包含内网数千个接入端口）中提炼出来，建立专用的 Grafana 出口大盘，能够形成“外网连通性拨测 + 物理出口带宽时序”的一站式闭环。
- **建设方案**：
  - 新增大盘：`06 互联网出口与 WAN (Internet Outbound & WAN Traffic)` (`nexora-network-outbound`)
  - 核心面板设计：
    - **KPI 统计卡片**：出口总入向带宽、出口总出向带宽、出口峰值利用率、出口丢包/错包速率。
    - **时序面板**：
      - 互联网出口多线路/多网关出入流量趋势图（堆叠/折线）。
      - 各出口边界网关（role='gateway' / role='firewall'）带宽利用率走势。
      - 出口接口实时丢包与错包时序监控。
    - **排行榜与清单表格**：
      - 出口端口带宽利用率排行（瘦身字段：设备名称、管理 IP、端口号、利用率）。
  - **前端注册与联动**：
    - 在 `src/pages/GrafanaDashboardPage.tsx` 的 `GRAFANA_DASHBOARDS` 注册该大盘。
    - 在 `src/pages/OutboundHealthPage.tsx` 页面顶部增加“Grafana 实时出口流量大盘”快捷跳转按钮。

---

## 3. 拟修改文件列表

| 模块 | 文件路径 | 修改说明 |
| :--- | :--- | :--- |
| 后端 API | `backend/api/monitoring_v1.py` | `_load_compile_inputs` 关联 `sites` 获取 `site_name` |
| 后端 Service | `backend/services/monitoring_compiler.py` | `Assignment` 增加 `site_name`，输出 `nexora_site_name` 及 relabel 规则 |
| 采集配置 | `monitoring/vmagent/scrape.yml` | 增加 `nexora_site_name` 映射，精简 `labeldrop` |
| Grafana 构建 | `monitoring/grafana/generate_dashboards.py` | 全面重构变量、Panel PromQL、表格 Organize 变换、新增出口大盘函数 |
| 仪表盘产物 | `monitoring/grafana/dashboards/*.json` | 重新生成 6 套完整工业级 JSON 仪表盘 |
| 前端大盘注册 | `src/pages/GrafanaDashboardPage.tsx` | 注册 `nexora-network-outbound` 大盘元数据 |
| 前端出口页 | `src/pages/OutboundHealthPage.tsx` | 增加直达 Grafana 出口大盘的入口 |
| 菜单与路由 | `src/components/AppSidebar/navConfig.ts` | 移除旧版 `snmp-metric-templates` 菜单 |
| 弹窗组件 | `src/components/DeviceFormModal.tsx` | 将 SNMP 模板外链指向 `/monitoring` |
| 路由与分发 | `src/utils/routeContext.ts`, `AppMainContent.tsx` | 将旧路径平滑重定向至 `/monitoring`，清理渲染分支 |
| 测试与门禁 | `backend/tests/monitoring/test_monitoring_v1_*.py`, `routeContext.test.ts` | 确保编译器契约测试与前端测试全量通过 |

---

## 4. 实施步骤

1. **Step 1**：修改 `backend/services/monitoring_compiler.py`、`backend/api/monitoring_v1.py` 和 `monitoring/vmagent/scrape.yml`，注入 `site_name` 并更新契约测试。
2. **Step 2**：重构 `monitoring/grafana/generate_dashboards.py`：
   - 增加 `vendor`、`role` 变量，`site` 切换为 `site_name`，`device` 切换为 `hostname`。
   - 在 `table_panel` 增加 `organize` 变换，剥离无用字段，保留可读列名。
   - 新增 `build_outbound_dashboard()`。
   - 执行脚本重新生成所有 6 个仪表盘 JSON 文件。
3. **Step 3**：在 `src/pages/GrafanaDashboardPage.tsx` 注册新大盘，并在 `OutboundHealthPage.tsx` 增加联动入口。
4. **Step 4**：下线 `/management/snmp-metric-templates`（菜单、路由重定向、弹窗文案、页面分发）。
5. **Step 5**：运行 pytest 监控测试与前端测试，验证契约与构建正确性。
6. **Step 6**：输出 walkthrough 文档，经用户确认后按规范生成 fix 记录并提交推送。

---

## 5. 验证计划与风险控制

- **验证命令**：
  - `.\.venv\Scripts\pytest.exe backend/tests/monitoring/ -v`
  - `npm test src/utils/routeContext.test.ts`
- **向后兼容**：
  - `site_name` 缺失时自动回退为 `site`、`site_code` 或 `'默认站点'`，不破坏无站点绑定的测试固件。
  - `vmagent` 的 `labeldrop` 保留对 `nexora_auth` 的校验匹配，满足 `test_monitoring_v1_deployment_contract.py` 断言。
