# Design Document

## Overview

本文档描述巡检系统产品化升级的技术设计方案。在现有成熟基础（Netmiko 采集、TextFSM 解析、健康评分、基础分析、Excel 报表）之上，通过最小侵入性改动实现：异常处理标准化、多指标关联分析、前端详情页增强、历史趋势 API、HTML 报表和合规检查体系。

设计原则：
- **最小侵入**：不重写现有逻辑，只在关键路径上插入新模块
- **向后兼容**：所有新字段通过 `ensure_column` 幂等迁移，现有 API 不变
- **异常一等公民**：每个异常都有类型、严重程度、用户友好描述，不静默失败
- **渐进增强**：每个 Phase 独立可部署，不依赖后续 Phase

---

## Architecture

### 整体数据流（升级后）

```
设备列表
    │
    ▼
_inspect_single_device()
    ├─ _ping_device()          → findings_json (connectivity_error)
    ├─ _check_ssh()            → findings_json (connectivity_error)
    ├─ _netmiko_collect()      → raw_outputs_json
    │   ├─ enable 提权         → findings_json (auth_error, 不阻断)
    │   └─ 命令执行            → 命令级错误标记 (__ERROR__ / % Invalid)
    ├─ _extract_item_value()   → metrics_json
    │   ├─ TextFSM 解析        → parse_error 记录
    │   ├─ fallback_regex      → 兜底
    │   └─ 数值转换            → data_error 记录
    ├─ _classify_exceptions()  ← 【新增】标准化异常分类
    ├─ analyze_device_inspection()
    │   ├─ 单指标阈值判断      → analysis_json
    │   ├─ 历史对比            → analysis_json (trend)
    │   └─ correlate_risk_patterns() ← 【新增】关联分析
    └─ 结果写入 inspection_results

inspection_results
    ├─ findings_json           (连通性/认证/系统硬故障)
    ├─ metrics_json            (指标值 + 采集/解析错误)
    ├─ analysis_json           (单指标分析 + correlated_risks)
    └─ raw_outputs_json        (原始命令输出)

报表生成
    ├─ generate_inspection_excel()  → .xlsx (4+3 Sheet)
    └─ generate_inspection_html()   ← 【新增】→ .html (Jinja2 + ECharts)
```

---

## Components and Interfaces

### 1. Exception Classifier（异常分类器）

**位置**：`backend/core/exception_classifier.py`（新建）

```python
# 异常类型枚举
EXCEPTION_TYPES = {
    'connectivity_error': {'severity': 'critical', 'label': '连通性异常'},
    'auth_error':         {'severity': 'critical', 'label': '认证异常'},
    'command_error':      {'severity': 'warning',  'label': '命令执行异常'},
    'parse_error':        {'severity': 'warning',  'label': '解析异常'},
    'data_error':         {'severity': 'warning',  'label': '数据异常'},
    'system_error':       {'severity': 'warning',  'label': '系统异常'},
}

def classify_exception(raw_error: str, context: str = '') -> dict:
    """
    将原始错误信息分类为标准异常记录。
    返回: {type, severity, message, raw_error}
    """

def make_finding(exc_type: str, message: str, raw_error: str = '') -> dict:
    """
    构造标准 finding 记录，用于写入 findings_json。
    返回: {type, severity, message, raw_error}
    """
```

**分类规则**（按优先级匹配）：

| 原始错误特征 | 分类 | 严重程度 |
|------------|------|---------|
| `NetmikoAuthenticationException` / `Authentication failed` | `auth_error` | critical |
| `NetmikoTimeoutException` / `timed out` | `connectivity_error` | critical |
| `Connection refused` / `errno=111` | `connectivity_error` | critical |
| `SSH session disconnected` / `Connection reset` | `connectivity_error` | warning |
| `Enable mode failed` / `enable` | `auth_error` | warning |
| `% Invalid input detected` | `command_error` | warning |
| `% Authorization failed` | `auth_error` | warning |
| `--More--` 残留 | `command_error` | warning |
| `__ERROR__` 前缀 | `command_error` | warning |
| TextFSM `State Error` | `parse_error` | warning |
| TextFSM 模板不存在 | `parse_error` | info |
| TextFSM 解析结果为空 | `parse_error` | info |
| 数值转换失败 | `data_error` | warning |
| 输出超过 10MB | `data_error` | info |
| 其他 | `system_error` | warning |

---

### 2. Correlation Rule Engine（关联分析引擎）

**位置**：`backend/core/analysis.py`（扩展现有文件）

#### 数据库表：`inspection_correlation_rules`

```sql
CREATE TABLE IF NOT EXISTS inspection_correlation_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    description TEXT DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'warning',  -- critical / warning
    suggestion TEXT DEFAULT '',
    conditions_json TEXT NOT NULL DEFAULT '[]', -- [{metric, op, value}]
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

`conditions_json` 格式：
```json
[
  {"metric": "cisco_ios_cpu", "op": ">", "value": 80},
  {"metric": "cisco_ios_intf_down", "op": ">", "value": 3}
]
```

#### 内置规则（Seed Data）

| 规则名 | 触发条件 | 严重程度 | 建议 |
|--------|---------|---------|------|
| 二层环路风险 | CPU > 80% AND 接口错误 > 100 AND 接口抖动 > 3 | critical | 检查 STP 状态，排查广播风暴 |
| 内存泄漏风险 | 内存 > 85% AND 内存较上次增长 > 10% | warning | 检查内存占用进程，考虑重启 |
| 上行链路劣化 | 上行接口利用率 > 70% AND 接口错误率 > 0.1% | warning | 检查上行链路质量，考虑扩容 |
| 路由协议不稳定 | BGP 邻居 Down > 0 AND OSPF 邻居 Down > 0 | critical | 检查路由协议配置和链路质量 |
| 设备过热风险 | 温度 > 60°C AND CPU > 70% | warning | 检查机房温度和散热系统 |

#### 核心函数

```python
def correlate_risk_patterns(
    metrics: dict,
    rules: list[dict],
    historical_metrics: dict | None = None
) -> list[dict]:
    """
    对单台设备的 metrics 执行所有关联规则匹配。
    返回触发的关联风险列表：
    [{rule_name, description, severity, suggestion, triggered_metrics}]
    """
```

---

### 3. Trend API（历史趋势接口）

**位置**：`backend/api/inspections.py`（新增端点）

```
GET /api/inspections/device/{device_id}/trend
    ?metric=cisco_ios_cpu    # check_key，必填
    &days=30                 # 天数，默认 30，最大 90
    &run_limit=100           # 最多返回的数据点数，默认 100
```

**响应格式**：
```json
{
  "device_id": "xxx",
  "metric": "cisco_ios_cpu",
  "unit": "%",
  "first_inspection": false,
  "series": [
    {"ts": "2026-04-15T10:00:00+08:00", "value": 45.2},
    {"ts": "2026-04-16T10:00:00+08:00", "value": 52.1}
  ]
}
```

**查询逻辑**：
```sql
SELECT checked_at, metrics_json
FROM inspection_results
WHERE device_id = ?
  AND checked_at >= datetime('now', '-{days} days')
ORDER BY checked_at ASC
LIMIT ?
```
从每行的 `metrics_json` 中提取 `metric` 对应的值，过滤掉 `{value: null, error: ...}` 结构的无效点。

---

### 4. Report Generator 增强

**位置**：`backend/core/report_generator.py`（扩展）

#### Excel 新增 Sheet

| Sheet 名 | 数据来源 | 新增 |
|---------|---------|------|
| 巡检概览 | run_info + findings_json + analysis_json | 已有，微调 |
| 异常明细 | findings_json（含 type 字段） | 已有，加 type 列 |
| 异常指标分析明细 | analysis_json | 已有 |
| **设备资产汇总** | inspection_results 基础字段 | **新增** |
| **指标横向对比** | metrics_json 所有设备 | **新增** |
| **整改建议** | analysis_json（非 healthy）+ correlated_risks | **新增** |
| 设备明细（每台） | raw_outputs_json | 已有 |

#### HTML 报表

**位置**：`backend/templates/inspection_report.html.j2`（新建 Jinja2 模板）

模板结构：
```
<!DOCTYPE html>
<html>
<head>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>/* 内嵌 CSS，深色科技风 */</style>
</head>
<body>
  <!-- 1. 报告头部：客户名称、巡检时间、工程师、设备数、健康评分 -->
  <!-- 2. 巡检摘要：健康/告警/严重数量 + 饼图（ECharts） -->
  <!-- 3. 关联风险（若有）：醒目卡片展示 -->
  <!-- 4. 异常设备列表：含异常类型和严重程度 -->
  <!-- 5. 设备指标汇总表：所有设备关键指标 -->
  <!-- 6. 合规检查专项 -->
  <!-- 7. 整改建议列表：按 critical → warning 排序 -->
</body>
</html>
```

新增函数：
```python
def generate_inspection_html(
    run_info: dict,
    results: list[dict],
    output_path: str,
    customer_name: str = '',
    engineer_name: str = '',
) -> str:
    """使用 Jinja2 模板生成 HTML 报表。"""
```

---

### 5. Frontend 增强

#### InspectionResult TypeScript 类型修复

**位置**：`src/pages/InspectionTab.tsx`

```typescript
interface InspectionResult {
  // ... 现有字段 ...
  analysis_json: string;      // 新增
  raw_outputs_json: string;   // 新增
}
```

#### 设备详情页 Tab 结构

**位置**：`src/pages/ExecutionScheduleTab.tsx`（巡检详情部分）

```
设备详情
├─ Tab 1: 原始输出（已有，保留）
├─ Tab 2: 指标快照（新增）
│   └─ metrics_json 键值对列表
│       ├─ 正常值：绿色/橙色/红色（按阈值）
│       └─ 错误值：红色 + 错误原因展示
├─ Tab 3: 指标分析（新增）
│   ├─ correlated_risks 卡片（若有）
│   ├─ analysis_json 表格（指标/值/状态/结论/建议）
│   └─ 每行「查看趋势」按钮 → 折线图弹窗
└─ Tab 4: 合规检查（新增）
    └─ analysis_json 中 category=compliance 的项
```

---

### 6. Compliance Items（合规检查指标）

**位置**：`backend/database.py`（`_build_network_inspection_items` 函数扩展）

内置合规指标（`category = 'compliance'`，`parse_type = 'status'` 或 `'count'`）：

| 指标 | 命令 | 平台 | 检查逻辑 |
|------|------|------|---------|
| NTP 服务器配置 | `show ntp status` | cisco_ios | 解析 `clock is synchronized` 状态 |
| Syslog 配置 | `show logging` | cisco_ios | 统计 logging host 行数，0 则告警 |
| AAA 认证 | `show running-config \| include aaa` | cisco_ios | 检查 `aaa new-model` 是否存在 |
| Telnet 禁用 | `show line vty 0 4` | cisco_ios | 检查 transport input 是否包含 telnet |
| SSH 版本 | `show ip ssh` | cisco_ios | 检查 SSH version 是否为 2.0 |
| SNMP 社区 | `show snmp community` | cisco_ios | 检查是否使用 public/private |

---

## Data Models

### 新增/修改的数据库字段

#### `inspection_results` 表（新增列）

```python
ensure_column('inspection_results', 'correlated_risks_json', "TEXT DEFAULT '[]'")
```

`correlated_risks_json` 格式：
```json
[
  {
    "rule_name": "二层环路风险",
    "description": "CPU 高负载 + 接口错误激增 + 接口抖动，疑似二层环路",
    "severity": "critical",
    "suggestion": "立即检查 STP 状态，执行 show spanning-tree 排查环路",
    "triggered_metrics": {
      "cisco_ios_cpu": 87.5,
      "cisco_ios_intf_errors": 1250,
      "cisco_ios_intf_flapping": 5
    }
  }
]
```

#### `inspection_items` 表（新增列）

```python
ensure_column('inspection_items', 'expected_value', "TEXT DEFAULT ''")
```

`expected_value`：合规检查的期望值，用于 `parse_type = 'status'` 的对比判断。

#### `inspection_correlation_rules` 表（新建）

见 §2 关联分析引擎部分。

### findings_json 格式升级

现有格式：`[{severity, message}]`

升级后格式（向后兼容，新增 `type` 和 `raw_error` 字段）：
```json
[
  {
    "type": "connectivity_error",
    "severity": "critical",
    "message": "设备 ICMP 不可达，请检查设备电源及网络路径",
    "raw_error": ""
  },
  {
    "type": "auth_error",
    "severity": "warning",
    "message": "Enable 提权失败，部分 show 命令可能被拒绝",
    "raw_error": "Enable mode failed: Authentication failed"
  }
]
```

旧格式（无 `type` 字段）的记录在读取时视为 `type = 'legacy'`，不影响展示。

---

## Error Handling

### 异常处理矩阵

| 异常场景 | 发生位置 | 处理方式 | 记录位置 | 是否阻断 |
|---------|---------|---------|---------|---------|
| ICMP 不可达 | `_ping_device()` | 记录 finding，直接返回 | `findings_json` | 仅该设备 |
| SSH 端口不通 | `_check_ssh()` | 记录 finding，直接返回 | `findings_json` | 仅该设备 |
| SSH 认证失败 | `_netmiko_collect()` | 捕获异常，记录 finding | `findings_json` | 仅该设备 |
| SSH 连接超时 | `_netmiko_collect()` | 捕获异常，记录 finding | `findings_json` | 仅该设备 |
| Enable 提权失败 | `_netmiko_collect()` | 记录 warning finding，继续执行 | `findings_json` | **不阻断** |
| 命令 `% Invalid input` | `_extract_item_value()` | 记录 metrics 错误 | `metrics_json[key].error` | 仅该指标 |
| 命令 `% Authorization failed` | `_extract_item_value()` | 记录 metrics 错误 | `metrics_json[key].error` | 仅该指标 |
| `--More--` 残留 | `_extract_item_value()` | 检测并记录 metrics 错误 | `metrics_json[key].error` | 仅该指标 |
| TextFSM 模板不存在 | `parse_with_textfsm()` | 返回空列表，记录 metrics 错误 | `metrics_json[key].error` | 仅该指标 |
| TextFSM State Error | `parse_with_textfsm()` | 捕获异常，记录 metrics 错误 | `metrics_json[key].error` | 仅该指标 |
| TextFSM 解析结果为空 | `_extract_item_value()` | 尝试 fallback_regex，失败则记录错误 | `metrics_json[key].error` | 仅该指标 |
| 数值转换失败 | `_extract_item_value()` | 记录 metrics 错误 | `metrics_json[key].error` | 仅该指标 |
| 关联分析失败 | `correlate_risk_patterns()` | 捕获异常，返回空列表，记录日志 | 日志 | **不阻断** |
| 设备采集超时（线程级） | `ThreadPoolExecutor` | 超时后取消线程，记录 finding | `findings_json` | 仅该设备 |
| 数据库写入失败（单设备） | `run_inspection()` | 记录日志，跳过该设备写入 | 日志 | **不阻断** |
| raw_outputs_json 超 10MB | `_inspect_network_device()` | 截断至 10MB，追加 info finding | `findings_json` | **不阻断** |
| 报表生成失败 | `generate_inspection_excel/html()` | 清理临时文件，向上抛出异常 | API 层 HTTP 500 | 仅报表请求 |
| analysis_summary_json 写入失败 | `run_inspection()` | 设为 `'{}'`，完成任务 | 日志 | **不阻断** |

---

## Testing Strategy

### 单元测试

- `test_exception_classifier.py`：对每种异常类型的分类规则进行参数化测试
- `test_correlation_rules.py`：对每条内置关联规则进行正例/负例测试
- `test_trend_api.py`：测试趋势 API 的边界条件（空数据、混合有效/无效点、时间范围）
- `test_report_generator.py`：测试 Excel 和 HTML 报表生成，含异常设备数据

### 属性测试（PBT）

对应 requirements.md 中的 8 个 Correctness Properties：

- **P1**：用 Hypothesis 生成随机设备集合，注入随机异常，断言非异常设备结果不变
- **P2**：对每种异常类型构造最小触发输入，断言 findings_json 或 metrics_json 中有对应记录
- **P3**：生成随机 findings 列表，断言 health_score 单调不增
- **P4**：对每条关联规则生成正例/负例，断言触发/不触发
- **P5**：生成 N 台设备结果，生成报表，断言报表设备数 = N
- **P6**：插入混合有效/无效历史记录，断言趋势 API 返回序列无 null 且时间升序
- **P7**：录制现有 API 快照，新版本部署后重放，断言状态码和必填字段不变
- **P8**：多次调用 `ensure_column`，断言 schema 不变、数据不变

### 集成测试

- 端到端巡检流程（含异常设备）：断言 `inspection_runs` 状态为 `completed`，`inspection_results` 记录数正确
- 报表下载：断言 Excel 和 HTML 文件可正常打开，Sheet 数量和设备数量正确


---

## Correctness Properties

见 `requirements.md §Correctness Properties`，P1–P8 完整定义在需求文档中，设计层面的实现映射如下：

### Property 1: 异常不阻断性

每台设备的采集和分析逻辑包裹在独立的 try/except 中，异常不传播到其他设备。`ThreadPoolExecutor` 的 `as_completed` 循环捕获每个 future 的异常并记录，不中断整体任务。

**Validates: Requirements 2.17, 2.18, 10.1, 10.2**

### Property 2: 异常完整记录性

`exception_classifier.py` 的 `make_finding()` 函数是所有异常记录的唯一入口。每个异常路径（连通性/认证/命令/解析/数据/系统）都必须调用此函数，确保无静默失败。

**Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16**

### Property 3: 健康评分单调性

`health_score = max(0, 100 - health_deduct)`，`health_deduct` 随 findings 数量单调递增。ICMP 不通时直接返回 `health_score = 0`，无 findings 时 `health_deduct = 0`，`health_score = 100`。

**Validates: Requirements 2.3, 10.3**

### Property 4: 关联规则触发完整性

`correlate_risk_patterns()` 对每条规则检查所有条件，全部满足才追加到 `correlated_risks`，任一条件不满足则跳过。

**Validates: Requirements 4.2, 4.3, 4.4, 4.6, 4.7**

### Property 5: 报表数据完整性

`generate_inspection_excel/html()` 遍历所有 `results`，不跳过任何设备（包括异常设备），确保报表设备数 = `inspection_results` 记录数。

**Validates: Requirements 6.1, 6.2, 6.3, 7.3, 10.4**

### Property 6: 趋势数据有效性

趋势 API 查询时过滤 `{value: null, error: ...}` 结构的无效点，`ORDER BY checked_at ASC` 保证时间升序。

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.8**

### Property 7: 向后兼容性

所有新字段通过 `ensure_column` 添加并有默认值，现有 API 端点签名不变，新增端点不修改旧端点。

**Validates: Requirements 9.4, 9.5, 9.6**

### Property 8: 数据库迁移幂等性

`ensure_column()` 使用 `IF NOT EXISTS` 语义，多次调用安全，不修改已有数据。

**Validates: Requirements 9.1, 9.2, 9.3**
