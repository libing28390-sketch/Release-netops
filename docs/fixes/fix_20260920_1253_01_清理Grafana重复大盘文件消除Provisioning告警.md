# 修复记录 - 清理 Grafana 重复大盘文件消除 Provisioning 告警

## 1. 问题现象
Grafana 容器启动和重新探测 provisioning 目录时输出告警：
`level=warn msg="Not saving new dashboard due to restricted database access" provisioner="Nexora dashboards" file=/var/lib/grafana/dashboards/network-wireless.json folderId=1`

## 2. 根因分析
`monitoring/grafana/generate_dashboards.py` 之前为了兼容两套命名，同时生成了 `nexora-*.json` 和 `*.json` 两组大盘文件并存放在同一目录下，它们的内部 `uid` 完全相同。
Grafana 加载第一个文件后，发现第二个文件 UID 相同且当前数据库处于只读 Provisioning 状态，因而抛出警告跳过保存。

## 3. 解决方案
1. 精简 `generate_dashboards.py`，统一仅生成带 `nexora-` 规范前缀的 8 个大盘文件。
2. 从 `monitoring/grafana/dashboards/` 目录下删除 8 个多余的无前缀重名文件。

## 4. 实际修改文件
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/linux-metrics.json` (删除)
- `monitoring/grafana/dashboards/monitoring-health.json` (删除)
- `monitoring/grafana/dashboards/network-device.json` (删除)
- `monitoring/grafana/dashboards/network-interface.json` (删除)
- `monitoring/grafana/dashboards/network-outbound.json` (删除)
- `monitoring/grafana/dashboards/network-overview.json` (删除)
- `monitoring/grafana/dashboards/network-wireless.json` (删除)
- `monitoring/grafana/dashboards/windows-metrics.json` (删除)
- `docs/plans/plan_20260920_1253_01_清理Grafana重复大盘文件消除Provisioning告警.md`
- `docs/walkthrough/walkthrough_20260920_1253_01_清理Grafana重复大盘文件消除Provisioning告警.md`

## 5. 验证命令与结果
- 重新运行 `python monitoring/grafana/generate_dashboards.py`，确认仅输出 8 个唯一的 `nexora-*.json` 文件。

## 6. 风险与回滚方式
- **风险**：无。前端所有页面均通过 `nexora-*` 的 UID 引用大盘。
- **回滚方式**：`git revert HEAD`。
