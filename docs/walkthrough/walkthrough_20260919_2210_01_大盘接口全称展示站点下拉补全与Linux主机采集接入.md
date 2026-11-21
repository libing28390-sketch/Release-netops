# 验证报告：大盘接口全称展示、站点与设备下拉列表补全及 Linux 主机采集打通

## 1. 完成摘要
- **接口全称呈现与索引清除**：
  - 彻底在表格中排除 `ifIndex` 索引列；
  - 修复全局百分比格式化污染，解决数字 `3` 被渲染成 `3%` 的问题；
  - 建立 `ifDescr` 到“接口全称”的映射，PromQL 优先聚合 `ifDescr` 与 `ifName`。
- **站点与设备下拉列表恢复**：
  - 修复 Docker 启动同步机制（`scripts/sync-frontend-dist.sh`），保证 baseline 中的全量业务标签自动同步进运行时卷，使时序指标完整携带 `site_name` 和 `hostname`，Grafana 变量查询恢复正常。
- **Linux 主机监控即时接入**：
  - 在 `monitoring/vmagent/scrape.yml` 中新增 `linux_nodes` 作业，配置对宿主机 `192.168.204.128:9100` 的秒级抓取与标签注入。

## 2. 实际修改文件
- `scripts/sync-frontend-dist.sh`
- `monitoring/vmagent/scrape.yml`
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/*.json`
- `docs/plans/plan_20260919_2210_01_大盘接口全称展示站点下拉补全与Linux主机采集接入.md`
- `docs/fixes/fix_20260919_2210_01_大盘接口全称展示站点下拉补全与Linux主机采集接入.md`

## 3. 验证情况
- 8 个大盘 JSON 重新编译并顺利通过验证；
- 变量查询语法完全合规；
- 代码已通过本地质量门禁。
