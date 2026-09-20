# 过滤 Linux 与 Windows 服务器仪表盘下拉设备与站点实施计划

## 1. 任务背景与现状
- **问题现象**：在 Grafana `07 Linux 服务器监控 (Linux Server Metrics)` 仪表盘中，顶部“服务器”下拉框不仅显示了 Linux 主机（如 `192.168.18.139:9100`、`192.168.204.128:9100`），还混入了网络设备（如 `10.254.0.1`、`192.168.56.11`）。当默认选中网络设备时，由于网络设备不产生 Node Exporter 指标，导致 Linux 监控面板全部显示为 0。
- **根因分析**：在 `monitoring/grafana/generate_dashboards.py` 中，站点和设备变量查询使用了正则匹配 `{__name__=~"node_uname_info|node_load1|up"}`。由于没有对抓取作业（`job`）进行限制，导致所有包含 `up` 指标的网络设备（`up{job="snmp"}`）和 Windows 主机（`up{job="windows_servers"}`）全部被匹配，混入下拉菜单。
- **任务目标**：
  1. Linux 服务器监控仪表盘的“站点”和“服务器”变量仅保留 Linux 服务器（通过 `job=~"linux_servers|.*node.*"` 及 `node_.*` 专有指标过滤），彻底排除网络设备及 Windows 主机。
  2. Windows 服务器监控仪表盘的“站点”和“服务器”变量仅保留 Windows 服务器（通过 `job=~"windows_servers|.*windows.*"` 及 `windows_.*` 专有指标过滤），彻底排除网络设备及 Linux 主机。
  3. 网络设备仪表盘的变量查询同样进行限定，避免服务器指标混入网络设备列表。
  4. 升级仪表盘版本号 `DASHBOARD_VERSION` 为 21，重新生成全部 JSON 仪表盘，确保 Grafana 启动时自动重新加载生效。

## 2. 拟修改范围与文件
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/*.json`（由脚本重新生成）

## 3. 实施步骤
1. 修改 `generate_dashboards.py`：
   - 递增版本号 `DASHBOARD_VERSION = 21`。
   - 更新 `build_linux_dashboard` 变量查询为 `{__name__=~"node_.*|up",job=~"linux_servers|.*node.*"}`。
   - 更新 `build_windows_dashboard` 变量查询为 `{__name__=~"windows_.*|up",job=~"windows_servers|.*windows.*"}`。
   - 更新 `make_network_variables` 去除裸 `up` 或限定 `job="snmp"`。
2. 运行脚本重新生成 8 个仪表盘文件。
3. 运行本地自动化测试验证。
4. 编写修复记录与走查记录，提交并推送到远端 `main` 分支。

## 4. 验证计划
- 检查生成的 `nexora-linux-metrics.json` 和 `nexora-windows-metrics.json` 中的 `templating.list` 查询语句。
- 运行 `pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py` 确保测试全部通过。
