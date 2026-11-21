# 验证报告 - 清理 Grafana 重复大盘文件消除 Provisioning 告警

## 1. 完成摘要
清理了 `monitoring/grafana/dashboards/` 目录下重复的 8 个同 UID 仪表盘文件，修复了 `generate_dashboards.py` 的重复生成逻辑，消除了 Grafana 启动与重新加载时的 `Not saving new dashboard due to restricted database access` 告警。同时对 Linux 大盘的 public-dashboards 探测日志及指标展示原理进行了说明。

## 2. 实际修改文件
- [monitoring/grafana/generate_dashboards.py](file:///d:/nexora/nexora-private/monitoring/grafana/generate_dashboards.py)：精简 `main()`，仅生成带 `nexora-` 前缀的规范大盘文件。
- [monitoring/grafana/dashboards/](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/)：删除 8 个多余的无前缀重名文件，目录只保留 8 个唯一的 `nexora-*.json`。

## 3. 关键验证与说明
- **日志 1（重复大盘警告）**：
  删除多余同 UID 文件后，Grafana provisioning 不再重复保存冲突文件，告警彻底清除。
- **日志 2（`/api/dashboards/uid/:uid/public-dashboards 404`）**：
  属于 Grafana 前端进入任意看盘时的原生状态探测请求，用以判断该看板是否已配置公共免登链接（Public Dashboard），返回 404 是正常行为。
- **Linux 大盘数据展示**：
  Linux 大盘依靠 Node Exporter（9100端口）采集数据，当前 CMDB 中只录入了网络设备，待录入服务器资产并安装 node_exporter 后将全自动呈现数据。
