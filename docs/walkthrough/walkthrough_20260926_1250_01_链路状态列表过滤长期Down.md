# 总览链路状态列表过滤长期 Down 接口走查

## 完成摘要

01 网络总览的链路状态卡片和接口列表已从“管理启用且当前 Down 的静态快照”调整为“管理启用、当前仍 Down，且过去 24 小时 ifOperStatus 发生过变化”。长期稳定 Down 接口不会在总览中被重复列为近期变化；接口详情仍保留当前状态查询。

表格现在按 24 小时状态变化次数排序，`Top20` 有了实际排序依据。状态指标缺失时，计数卡显示 No data；已有状态样本但没有符合条件的近期变化时，列表显示“近24h无近期变化”。

## 实际修改文件

- `monitoring/grafana/generate_dashboards.py`：为 Overview 构造近期 Down 变化条件，更新计数、Top20 表格、图例/分组文案和缺省提示。
- `monitoring/grafana/dashboards/nexora-network-overview.json`：重新生成 Overview 配置。
- `docs/plans/plan_20260926_1250_01_链路状态列表过滤长期Down.md`
- 本走查记录。

开始时已有的 Linux 大盘图例调整和 `handoff.md` 用户改动均保留。本次未修改设备详情大盘的当前状态面板。

## 验证命令与结果

- `python monitoring/grafana/generate_dashboards.py`：成功生成 9 份仪表盘 JSON。
- `python -m py_compile monitoring/grafana/generate_dashboards.py`：通过。
- Python JSON 解析与配置断言：9 个 JSON 全部可解析；Overview 卡片和表格均包含 24h 状态变化、当前 oper Down、admin Up 条件；状态指标缺失时卡片不回退为 0。
- `git diff --check`：通过。
- 检查完整生成差异：本次只新增 Overview JSON 差异；已有 Linux Metrics JSON 差异来自前序未提交任务，未覆盖。

## 未执行验证及原因

- 未把 JSON 写入或部署到运行中的 Grafana，没有对活动页面进行最终视觉验证。
- 未运行业务测试套件；本次改动限制在仪表盘 PromQL 和显示配置，按计划做了生成、Python 编译及 JSON/查询条件验证。

## 剩余风险与后续建议

- 这个过滤会隐藏所有 24 小时以上没有状态变化的 Down 接口，包括预期闲置端口和长期真实故障；详情页仍能查询当前状态，但总览不会再提醒它们。
- 若需要长期故障持续告警，同时排除已知备用口，后续应给接口增加明确的“预期 Up/预期 Down/不监控”状态或维护抑制策略，再以预期状态和实际状态比较，不能只凭持续时间推断端口是否异常。
- 回滚时恢复 Overview 原有 admin-up/oper-down 静态筛选和对应文字，再运行生成器。
