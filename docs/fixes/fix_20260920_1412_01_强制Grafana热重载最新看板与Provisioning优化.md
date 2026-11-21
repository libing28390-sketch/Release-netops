# 修复记录 - 强制 Grafana 热重载最新看板与 Provisioning 优化

## 1. 问题现象
宿主机上执行 `git pull` 并重启后，Grafana 界面上点击【站点】依然弹出带有 `{job="linux_servers"...} or ...` 的报错弹窗，且 Linux 指标图表依然呈现旧版本的 `1500000000%`。

## 2. 根因分析
Grafana 的 Provisioning 机制在首次加载磁盘上的 JSON 后，会将大盘存入内部 SQLite 数据库 `/var/lib/grafana/grafana.db`。后续用户访问页面时，Grafana 直接从数据库返回，而不是每次读取磁盘文件。
当 `nexora.yml` 中 `allowUiUpdates: false`（默认值）且磁盘文件的 `version` 小于或等于数据库中已有的大盘版本时，Grafana 会输出 `Not saving new dashboard due to restricted database access` 并直接跳过对数据库的更新，导致前端界面永远停留在初次加载的老版本。

## 3. 解决方案
1. 在 `monitoring/grafana/provisioning/dashboards/nexora.yml` 中设置 `allowUiUpdates: true` 与 `disableDeletion: false`。
2. 在 `monitoring/grafana/generate_dashboards.py` 中将全局版本号提升至 `DASHBOARD_VERSION = 20`，重新生成所有 8 个大盘 JSON。
3. 宿主机重启时可通过清理 `grafana.db` 或依赖 provisioning 自动热重载。

## 4. 实际修改文件
- `monitoring/grafana/provisioning/dashboards/nexora.yml`
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/*.json`
- `docs/plans/plan_20260920_1412_01_强制Grafana热重载最新看板与Provisioning优化.md`
- `docs/walkthrough/walkthrough_20260920_1412_01_强制Grafana热重载最新看板与Provisioning优化.md`

## 5. 验证命令与结果
- 检查新生成的 JSON，确认全部更新为版本 20。

## 6. 风险与回滚方式
- **风险**：无。
- **回滚方式**：`git revert HEAD`。
