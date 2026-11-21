# 验证报告 - 强制 Grafana 热重载最新看板与 Provisioning 优化

## 1. 完成摘要
排查并定位了宿主机上 Grafana 未能呈现新版修复大盘的根本原因：
Grafana 的 Provisioning 机制在初次导入后，将看板持久化保存在内部 SQLite 数据库中。由于旧配置中 `allowUiUpdates` 为 false 且大盘版本未发生大版本跃迁，Grafana 会以 `Not saving new dashboard due to restricted database access` 为由拒绝从磁盘挂载目录重新读取覆盖。
本次变更将全局看板版本号强制提升至 `20`，并开启 `allowUiUpdates: true`，彻底打通热重载通路。

## 2. 实际修改文件
- [monitoring/grafana/provisioning/dashboards/nexora.yml](file:///d:/nexora/nexora-private/monitoring/grafana/provisioning/dashboards/nexora.yml)：开启 `allowUiUpdates: true`，`disableDeletion: false`，更新轮询间隔调整为 10 秒。
- [monitoring/grafana/generate_dashboards.py](file:///d:/nexora/nexora-private/monitoring/grafana/generate_dashboards.py)：定义全局 `DASHBOARD_VERSION = 20`，将所有 8 个大盘版本号统一步进至 20。
- `monitoring/grafana/dashboards/*.json`：全量重新生成版本号为 20 的最新大盘。

## 3. 关键验证与说明
- 验证所有 JSON 文件中 `version: 20` 生效；
- 验证 `nexora-linux-metrics.json` 中绝对无 `{job="linux_servers"...} or ...` 非法语法；
- 提供清理 Grafana 本地数据库缓存（`grafana.db`）的一键指令，确保宿主机 100% 立即加载全新大盘。
