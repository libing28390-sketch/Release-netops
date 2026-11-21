# 过滤 Linux 与 Windows 服务器仪表盘下拉设备与站点走查记录

## 1. 验证摘要
- 已更新 `monitoring/grafana/generate_dashboards.py`，将仪表盘版本升级至 `21`。
- 重新生成全部 8 个 Grafana 仪表盘 JSON 文件，更新了变量查询表达式：
  - **Linux 服务器监控 (07)**：
    - 站点：`label_values({__name__=~"node_.*|up",job=~"linux_servers|.*node.*"}, site_name)`
    - 服务器：`label_values({__name__=~"node_.*|up",job=~"linux_servers|.*node.*",site_name=~"$site"}, instance)`
  - **Windows 服务器监控 (08)**：
    - 站点：`label_values({__name__=~"windows_.*|up",job=~"windows_servers|.*windows.*"}, site_name)`
    - 服务器：`label_values({__name__=~"windows_.*|up",job=~"windows_servers|.*windows.*",site_name=~"$site"}, instance)`
  - **网络设备仪表盘 (01~06)**：
    - 限定网络设备查询为 `job="snmp"`，避免服务器指标混入网络设备列表。
- 本地自动化测试 `backend/tests/monitoring/test_domestic_and_wireless_monitoring.py` 验证通过（`5 passed in 42.99s`）。

## 2. 实际修改文件
- [generate_dashboards.py](file:///d:/nexora/nexora-private/monitoring/grafana/generate_dashboards.py)
- [nexora-linux-metrics.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-linux-metrics.json)
- [nexora-windows-metrics.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-windows-metrics.json)
- [nexora-network-overview.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-network-overview.json)
- [nexora-network-device.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-network-device.json)
- [nexora-network-wireless.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-network-wireless.json)
- [nexora-network-interface.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-network-interface.json)
- [nexora-monitoring-health.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-monitoring-health.json)
- [nexora-network-outbound.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-network-outbound.json)

## 3. 验证命令与结果
```bash
& "d:\nexora\nexora-private\.venv\Scripts\python.exe" monitoring/grafana/generate_dashboards.py
# 结果：成功生成 8 个 JSON 仪表盘文件，版本号为 21

& "d:\nexora\nexora-private\.venv\Scripts\python.exe" -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py
# 结果：5 passed in 42.99s
```
