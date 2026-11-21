# 修复网络大盘变量Job过滤与监控编译SQL转义走查记录

## 1. 验证摘要
- **排查定位**：
  1. 用户提供的网络总览截图中，纳管设备数为 14 台，但设备下拉框只有 2 台设备，且采集接口总数显示 `No data`。根本原因在于 `monitoring/grafana/generate_dashboards.py` 的变量查询中硬编码了 `job="snmp"`，而 vmagent 实际采集网络设备使用的 Job 名称为 `network_snmp`，导致真实设备的指标全部被过滤。
  2. Linux 主机监控在 20:30 后归零的根本原因在于：后台启动自动同步在编译采集器时，`_load_compile_inputs` 中的 `server_sql`（含 `LIKE '%server%'`）因 PostgreSQL 适配层 `_adapt_pg_sql` 把 `%server%` 误认为 `%s` 占位符而触发 `TypeError: not enough arguments for format string` 异常，导致 `servers = []` 并生成了空的 `linux_targets.yml`，致使 vmagent 停止抓取 `192.168.204.128:9100`。
- **完成修复**：
  1. 重构了 `backend/database/core.py` 中的 `_adapt_pg_sql`，严格区分真正的 `%s` 占位符与含有字母的普通单词（如 `%server`、`%status`、`%switch`）。
  2. 将 `backend/api/monitoring_v1.py` 中的 `server_sql` 改为参数化传参，并增加了异常 warning 日志。
  3. 为 `backend/services/monitoring_compiler.py` 的服务器采集生成增加了默认站点兜底。
  4. 将 `monitoring/grafana/generate_dashboards.py` 中的 `job="snmp"` 纠正为 `job=~"network_snmp|.*snmp.*"`，将大盘版本号提升至 `22` 并重新编译生成全部 8 个仪表盘 JSON 文件。
  5. 补充了 2 个自动化回归测试用例，全量 24 个监控测试全部 100% 通过。

## 2. 实际修改文件
- `backend/database/core.py`
- `backend/api/monitoring_v1.py`
- `backend/services/monitoring_compiler.py`
- `backend/tests/monitoring/test_monitoring_v1_compiler.py`
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/nexora-*.json` (全部 8 个大盘文件)
- `docs/plans/plan_20260920_2045_01_修复网络大盘变量Job过滤与监控编译SQL转义.md`
- `docs/fixes/fix_20260920_2045_01_修复网络大盘变量Job过滤与监控编译SQL转义.md`
- `docs/walkthrough/walkthrough_20260920_2045_01_修复网络大盘变量Job过滤与监控编译SQL转义.md`

## 3. 验证命令与结果
```bash
& "D:\netops\netsops-main\.venv\Scripts\python.exe" -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py backend/tests/monitoring/test_monitoring_v1_compiler.py
# 结果：24 passed in 47.39s
```
