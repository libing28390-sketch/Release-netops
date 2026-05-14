# Implementation Plan

## Overview

本实施计划将巡检系统产品化升级分为 10 个 Phase，按依赖顺序执行。核心原则：先写探索测试（在未修复代码上运行，预期失败），再修复，再验证。所有属性测试使用 Hypothesis（后端）和 fast-check（前端）。

> 符号说明：`P1`–`P8` 对应 `design.md §Correctness Properties`；`R1`–`R10` 对应 `requirements.md §Requirements`。

## Tasks

## Phase A — 基础修复与异常分类器（无行为变更，安全先行）

- [x] 1. 修复已知 Bug（R1）

  - [x] 1.1 修复 `analysis.py::summarize_run_analysis()` 数据读取 Bug
    - 将 `res.get('analysis')` 改为 `json.loads(res.get('analysis_json') or '[]')`
    - 添加单元测试：构造含 `analysis_json` 字段的 mock 结果，断言汇总数据正确
    - _Requirements: R1.1_

  - [x] 1.2 修复 TypeScript 类型定义
    - 在 `src/pages/InspectionTab.tsx` 的 `InspectionResult` 接口中添加 `analysis_json: string` 和 `raw_outputs_json: string` 字段
    - 在 `src/pages/ExecutionScheduleTab.tsx` 中同步更新相关类型引用
    - _Requirements: R1.2, R1.3_

- [x] 2. 创建异常分类器模块（R2）

  - [x] 2.1 新建 `backend/core/exception_classifier.py`
    - 定义 `EXCEPTION_TYPES` 字典（6 种类型 + 默认严重程度 + 中文标签）
    - 实现 `classify_exception(raw_error: str, context: str = '') -> dict` 函数，按优先级匹配规则表
    - 实现 `make_finding(exc_type: str, message: str, raw_error: str = '') -> dict` 函数
    - _Requirements: R2.1, R2.2_

  - [x] 2.2 编写异常分类器属性测试（P2 探索测试）
    - 用 Hypothesis 对每种异常类型构造最小触发输入，断言 `classify_exception` 返回正确类型
    - 断言 `make_finding` 返回的 `message` 非空、`type` 在 `EXCEPTION_TYPES` 中
    - _Validates: P2_

  - [x] 2.3 将 `inspection_service.py` 中的异常记录迁移到使用 `make_finding()`
    - 替换所有 `findings.append({'severity': ..., 'message': ...})` 为 `findings.append(make_finding(...))`
    - 为 ICMP 不可达、SSH 端口不通、SSH 认证失败、SSH 超时、SSH 会话中断、Enable 提权失败分别使用正确的异常类型
    - _Requirements: R2.3, R2.4, R2.5, R2.6, R2.7, R2.8_

  - [x] 2.4 处理命令级异常（R2.9–R2.12）
    - 在 `_extract_item_value()` 中检测 `% Invalid input detected`、`% Authorization failed`、`--More--` 残留、`__ERROR__` 前缀
    - 对每种情况写入 `metrics_json[check_key] = {'value': None, 'error': '...'}`，使用标准化错误消息
    - _Requirements: R2.9, R2.10, R2.11, R2.12_

  - [x] 2.5 处理解析级异常（R2.13–R2.16）
    - 在 `parse_with_textfsm()` 中捕获 TextFSM State Error，返回空列表并记录具体错误
    - 在 `_extract_item_value()` 中对模板不存在、解析结果为空、字段缺失、数值转换失败分别写入标准化错误消息
    - _Requirements: R2.13, R2.14, R2.15, R2.16_

---

## Phase B — 系统级异常防护（R10）

- [x] 3. 并发超时防护（R10.1）

  - [x] 3.1 为 `ThreadPoolExecutor` 添加设备级超时
    - 在 `run_inspection()` 的 `as_completed` 循环中，对每个 future 设置 `timeout = _SSH_COMMAND_TIMEOUT + 10`
    - 超时时调用 `make_finding('system_error', '设备采集超时，已跳过')` 并写入结果
    - _Requirements: R10.1_

  - [x] 3.2 数据库写入失败隔离（R10.2）
    - 将 `executemany` 改为逐条 `execute`，每条用独立 try/except 包裹
    - 写入失败时记录日志，跳过该设备，不回滚整次任务
    - _Requirements: R10.2_

  - [x] 3.3 raw_outputs_json 大小限制（R10.3）
    - 在 `_inspect_network_device()` 中，序列化 `raw_outputs_json` 后检查大小
    - 超过 10MB 时截断最长的命令输出，追加 info finding
    - _Requirements: R10.3_

  - [x] 3.4 报表生成异常清理（R10.4）
    - 在 `generate_inspection_excel()` 和 `generate_inspection_html()` 中用 try/finally 确保临时文件被删除
    - _Requirements: R10.4_

  - [x] 3.5 analysis_summary_json 写入容错（R10.5）
    - 在 `run_inspection()` 中将 `analysis_summary_json` 写入包裹在 try/except 中，失败时设为 `'{}'`
    - _Requirements: R10.5_

---

## Phase C — 数据库迁移（R9）

- [x] 4. 数据库 Schema 迁移（R9）

  - [x] 4.1 为 `inspection_results` 添加新列
    - 在 `database.py::_init_db_logic()` 中调用 `ensure_column('inspection_results', 'correlated_risks_json', "TEXT DEFAULT '[]'")`
    - _Requirements: R9.1_

  - [x] 4.2 为 `inspection_items` 添加新列
    - 调用 `ensure_column('inspection_items', 'expected_value', "TEXT DEFAULT ''")`
    - _Requirements: R9.2_

  - [x] 4.3 创建 `inspection_correlation_rules` 表
    - 在 `_init_db_logic()` 中添加 `CREATE TABLE IF NOT EXISTS inspection_correlation_rules (...)` 语句
    - 添加 5 条内置关联规则的 Seed 数据（二层环路/内存泄漏/上行链路劣化/路由协议不稳定/设备过热）
    - _Requirements: R4.4, R4.5_

  - [x] 4.4 编写迁移幂等性属性测试（P8）
    - 用 Hypothesis 对 `ensure_column` 调用 1–5 次，断言 schema 不变、现有数据不变
    - _Validates: P8_

  - [x] 4.5 处理旧版本 NULL 字段兼容（R9.5, R9.6）
    - 在 `inspection_service.py` 和 `report_generator.py` 中所有读取 `analysis_json` 和 `raw_outputs_json` 的地方，使用 `or '[]'` / `or '{}'` 默认值
    - _Requirements: R9.5, R9.6_

---

## Phase D — 关联分析引擎（R4）

- [ ] 5. 实现关联分析引擎（R4）

  - [x] 5.1 编写关联规则触发探索测试（P4 探索测试）
    - 对每条内置规则构造恰好满足所有条件的指标集合（正例）和缺少一个条件的指标集合（负例）
    - 在未实现 `correlate_risk_patterns()` 前运行，预期正例不触发（因函数不存在），记录反例
    - _Validates: P4_

  - [x] 5.2 实现 `correlate_risk_patterns()` 函数
    - 在 `backend/core/analysis.py` 中添加函数，从数据库加载已启用规则，对 metrics 逐一匹配
    - 支持条件操作符：`>`、`<`、`>=`、`<=`、`==`、`!=`
    - 返回触发的关联风险列表，格式含 `rule_name`、`description`、`severity`、`suggestion`、`triggered_metrics`
    - _Requirements: R4.1, R4.2, R4.3_

  - [~] 5.3 将关联分析集成到巡检流程
    - 在 `_inspect_network_device()` 的步骤 7（智能分析）中，调用 `correlate_risk_patterns()`
    - 将结果序列化为 JSON 存入 `inspection_results.correlated_risks_json`
    - _Requirements: R4.2, R4.3_

  - [~] 5.4 关联规则 CRUD API
    - 在 `backend/api/inspections.py` 中添加：
      - `GET /api/inspections/correlation-rules` — 列出所有规则
      - `POST /api/inspections/correlation-rules` — 创建规则
      - `PUT /api/inspections/correlation-rules/{rule_id}` — 更新规则
      - `DELETE /api/inspections/correlation-rules/{rule_id}` — 删除规则
    - _Requirements: R4.5_

  - [~] 5.5 验证关联规则触发属性测试（P4 验证）
    - 重新运行 5.1 的测试，断言正例触发、负例不触发
    - _Validates: P4_

---

## Phase E — 历史趋势 API（R5）

- [ ] 6. 历史趋势 API（R5）

  - [~] 6.1 编写趋势数据有效性探索测试（P6 探索测试）
    - 在数据库中插入包含正常值和 `{value: null, error: ...}` 混合的历史记录
    - 调用趋势 API（未实现时预期 404），记录预期行为
    - _Validates: P6_

  - [~] 6.2 实现趋势 API 端点
    - 在 `backend/api/inspections.py` 中添加 `GET /api/inspections/device/{device_id}/trend`
    - 支持 `metric`（必填）、`days`（默认 30，最大 90）、`run_limit`（默认 100）参数
    - 从 `inspection_results.metrics_json` 中提取指定 metric 的历史值，过滤无效点
    - 返回格式：`{device_id, metric, unit, first_inspection, series: [{ts, value}]}`
    - _Requirements: R5.1, R5.2, R5.3, R5.4, R5.8_

  - [~] 6.3 验证趋势数据有效性属性测试（P6 验证）
    - 重新运行 6.1 的测试，断言返回序列无 null 值且时间升序
    - _Validates: P6_

---

## Phase F — 前端详情页增强（R3）

- [ ] 7. 前端设备详情页增强（R3）

  - [~] 7.1 「指标快照」Tab
    - 在 `ExecutionScheduleTab.tsx` 的巡检设备详情区域添加「指标快照」Tab
    - 解析 `metrics_json`，以键值对列表展示所有指标
    - 正常数值根据阈值显示绿色/橙色/红色
    - `{value: null, error: ...}` 结构用红色文字展示指标名 + 错误原因
    - _Requirements: R3.5, R3.6, R3.7_

  - [~] 7.2 「指标分析」Tab
    - 添加「指标分析」Tab，解析 `analysis_json`，以表格展示（指标名/当前值/状态/诊断结论/建议操作）
    - critical 行红色背景，warning 行橙色背景
    - 若 `correlated_risks_json` 非空，在表格顶部展示关联风险卡片
    - _Requirements: R3.2, R3.3, R3.4, R3.9_

  - [~] 7.3 「指标分析」Tab 趋势按钮
    - 在每个数值型指标行添加「查看趋势」按钮
    - 点击后调用 `GET /api/inspections/device/{device_id}/trend?metric={check_key}` 并以 Recharts 折线图展示
    - 趋势数据为空时展示「暂无历史数据」提示
    - _Requirements: R5.5, R5.6, R5.7_

  - [~] 7.4 「合规检查」Tab
    - 添加「合规检查」Tab，展示 `analysis_json` 中 `category = 'compliance'` 的所有项
    - 通过/失败状态用绿色/红色图标标注
    - _Requirements: R3.8_

---

## Phase G — 报表增强（R6, R7）

- [ ] 8. Excel 报表增强（R6）

  - [~] 8.1 新增「设备资产汇总」Sheet
    - 在 `report_generator.py` 中添加 Sheet，列：设备名称/管理 IP/平台/站点/角色/健康评分/健康状态/合规状态/巡检时间
    - _Requirements: R6.1, R8.6_

  - [~] 8.2 新增「指标横向对比」Sheet
    - 收集所有设备的 `metrics_json`，以设备为行、指标为列生成对比表
    - 超过 `critical_threshold` 的单元格红色背景，超过 `warning_threshold` 的橙色背景
    - _Requirements: R6.2_

  - [~] 8.3 新增「整改建议」Sheet
    - 汇总所有 `analysis_json` 中 `status != 'healthy'` 的条目，按 critical → warning 排序
    - 若有 `correlated_risks`，在顶部单独列出并标注「组合风险」
    - _Requirements: R6.3, R6.4_

  - [~] 8.4 升级「异常明细」Sheet 支持 `type` 字段
    - 在「异常明细」Sheet 中添加「异常类型」列，展示 `findings_json` 中的 `type` 字段（中文）
    - 旧格式（无 `type` 字段）显示「历史记录」
    - _Requirements: R6.5_

  - [~] 8.5 报表生成异常清理（已在 Phase B 3.4 完成，此处验证）
    - 编写测试：模拟 xlsxwriter 抛出异常，断言临时文件被删除，API 返回 HTTP 500
    - _Requirements: R6.6_

  - [~] 8.6 编写报表数据完整性属性测试（P5）
    - 用 Hypothesis 生成 N 台设备结果（含部分异常设备），生成 Excel，断言 Sheet 中设备数 = N
    - _Validates: P5_

- [ ] 9. HTML 报表生成（R7）

  - [~] 9.1 创建 Jinja2 HTML 模板
    - 新建 `backend/templates/inspection_report.html.j2`
    - 包含：报告头部、巡检摘要（含 ECharts 饼图）、关联风险卡片、异常设备列表、指标汇总表、合规检查专项、整改建议列表
    - 内嵌 CSS（深色科技风），ECharts 通过 CDN 加载
    - _Requirements: R7.2, R7.3, R7.4, R7.5_

  - [~] 9.2 实现 `generate_inspection_html()` 函数
    - 在 `report_generator.py` 中添加函数，使用 Jinja2 渲染模板
    - 支持 `customer_name` 和 `engineer_name` 参数
    - 用 try/finally 确保临时文件清理
    - _Requirements: R7.2, R7.6_

  - [~] 9.3 扩展导出 API 支持 `format` 参数
    - 修改 `GET /api/inspections/{run_id}/export`，添加 `format` 查询参数（`xlsx` 默认，`html`）
    - 根据 `format` 调用对应的生成函数，返回对应 MIME 类型
    - 文件名格式：`Nexora_Inspection_{run_id}_{YYYYMMDD}.{ext}`
    - _Requirements: R7.1, R7.7_

  - [~] 9.4 验证 HTML 报表数据完整性属性测试（P5 扩展）
    - 生成 HTML 报表，用 BeautifulSoup 解析，断言设备数量和关键字段存在
    - _Validates: P5_

---

## Phase H — 合规检查体系（R8）

- [ ] 10. 合规检查指标（R8）

  - [~] 10.1 在 `database.py` 中添加合规检查指标 Seed 数据
    - 为 Cisco IOS 添加 6 类合规指标（NTP/Syslog/AAA/Telnet/SSH版本/SNMP社区）
    - 每条指标设置 `category = 'compliance'`、`parse_type`、`expected_value`、`fallback_regex`
    - _Requirements: R8.1, R8.2_

  - [~] 10.2 在 `_extract_item_value()` 中支持合规判定逻辑
    - 当 `parse_type = 'status'` 且 `expected_value` 非空时，将解析结果与 `expected_value` 对比
    - 不匹配则标记为 warning/critical（根据指标配置）
    - _Requirements: R8.3_

  - [~] 10.3 计算并存储合规状态
    - 在 `_inspect_network_device()` 中统计合规检查通过率
    - 全部通过 → `compliant`，部分通过 → `partial`，全部失败 → `non_compliant`
    - 写入 `inspection_results.compliance_status`
    - _Requirements: R8.5_

---

## Phase I — 属性测试全量验证（P1–P8）

- [ ] 11. 全量属性测试验证

  - [~] 11.1 P1 异常不阻断性验证
    - 用 Hypothesis 生成包含 N 台设备的巡检任务，随机注入 k 台设备的连接失败
    - 断言其余 N-k 台设备的结果与无注入时一致
    - _Validates: P1_

  - [~] 11.2 P2 异常完整记录性验证
    - 对每种异常类型（共 16 种，对应 R2.3–R2.16）构造最小触发输入
    - 断言 `findings_json` 或 `metrics_json` 中有对应记录且 `message` 非空
    - _Validates: P2_

  - [~] 11.3 P3 健康评分单调性验证
    - 生成随机 findings 列表（0–20 条），断言 health_score 随 findings 数量增加而不增
    - 边界：0 条 findings → 100 分，ICMP 不通 → 0 分
    - _Validates: P3_

  - [~] 11.4 P7 向后兼容性验证
    - 录制现有 API 的请求/响应快照（`/api/inspections`、`/api/inspections/{id}`、`/api/inspections/{id}/export`）
    - 在新版本部署后重放，断言状态码和必填字段不变
    - _Validates: P7_

---

## Phase J — 集成测试与收尾

- [ ] 12. 集成测试

  - [~] 12.1 端到端巡检流程测试（含异常设备）
    - 构造包含正常设备、ICMP 不通设备、SSH 认证失败设备、命令错误设备的混合场景
    - 断言：`inspection_runs.status = 'completed'`，`inspection_results` 记录数正确，每台设备的 `findings_json` 包含正确的异常类型
    - _Validates: P1, P2_

  - [~] 12.2 报表下载集成测试
    - 触发巡检，下载 Excel 和 HTML 报表
    - 断言：Excel 文件可打开，Sheet 数量 = 7 + 设备数，HTML 文件包含 ECharts 脚本标签
    - _Validates: P5_

  - [~] 12.3 关联分析端到端测试
    - 构造满足「二层环路风险」规则的设备指标，触发巡检
    - 断言：`correlated_risks_json` 包含该规则，前端「指标分析」Tab 展示关联风险卡片
    - _Validates: P4_

---

## Notes

- Phase A 和 Phase B 可以并行开始，Phase C 依赖 Phase A 完成
- Phase D、E、H 可以在 Phase C 完成后并行执行
- Phase F 依赖 Phase D 和 Phase E 都完成
- Phase G 依赖 Phase B、C、D 完成
- 每个 Phase 内的子任务按顺序执行

## Task Dependency Graph

```json
{
  "waves": [
    {"wave": 1, "tasks": ["1.1", "1.2"]},
    {"wave": 2, "tasks": ["2.1"]},
    {"wave": 3, "tasks": ["2.2", "2.3", "2.4", "2.5"]},
    {"wave": 4, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5", "4.1", "4.2", "4.3"]},
    {"wave": 5, "tasks": ["4.4", "4.5"]},
    {"wave": 6, "tasks": ["5.1", "6.1", "10.1"]},
    {"wave": 7, "tasks": ["5.2", "6.2", "10.2"]},
    {"wave": 8, "tasks": ["5.3", "5.4", "6.3", "10.3"]},
    {"wave": 9, "tasks": ["5.5", "7.1"]},
    {"wave": 10, "tasks": ["7.2", "7.3", "7.4", "8.1", "8.2", "8.3", "8.4"]},
    {"wave": 11, "tasks": ["8.5", "8.6", "9.1"]},
    {"wave": 12, "tasks": ["9.2", "9.3"]},
    {"wave": 13, "tasks": ["9.4"]},
    {"wave": 14, "tasks": ["11.1", "11.2", "11.3", "11.4"]},
    {"wave": 15, "tasks": ["12.1", "12.2", "12.3"]}
  ]
}
```
