# 实施计划 - 强制 Grafana 热重载最新看板与 Provisioning 优化

## 1. 任务目标
解决宿主机上 Grafana 未将磁盘上已修复的最新仪表盘 JSON 文件加载到内置数据库中，导致在点击【站点】时仍使用旧缓存中的 `{job="linux_servers"...} or ...` 触发 `Validation failed` 报错的问题。

## 2. 现状与根因分析
- **现象**：
  用户在 Grafana 界面点击站点查询时，依然弹出：
  `Validation failed: cannot parse matches[]={job="linux_servers",site_name=~".*"} or {__name__=~"node_.*",site_name=~".*"}: expecting metricSelector`
- **根因**：
  1. 代码库的 JSON 文件已经在前次提交中去除了非法的 `or` 语句；
  2. 但 Grafana 在初次加载后，会将 Dashboard 存入内部 SQLite 数据库 `/var/lib/grafana/grafana.db` 中；
  3. `monitoring/grafana/provisioning/dashboards/nexora.yml` 缺少 `allowUiUpdates: true`，且 `nexora-linux-metrics.json` 的版本号 `"version": 3` 未发生递增；
  4. Grafana 判定数据库中的版本已是最新的（或处于保护状态 `restricted database access`），因此**直接跳过了磁盘上新 JSON 文件的更新保存**，导致前端实际执行的依旧是数据库里的旧版本。

## 3. 拟修改文件
- `monitoring/grafana/generate_dashboards.py`：定义统一版本常量 `DASHBOARD_VERSION = 20`，将所有仪表盘的 `version` 递增至 20。
- `monitoring/grafana/provisioning/dashboards/nexora.yml`：增加 `allowUiUpdates: true`，`disableDeletion: false`，缩短更新检查间隔。
- `monitoring/grafana/dashboards/` 下的所有 JSON 文件通过脚本重新生成。

## 4. 实施步骤
1. 修改 `nexora.yml` 启用 `allowUiUpdates: true`。
2. 修改 `generate_dashboards.py` 统一定义 `DASHBOARD_VERSION = 20`。
3. 运行 `generate_dashboards.py` 重新生成全部 8 个仪表盘。
4. 运行 pytest 确保单测通过。
5. 编写 Walkthrough 和 Fix 记录，并推送至 `origin/main`。
6. 指引用户在宿主机执行重载命令（包括重载或清理旧 db 缓存）。

## 5. 验证计划
- 检查新生成的 JSON 中 `version` 均为 20；
- 检查 `nexora-linux-metrics.json` 中绝对不包含 `or` 逻辑运算符；
- 运行 pytest 测试。
