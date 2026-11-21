# Grafana V2 Actions 测试对齐

## 任务目标

修复 GitHub Actions 中唯一失败的监控测试，使旧断言与当前 Grafana V2 颜色规范一致；确认 S3 容器监控覆盖范围与真实容量告警能力。

## 现状与问题

用户提供的 workflow 输出显示 2,799 passed、1 skipped、1 failed。唯一失败为 `test_wireless_and_interface_dashboards_share_reference_semantic_colors`，测试仍期待 V2 前的颜色值。仓库生成器及当前 dashboard skill 已改用 V2 颜色。

现有运行环境用 cAdvisor 采集 Docker 容器资源，但需要区分容器 CPU/内存/磁盘 I/O 与 SeaweedFS `/data` 剩余空间/S3 Bucket 容量预警。失败用例还直接断言基础 builder，而生产生成流程会应用 V2 presentation 配置，因此一部分旧语义断言也已失效。

## 影响范围

- 只更新 `backend/tests/monitoring/test_domestic_and_wireless_monitoring.py` 的 dashboard 语义测试，让它针对最终 V2 dashboard catalog，并更新过时的颜色、利用率与表格着色断言。
- 不修改生产查询、备份策略、告警通道或 SeaweedFS 运行参数；S3 容量缺口以代码证据说明。
- 增加本任务计划和 walkthrough；当前未获本任务新的提交/推送指令，不执行 Git 提交。

## 实施步骤

1. 将测试改为检查 `build_dashboard_catalog()` 的最终 dashboard，并按 V2 标准色/展示契约更新旧断言。
2. 运行唯一失败测试和 V2 presentation 专项测试确认相关合同。
3. 沿 Compose cAdvisor、vmagent、Dashboard、storage/status 与宿主机告警路径核对 S3 容器监控层次。
4. 归档核对结果与未实现的容量告警缺口。

## 验证计划

`pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py::test_wireless_and_interface_dashboards_share_reference_semantic_colors --noconftest -q -p no:cacheprovider`

`pytest backend/tests/monitoring/test_grafana_v2_presentation.py --noconftest -q -p no:cacheprovider`

S3 部分只读代码审查，不连接虚机、不执行 Compose 或外部存储操作。

## 风险与回滚

测试断言与生产 V2 颜色保持同源；回滚只需恢复该测试的旧颜色断言。存储分析不改变任何配置或对象数据。
