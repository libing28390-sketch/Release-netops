# 实施计划 - 清理 Grafana 重复大盘文件消除 Provisioning 告警

## 1. 任务目标
消除 Grafana provisioning 日志中的警告：
`Not saving new dashboard due to restricted database access provisioner="Nexora dashboards" file=/var/lib/grafana/dashboards/network-wireless.json folderId=1`，
规范大盘文件命名，并解答用户关于 Linux 大盘 public-dashboards 404 与数据展示的疑问。

## 2. 现状与根因分析
1. **重复大盘文件告警**：
   `monitoring/grafana/generate_dashboards.py` 之前同时生成了 `nexora-*.json` 与 `*.json` 两份完全一样、UID 完全相同的大盘文件。Grafana 在初始化加载时，发现相同 UID 在只读 provisioned 模式下无法二次写入，因此打出告警。
2. **public-dashboards 404**：
   Grafana 官方前端在打开任何看板时都会请求 `/api/dashboards/uid/:uid/public-dashboards`，用于检查该看板是否开启了对外公开免登链接。若未开启则返回 404，属于 Grafana 原生机制，并非错误。
3. **Linux 大盘无数据**：
   当前 CMDB 中只录入了网络设备，未录入类型为 `server`（服务器）的 Linux 资产，且未部署 Node Exporter（9100 端口）。

## 3. 拟修改文件
- `monitoring/grafana/generate_dashboards.py`：仅生成 `nexora-*.json`，移除重复生成的 `*.json`。
- `monitoring/grafana/dashboards/`：删除 8 个无前缀的重复 json 文件。

## 4. 实施步骤
1. 删除 `monitoring/grafana/dashboards/` 下的 8 个多余文件：
   `network-overview.json`, `network-device.json`, `network-wireless.json`, `network-interface.json`, `monitoring-health.json`, `network-outbound.json`, `linux-metrics.json`, `windows-metrics.json`。
2. 修改 `generate_dashboards.py`，仅生成 `nexora-*.json` 文件。
3. 运行 `generate_dashboards.py` 验证生成的 json 文件一致性。
4. 创建修复记录并向用户说明。

## 5. 验证计划
- 运行 `python monitoring/grafana/generate_dashboards.py`。
- 确认目录只保留 8 个唯一的 `nexora-*.json` 文件。
