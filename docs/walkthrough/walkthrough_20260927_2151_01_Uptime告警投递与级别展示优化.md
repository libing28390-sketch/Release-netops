# Uptime、告警投递与级别展示优化 Walkthrough

## 完成摘要

- 两个 Uptime Stat 面板统一显示为 Grafana `dtdhms` 时长格式，并关闭面积 sparkline；面板标题改为中文“系统运行时长”和“系统平均运行时长”。
- 告警运营看板的“当前最久未恢复时长”和“未恢复告警时长 P95”使用相同的 `dtdhms` 单值展示并关闭 sparkline，避免斜线趋势背景干扰持续时间读数。
- 24 小时投递成功率面板改名为“24h 告警成功率”，统计口径仍为 24 小时内成功次数 / 已完成尝试数。
- 24 小时通知成功率现按成功次数除以已完成尝试总数计算，分母包含 `succeeded`、`retrying` 和 `failed`。指标源可用但没有已完成尝试时显示“暂无已完成投递”；指标源缺失时仍显示“数据暂不可用”。
- 告警级别卡片及分布图例均改为中文。PromQL 仍以 `critical`、`major` 等 exporter 英文标签查询，未改变后端指标契约。

## 根因与实现

原成功率 PromQL 只把 `succeeded` 和终态 `failed` 加入分母，漏掉 `retrying` 状态代表的已完成失败尝试；同时，在分母为零时通过比较表达式过滤掉结果，所以当日没有完成尝试时面板显示通用无数据。Exporter 查询成功时会为 allowlist 中的 channel/status 组合输出零值序列，因此可用 `count()` 区分“指标源可用但无完成尝试”和“指标族缺失”。新查询仅在前一种情况输出 `-1` sentinel，并由 Grafana value mapping 渲染中文空状态。

告警严重度 exporter 会为九个标准级别都输出聚合序列。看板按级别逐项查询，并设置中文 legend，从而不改存储标签也可本地化显示。

## 实际修改文件

- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/nexora-linux-metrics.json`
- `monitoring/grafana/dashboards/nexora-network-device.json`
- `monitoring/grafana/dashboards/nexora-alert-operations.json`
- `docs/plans/plan_20260927_2151_01_Uptime告警投递与级别展示优化.md`
- `docs/walkthrough/walkthrough_20260927_2151_01_Uptime告警投递与级别展示优化.md`

本轮没有修改后端、数据表、实际通知投递行为或运行中的 Grafana。

## 验证命令与结果

- `python monitoring/grafana/generate_dashboards.py`：成功生成全部 12 个 dashboard JSON；最终差异仅涉及预期的 Linux、网络设备、告警运营 3 个 dashboard。
- `python -m py_compile monitoring/grafana/generate_dashboards.py`：通过。
- 解析 `monitoring/grafana/dashboards/*.json`：12 个 JSON 全部解析成功。
- `git diff --check`：通过。
- 对生成差异的人工检查确认两个 Uptime 面板均为 `unit: dtdhms`、`graphMode: none`；成功率 PromQL 纳入 `retrying`，并保留指标源缺失时的无数据语义；严重度 label selector 保持英文，面板标题与分布 legend 为中文。
- 对生成差异的人工检查确认两张未恢复时长卡片也采用 `unit: dtdhms`、`graphMode: none`；成功率卡片标题为“24h 告警成功率”。

## 未执行验证与剩余风险

- 未运行 pytest 或其他业务测试。本轮只改动 Grafana dashboard 生成器和生成 JSON，遵循当前任务的静态验证范围。
- 未在运行中的 Grafana 执行导入或截图验证，也未在服务器部署。需要将生成后的 dashboard JSON 发布/同步到目标环境后，确认 `dtdhms` 的实际显示样式及“暂无已完成投递” value mapping 的渲染效果。
- 成功率的 sentinel 依赖当前 exporter 的约定：数据库查询成功时零值状态系列也会输出；若 exporter 实现或指标结构改变，应同步调整 availability guard。
- 没有修改现有两个未跟踪的 `dist-*` 目录。
