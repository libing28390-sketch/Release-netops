# 验证报告：大盘 Top 接口名称缺失修复、Grafana 变量语法合规化与主机监控接入

## 1. 完成摘要
- **Top 排序表格缺失接口名称与单设备折叠问题修复**：
  - `snmp.yml` 补全 `ifDescr` 指标采集与全部关联 lookups；
  - `generate_dashboards.py` 将 Top 聚合维度扩展为 `by (hostname, instance, ifName, ifDescr, ifIndex)`，并将端口编号、端口名称、端口索引映射至前端展示列，彻底解决接口缺失与多端口被错误折叠为单一设备行的问题。
- **Grafana 变量语法报错解决**：
  - 将所有大盘中的 `label_values(a or b or c, label)` 升级为标准 Prometheus 系列选择器 `{__name__=~"a|b|c"}`，消灭 `expecting metricSelector` 校验报错。
- **主机监控作业接入与 Agent 插件体系完善**：
  - 在 `monitoring/vmagent/scrape.yml` 中新增 `linux_nodes` (9100) 与 `windows_nodes` (9182) 抓取任务；
  - 初始化 `monitoring/vmagent/targets/linux_targets.yml` 与 `windows_targets.yml`；
  - 提供 Linux (`node_exporter`) 和 Windows (`windows_exporter`) 的极简一键安装与配置步骤。

## 2. 实际修改文件
- `monitoring/snmp-exporter/snmp.yml`
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/*.json` (全量 8 个大盘)
- `monitoring/vmagent/scrape.yml`
- `monitoring/vmagent/targets/linux_targets.yml`
- `monitoring/vmagent/targets/windows_targets.yml`
- `docs/plans/plan_20260919_2125_01_大盘Top接口名称缺失修复与Linux主机监控接入.md`
- `docs/fixes/fix_20260919_2125_01_大盘Top接口名称缺失修复与Linux主机监控接入.md`

## 3. 验证情况
1. **大盘生成验证**：
   - 执行 `.venv\Scripts\python.exe monitoring\grafana\generate_dashboards.py` 顺利生成 8 个 JSON。
2. **系列选择器与变量解析验证**：
   - 运行验证脚本检查 8 个大盘的所有变量查询表达式，全部符合 `{__name__=~"..."}` 规范。
3. **SNMP 接口映射验证**：
   - 检查 `snmp.yml` 中 `generic_ifmib_interface_std` 模块的 `ifDescr` 定义与各项 `lookups` 配置，语法与缩进完全正确。

## 4. 后续建议
- 主机纳管时，在 Linux 运行 `node_exporter`，在 Windows 运行 `windows_exporter`，并在 `vmagent` 中登记 targets 即可实现主机性能秒级采集。
