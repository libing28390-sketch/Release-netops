# 修复记录：过滤 Linux 与 Windows 服务器仪表盘下拉设备与站点

## 1. 问题现象
- 在 Grafana `07 Linux 服务器监控 (Linux Server Metrics)` 仪表盘中，顶部“服务器”下拉框混入了网络设备（如 `10.254.0.1`、`192.168.56.11`）。
- 默认选中网络设备时，由于网络设备不产生系统 Node 指标，各监控面板数据均展示为 0。

## 2. 根因分析
- 仪表盘变量查询使用了 `{__name__=~"node_uname_info|node_load1|up"}`，由于 `|up` 没有限制具体的抓取作业（`job`），所有含有 `up` 指标的网络设备（`job="snmp"`）和 Windows 主机都被抓取出来并展示在下拉菜单中。

## 3. 解决方案
- 在 `monitoring/grafana/generate_dashboards.py` 中更新模板变量定义：
  - Linux 服务器监控：通过 `{__name__=~"node_.*|up",job=~"linux_servers|.*node.*"}` 进行精确过滤，彻底排除网络设备与 Windows 主机。
  - Windows 服务器监控：通过 `{__name__=~"windows_.*|up",job=~"windows_servers|.*windows.*"}` 进行精确过滤，彻底排除网络设备与 Linux 主机。
  - 网络设备变量：限定为 `{job="snmp"}`。
- 将版本号 `DASHBOARD_VERSION` 升级至 `21`，强制 Grafana 自动加载最新的预置配置。
- 重新生成全部 8 个仪表盘 JSON 文件。

## 4. 实际修改文件
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/nexora-*.json` (8个文件)

## 5. 验证命令与结果
- `& "d:\nexora\nexora-private\.venv\Scripts\python.exe" -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`
  - 结果：`5 passed in 42.99s`。

## 6. 风险与回滚方式
- 风险：极低，仅影响 Grafana 仪表盘模板变量查询过滤。
- 回滚：`git revert HEAD`。
