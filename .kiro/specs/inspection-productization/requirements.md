# Requirements Document

## Introduction

本文档描述对现有网络设备自动化巡检系统（Nexora NetOps）的产品化升级需求。系统已具备 SSH 登录采集、TextFSM 解析、健康评分、基础风险分析和 Excel 报表能力。本次升级的核心目标是：将异常处理提升为一等公民、构建多指标关联分析引擎、增强前端可视化、新增 HTML 报表和历史趋势 API，并引入合规检查体系，使系统达到可对外交付的产品化水准。

---

## Glossary

- **Inspection_Engine**：巡检引擎，负责协调连通性探测、命令采集、解析和分析的核心服务（`inspection_service.py`）。
- **Analysis_Engine**：分析引擎，负责单设备指标阈值判断、历史对比和多指标关联分析（`analysis.py`）。
- **Report_Generator**：报表生成器，负责生成 Excel 和 HTML 格式的巡检报告（`report_generator.py`）。
- **TextFSM_Parser**：TextFSM 解析器，负责将 CLI 原始输出转换为结构化记录（`textfsm.py`）。
- **Exception_Classifier**：异常分类器，负责将所有异常归类为标准异常类型并附加严重程度和用户友好描述的模块。
- **Inspection_Run**：一次完整的巡检任务，对应数据库表 `inspection_runs` 中的一条记录。
- **Inspection_Result**：单台设备的巡检结果，对应数据库表 `inspection_results` 中的一条记录。
- **Inspection_Item**：巡检指标定义，对应数据库表 `inspection_items` 中的一条记录，包含命令、解析规则和阈值。
- **metrics_json**：`inspection_results` 表中存储采集到的结构化指标键值对的 JSON 字段，格式为 `{check_key: value}` 或 `{check_key: {value: null, error: "..."}}` 。
- **findings_json**：`inspection_results` 表中存储连通性和采集层硬故障列表的 JSON 字段，每项含 `severity` 和 `message`。
- **analysis_json**：`inspection_results` 表中存储智能分析结果列表的 JSON 字段，每项含 `metric`、`status`、`conclusion`、`suggestion`。
- **raw_outputs_json**：`inspection_results` 表中存储各命令原始 CLI 输出的 JSON 字段，格式为 `{command: output_text}`。
- **analysis_summary_json**：`inspection_runs` 表中存储整次巡检汇总分析结论的 JSON 字段。
- **correlated_risks**：`analysis_json` 中的新子字段，存储多指标关联分析发现的组合风险列表。
- **Correlation_Rule**：关联规则，定义触发组合风险所需的多个指标条件及其组合逻辑。
- **Compliance_Item**：合规检查指标，属于 `inspection_items` 中 `category = 'compliance'` 的特殊指标，用于检查 NTP/Syslog/AAA/危险服务等配置规范。
- **Health_Score**：健康评分，0–100 的整数，由基础分 100 按异常扣分得出，存储在 `inspection_results.health_score`。
- **Exception_Type**：标准异常类型枚举，包含 `connectivity_error`、`auth_error`、`command_error`、`parse_error`、`data_error`、`system_error`。
- **Severity**：严重程度枚举，包含 `critical`（严重）、`warning`（告警）、`info`（提示）。
- **ensure_column**：系统已有的幂等数据库列迁移函数，用于安全地向现有表添加新列。
- **Trend_API**：历史趋势查询接口，返回指定设备指定指标在时间范围内的历史值序列。
- **HTML_Report**：基于 Jinja2 模板和内嵌 ECharts CDN 生成的 HTML 格式巡检报告，适合对外交付。

---

## Requirements

### 需求 1：已知 Bug 修复

**用户故事：** 作为系统维护者，我希望修复已知的数据读取 Bug，以确保分析汇总和前端展示功能正确运行。

#### 验收标准

1. WHEN `summarize_run_analysis()` 被调用时，THE `Analysis_Engine` SHALL 通过 `json.loads(res.get('analysis_json') or '[]')` 读取每台设备的分析结果，而非使用 `res.get('analysis')`。
2. THE `InspectionResult` TypeScript 类型 SHALL 包含 `analysis_json: string` 字段。
3. THE `InspectionResult` TypeScript 类型 SHALL 包含 `raw_outputs_json: string` 字段。
4. WHEN 前端请求巡检详情时，THE 前端 SHALL 能够正确解析并展示 `analysis_json` 和 `raw_outputs_json` 字段内容。

---

### 需求 2：异常分类标准化

**用户故事：** 作为网络运维工程师，我希望所有异常都有统一的分类、严重程度和中文描述，以便快速定位问题根因并向客户清晰说明。

#### 验收标准

1. THE `Exception_Classifier` SHALL 将所有异常归入以下六类之一：`connectivity_error`（连通性异常）、`auth_error`（认证异常）、`command_error`（命令执行异常）、`parse_error`（解析异常）、`data_error`（数据异常）、`system_error`（系统异常）。
2. THE `Exception_Classifier` SHALL 为每类异常分配默认严重程度：`connectivity_error` 和 `auth_error` 为 `critical`，`command_error` 和 `parse_error` 为 `warning`，`data_error` 和 `system_error` 为 `warning`。
3. WHEN 设备 ICMP 不可达时，THE `Inspection_Engine` SHALL 在 `findings_json` 中记录 `{type: "connectivity_error", severity: "critical", message: "设备 ICMP 不可达，请检查设备电源及网络路径"}`。
4. WHEN SSH 端口不通时，THE `Inspection_Engine` SHALL 在 `findings_json` 中记录 `{type: "connectivity_error", severity: "critical", message: "SSH 端口 {port} 不通，请检查防火墙策略或 SSH 服务状态"}`。
5. WHEN SSH 认证失败时，THE `Inspection_Engine` SHALL 在 `findings_json` 中记录 `{type: "auth_error", severity: "critical", message: "SSH 认证失败，请核查账号密码或密钥配置"}`。
6. WHEN SSH 连接超时时，THE `Inspection_Engine` SHALL 在 `findings_json` 中记录 `{type: "connectivity_error", severity: "critical", message: "SSH 连接超时，设备响应缓慢或网络延迟过高"}`。
7. WHEN SSH 会话中断时，THE `Inspection_Engine` SHALL 在 `findings_json` 中记录 `{type: "connectivity_error", severity: "warning", message: "SSH 会话意外中断，设备可能已重启或连接被重置"}`。
8. WHEN Enable 提权失败时，THE `Inspection_Engine` SHALL 在 `findings_json` 中记录 `{type: "auth_error", severity: "warning", message: "Enable 提权失败，部分 show 命令可能被拒绝，请检查 enable secret 或 AAA 配置"}` 并继续执行后续命令。
9. WHEN 命令输出包含 `% Invalid input detected` 时，THE `Inspection_Engine` SHALL 在对应指标的 `metrics_json` 中记录 `{value: null, error: "命令不存在或设备不支持该命令"}`。
10. WHEN 命令输出包含 `% Authorization failed` 时，THE `Inspection_Engine` SHALL 在对应指标的 `metrics_json` 中记录 `{value: null, error: "命令执行权限不足，请检查账号授权级别"}`。
11. WHEN 命令输出包含 `__ERROR__` 前缀时，THE `Inspection_Engine` SHALL 将该命令的所有关联指标标记为 `{value: null, error: "命令执行失败: {原始错误信息}"}`。
12. WHEN 命令输出包含 `--More--` 残留时，THE `Inspection_Engine` SHALL 在对应指标的 `metrics_json` 中记录 `{value: null, error: "命令输出分页符未清除，请检查终端分页配置"}`。
13. WHEN TextFSM 模板不存在时，THE `TextFSM_Parser` SHALL 在对应指标的 `metrics_json` 中记录 `{value: null, error: "未找到 {platform}/{command} 的解析模板"}`。
14. WHEN TextFSM 解析结果为空时，THE `TextFSM_Parser` SHALL 在对应指标的 `metrics_json` 中记录 `{value: null, error: "TextFSM 解析结果为空，输出格式可能与模板不匹配"}`。
15. WHEN TextFSM 解析字段缺失时，THE `TextFSM_Parser` SHALL 在对应指标的 `metrics_json` 中记录 `{value: null, error: "解析字段 {field_name} 在结果中不存在"}`。
16. WHEN 数值转换失败时，THE `TextFSM_Parser` SHALL 在对应指标的 `metrics_json` 中记录 `{value: null, error: "字段值 '{raw_value}' 无法转换为数字"}`。
17. IF 某台设备发生任意类型异常，THEN THE `Inspection_Engine` SHALL 继续对其他设备和其他指标执行巡检，不阻断整体任务。
18. WHEN 并发巡检中某台设备超时，THE `Inspection_Engine` SHALL 在超过 `_SSH_COMMAND_TIMEOUT` 后强制终止该设备的采集线程，并在 `findings_json` 中记录 `{type: "system_error", severity: "warning", message: "设备采集超时，已跳过"}`。

---

### 需求 3：前端设备详情页增强

**用户故事：** 作为网络运维工程师，我希望在设备详情页看到结构化的指标分析和指标快照，而不只是原始命令输出，以便快速判断设备健康状态。

#### 验收标准

1. WHEN 用户打开设备详情页时，THE 前端 SHALL 展示至少以下四个 Tab：「原始输出」、「指标快照」、「指标分析」、「合规检查」。
2. WHEN 用户切换到「指标分析」Tab 时，THE 前端 SHALL 以表格形式展示 `analysis_json` 中的每一项，列包含：指标名称、当前值、状态、诊断结论、建议操作。
3. WHEN `analysis_json` 中某项的 `status` 为 `critical` 时，THE 前端 SHALL 以红色背景高亮该行。
4. WHEN `analysis_json` 中某项的 `status` 为 `warning` 时，THE 前端 SHALL 以橙色背景高亮该行。
5. WHEN 用户切换到「指标快照」Tab 时，THE 前端 SHALL 以键值对列表展示 `metrics_json` 中的所有指标。
6. WHEN `metrics_json` 中某指标的值为 `{value: null, error: "..."}` 结构时，THE 前端 SHALL 以红色文字展示该指标名称，并在旁边显示具体错误原因。
7. WHEN `metrics_json` 中某指标的值为正常数值时，THE 前端 SHALL 根据对应 `Inspection_Item` 的阈值配置，对超过 `critical_threshold` 的值用红色显示，超过 `warning_threshold` 的值用橙色显示。
8. WHEN 用户切换到「合规检查」Tab 时，THE 前端 SHALL 展示 `analysis_json` 中 `category = 'compliance'` 的所有合规检查结果。
9. WHEN `correlated_risks` 字段存在于 `analysis_json` 时，THE 前端 SHALL 在「指标分析」Tab 顶部以醒目卡片形式展示关联风险列表。
10. THE `InspectionResult` TypeScript 类型 SHALL 包含 `analysis_json: string`、`raw_outputs_json: string` 字段，且类型定义与后端返回数据保持一致。

---

### 需求 4：多指标关联分析引擎

**用户故事：** 作为网络运维工程师，我希望系统能自动识别多个指标同时异常时的组合风险（如二层环路、内存泄漏），而不只是孤立地报告单个指标超阈值。

#### 验收标准

1. THE `Analysis_Engine` SHALL 支持可配置的关联规则，每条规则定义：规则名称、触发条件（多个指标的阈值组合）、风险描述、建议操作、严重程度。
2. WHEN `Analysis_Engine` 执行分析时，THE `Analysis_Engine` SHALL 对每台设备的 `metrics_json` 逐一匹配所有已启用的关联规则。
3. WHEN 某台设备的指标满足某条关联规则的所有触发条件时，THE `Analysis_Engine` SHALL 将该关联风险追加到 `analysis_json` 的 `correlated_risks` 列表中，格式为 `{rule_name, description, severity, suggestion, triggered_metrics}`。
4. THE `Analysis_Engine` SHALL 内置至少以下三条关联规则：
   - 规则 1（二层环路风险）：CPU 利用率 > 80% 且接口错误计数增量 > 100 且接口抖动次数 > 3，严重程度 `critical`。
   - 规则 2（内存泄漏风险）：内存利用率 > 85% 且内存利用率较上次增长 > 10%，严重程度 `warning`。
   - 规则 3（上行链路劣化风险）：上行接口利用率 > 70% 且接口错误率 > 0.1%，严重程度 `warning`。
5. WHERE 关联规则存储在数据库中，THE `Analysis_Engine` SHALL 支持通过 API 对关联规则进行增删改查，无需重启服务即可生效。
6. WHEN 关联规则配置文件或数据库中无任何规则时，THE `Analysis_Engine` SHALL 跳过关联分析步骤，不影响单指标分析结果。
7. WHEN 关联分析执行失败时，THE `Analysis_Engine` SHALL 记录错误日志并将 `correlated_risks` 设为空列表，不影响 `analysis_json` 中其他字段。

---

### 需求 5：历史趋势 API 与前端展示

**用户故事：** 作为网络运维工程师，我希望能查看某台设备某个指标在过去 N 天的历史变化趋势，以便判断是否存在持续恶化的问题。

#### 验收标准

1. THE 后端 SHALL 提供 `GET /api/inspections/device/{device_id}/trend` 接口，支持查询参数 `metric`（指标 check_key）和 `days`（天数，默认 30，最大 90）。
2. WHEN 请求历史趋势接口时，THE 后端 SHALL 返回格式为 `{device_id, metric, unit, series: [{ts, value}]}` 的 JSON 响应，`series` 按时间升序排列。
3. WHEN 指定 `metric` 在历史记录中不存在时，THE 后端 SHALL 返回 `{series: []}` 而非错误响应。
4. WHEN 设备首次巡检（无历史数据）时，THE 后端 SHALL 返回 `{series: []}` 并在响应中包含 `first_inspection: true` 标志。
5. WHEN 用户在设备详情页切换到「指标分析」Tab 时，THE 前端 SHALL 在每个数值型指标旁提供「查看趋势」按钮。
6. WHEN 用户点击「查看趋势」按钮时，THE 前端 SHALL 调用趋势 API 并以折线图（使用已有 Recharts 组件）展示该指标的历史趋势。
7. WHEN 趋势数据为空时，THE 前端 SHALL 展示「暂无历史数据，首次巡检后将自动记录」提示。
8. THE 趋势 API SHALL 仅返回 `metrics_json` 中值为有效数值（非 `{value: null, error: ...}` 结构）的历史记录点。

---

### 需求 6：Excel 报表增强

**用户故事：** 作为项目交付工程师，我希望 Excel 报表包含设备资产汇总、指标横向对比和整改建议，以便直接用于客户汇报。

#### 验收标准

1. THE `Report_Generator` SHALL 在现有 Excel 报表基础上新增「设备资产汇总」Sheet，包含列：设备名称、管理 IP、平台、站点、角色、健康评分、健康状态、本次巡检时间。
2. THE `Report_Generator` SHALL 新增「指标横向对比」Sheet，以设备为行、指标为列，展示所有设备的关键指标值，超阈值单元格用红色/橙色背景标注。
3. THE `Report_Generator` SHALL 新增「整改建议」Sheet，汇总所有 `analysis_json` 中 `status != 'healthy'` 的条目，列包含：设备名称、指标名称、当前值、状态、诊断结论、建议操作、优先级。
4. WHEN `correlated_risks` 不为空时，THE `Report_Generator` SHALL 在「整改建议」Sheet 顶部单独列出关联风险，并标注「组合风险」标签。
5. WHEN 某设备的 `findings_json` 包含 `type` 字段时，THE `Report_Generator` SHALL 在「异常明细」Sheet 中展示异常类型（中文）和严重程度。
6. WHEN 报表生成失败时，THE `Report_Generator` SHALL 捕获异常、清理临时文件，并向调用方返回包含错误原因的异常，不留下孤立临时文件。

---

### 需求 7：HTML 报表生成

**用户故事：** 作为项目交付工程师，我希望能生成一份美观的 HTML 报表，内嵌图表，适合直接发送给客户或在浏览器中展示。

#### 验收标准

1. THE 后端 SHALL 在 `GET /api/inspections/{run_id}/export` 接口上支持 `format` 查询参数，当 `format=html` 时返回 HTML 文件，当 `format=xlsx`（默认）时返回 Excel 文件。
2. THE `Report_Generator` SHALL 使用 Jinja2 模板生成 HTML 报表，模板内嵌 ECharts CDN 链接（不依赖本地文件）。
3. THE HTML 报表 SHALL 包含以下内容：巡检概览（总设备数、健康/告警/严重数量、平均健康评分）、健康评分分布饼图（ECharts）、异常设备列表（含异常类型和严重程度）、各设备指标汇总表、整改建议列表。
4. WHEN `correlated_risks` 不为空时，THE HTML 报表 SHALL 在异常设备列表中以醒目样式展示关联风险。
5. THE HTML 报表 SHALL 为独立的单文件 HTML，可在无网络环境下通过浏览器打开（ECharts 通过 CDN 加载，其余内容内嵌）。
6. WHEN HTML 报表生成失败时，THE `Report_Generator` SHALL 清理临时文件并向调用方返回包含错误原因的异常。
7. THE HTML 报表文件名 SHALL 遵循格式 `Nexora_Inspection_{run_id}_{YYYYMMDD}.html`。

---

### 需求 8：合规检查体系

**用户故事：** 作为网络安全工程师，我希望巡检系统能自动检查设备的 NTP、Syslog、AAA、危险服务等配置规范，并在报表中有专项展示。

#### 验收标准

1. THE `Inspection_Engine` SHALL 支持在 `inspection_items` 表中定义 `category = 'compliance'` 的合规检查指标。
2. THE 系统 SHALL 内置至少以下六类合规检查指标：NTP 服务器配置、Syslog 服务器配置、AAA 认证配置、Telnet 服务禁用状态、SSH 版本（应为 SSHv2）、SNMP 社区字符串安全性（不应使用 `public`/`private`）。
3. WHEN 合规检查指标的 `parse_type = 'status'` 时，THE `Inspection_Engine` SHALL 将解析结果与 `expected_value` 字段对比，不匹配则标记为 `warning` 或 `critical`。
4. WHEN 合规检查指标的 `parse_type = 'count'` 时，THE `Inspection_Engine` SHALL 将记录数与 `warning_threshold` 对比，记录数为 0 则标记为 `warning`（表示未配置）。
5. WHEN 巡检完成时，THE `Inspection_Engine` SHALL 统计每台设备的合规检查通过率，并将结果存入 `inspection_results.compliance_status`（`compliant`/`non_compliant`/`partial`）。
6. THE `Report_Generator` SHALL 在 Excel 报表的「设备资产汇总」Sheet 中包含合规状态列。
7. THE HTML 报表 SHALL 包含合规检查专项章节，展示每台设备各合规项的通过/失败状态。

---

### 需求 9：数据库迁移兼容性

**用户故事：** 作为系统管理员，我希望所有新增数据库字段都通过幂等迁移机制添加，不破坏现有数据和 API 的向后兼容性。

#### 验收标准

1. THE 系统 SHALL 使用现有的 `ensure_column` 函数为 `inspection_results` 表添加所有新列，包括：`exception_type`（TEXT）、`correlated_risks_json`（TEXT）。
2. THE 系统 SHALL 使用 `ensure_column` 为 `inspection_items` 表添加新列：`category`（TEXT，默认 `'general'`）、`expected_value`（TEXT）。
3. WHEN `ensure_column` 被多次调用时，THE 系统 SHALL 幂等地执行，不抛出异常，不修改已有数据。
4. THE 所有新增 API 端点 SHALL 与现有 API 端点共存，不修改现有端点的请求/响应格式。
5. WHEN 旧版本数据库中 `analysis_json` 字段为 `NULL` 时，THE 系统 SHALL 将其视为空列表 `[]` 处理，不抛出解析异常。
6. WHEN 旧版本数据库中 `raw_outputs_json` 字段为 `NULL` 时，THE 系统 SHALL 将其视为空字典 `{}` 处理，不抛出解析异常。

---

### 需求 10：系统级异常防护

**用户故事：** 作为系统管理员，我希望系统在面对并发超时、数据库写入失败、报表生成失败等系统级异常时能优雅降级，不影响其他正在进行的巡检任务。

#### 验收标准

1. WHEN 并发巡检中某台设备的采集线程超过 `_SSH_COMMAND_TIMEOUT + 10` 秒时，THE `Inspection_Engine` SHALL 强制取消该线程，记录超时异常，并继续处理其他设备结果。
2. WHEN 数据库写入单台设备结果失败时，THE `Inspection_Engine` SHALL 记录错误日志，跳过该设备的写入，并继续写入其他设备结果，不回滚整次巡检任务。
3. WHEN `raw_outputs_json` 单个字段超过 10MB 时，THE `Inspection_Engine` SHALL 截断原始输出至 10MB 并在 `findings_json` 中追加 `{type: "data_error", severity: "info", message: "原始输出超过 10MB，已截断"}`。
4. WHEN 报表生成过程中发生异常时，THE `Report_Generator` SHALL 删除已创建的临时文件，并向 API 层返回包含错误原因的异常，API 层返回 HTTP 500 响应。
5. WHEN `analysis_summary_json` 写入失败时，THE `Inspection_Engine` SHALL 将 `analysis_summary_json` 设为 `'{}'` 并完成巡检任务，不将整次任务标记为失败。



---

## Correctness Properties

以下属性用于指导属性测试（Property-Based Testing），确保系统在各种输入下的行为符合规范。

### P1：异常不阻断性（Exception Non-Blocking）

**定义**：对任意设备集合 `D`，若其中设备 `d_i` 发生任意类型异常（连通性/认证/命令/解析/数据/系统），其余设备 `D \ {d_i}` 的巡检结果不受影响。

**形式化**：`∀ run, ∀ d_i ∈ run.devices: exception(d_i) ⟹ ∀ d_j ≠ d_i: result(d_j) = result_without_d_i(d_j)`

**测试策略**：生成包含 N 台设备的巡检任务，随机注入 k 台设备的连接失败，断言其余 N-k 台设备的结果与无注入时一致。

---

### P2：异常完整记录性（Exception Complete Recording）

**定义**：每种已知异常类型都必须在 `findings_json` 或 `metrics_json` 中有对应记录，不存在"静默失败"（silent failure）。

**形式化**：`∀ exception_event e: ∃ record r ∈ (findings_json ∪ metrics_json_errors): r.type = classify(e) ∧ r.message ≠ ''`

**测试策略**：对每种异常类型（ICMP 不通、SSH 认证失败、命令错误、TextFSM 解析失败等）构造最小触发输入，断言对应记录存在且 `message` 非空。

---

### P3：健康评分单调性（Health Score Monotonicity）

**定义**：设备的 `health_score` 随异常数量增加而单调不增；无异常时为 100，ICMP 不通时为 0。

**形式化**：`findings_count(d) ≤ findings_count(d') ⟹ health_score(d) ≥ health_score(d')`，且 `ping_ok(d) = 0 ⟹ health_score(d) = 0`，且 `findings_count(d) = 0 ⟹ health_score(d) = 100`

**测试策略**：生成随机 findings 列表，断言 health_score 随 findings 数量增加而不增，边界条件（0 个 findings → 100 分，ICMP 不通 → 0 分）严格成立。

---

### P4：关联规则触发完整性（Correlation Rule Completeness）

**定义**：若设备指标满足某关联规则的所有触发条件，则该规则必须出现在 `correlated_risks` 中；若不满足任一条件，则该规则不出现。

**形式化**：`∀ rule r, ∀ device d: (∀ cond c ∈ r.conditions: satisfies(d, c)) ⟺ r ∈ correlated_risks(d)`

**测试策略**：对每条内置关联规则，生成恰好满足所有条件的指标集合（正例）和缺少一个条件的指标集合（负例），断言正例触发规则、负例不触发。

---

### P5：报表数据完整性（Report Data Completeness）

**定义**：Excel 和 HTML 报表中展示的设备数量等于 `inspection_results` 中该 `run_id` 的记录数，不存在数据丢失或重复。

**形式化**：`|report.devices| = |inspection_results WHERE run_id = run.id|`，且 `∀ d ∈ inspection_results: d ∈ report.devices`

**测试策略**：生成包含 N 台设备的巡检结果（含部分异常设备），生成报表后断言报表中设备数量 = N，且每台设备的 hostname 和 IP 均出现在报表中。

---

### P6：趋势数据有效性（Trend Data Validity）

**定义**：趋势 API 返回的序列中，每个数据点的值必须是有效数值（非 null、非 error 结构），且时间戳严格升序。

**形式化**：`∀ point p ∈ trend.series: isNumber(p.value) ∧ p.value ≠ null`，且 `∀ i < j: series[i].ts < series[j].ts`

**测试策略**：在数据库中插入包含正常值和 `{value: null, error: ...}` 混合的历史记录，调用趋势 API，断言返回序列中无 null 值且时间戳严格升序。

---

### P7：向后兼容性（Backward Compatibility）

**定义**：所有现有 API 端点在新版本部署后，对旧格式请求的响应与旧版本一致（状态码、必填字段、数据类型不变）。

**形式化**：`∀ request req ∈ legacy_requests: response_new(req).status = response_old(req).status ∧ response_new(req).required_fields ⊇ response_old(req).required_fields`

**测试策略**：录制现有 API 的请求/响应快照，在新版本部署后重放，断言状态码和必填字段不变（允许新增字段）。

---

### P8：数据库迁移幂等性（Migration Idempotency）

**定义**：`ensure_column` 被调用任意次数后，数据库 schema 与调用一次的结果相同，且现有数据不被修改。

**形式化**：`∀ n ≥ 1: schema_after_n_calls = schema_after_1_call ∧ existing_data_unchanged`

**测试策略**：在测试数据库上调用 `ensure_column` 3 次，断言 schema 不变、现有行数据不变、不抛出异常。
