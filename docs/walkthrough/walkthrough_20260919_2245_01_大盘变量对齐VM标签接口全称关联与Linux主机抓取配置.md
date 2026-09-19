# Walkthrough - 大盘变量对齐VM标签、Top接口全称关联注入与Linux主机抓取配置

## 完成摘要
针对用户在部署环境 `https://192.168.204.128/grafana` 反馈的接口全称缺失（显示为 `3%` 等索引）、站点和设备下拉框只有 `All`、以及 Linux 服务器监控无数据问题，深入探查 VictoriaMetrics 真实存储标签与时序结构，定位全部根因并完成修复：
1. **彻底解决站点与设备下拉框只有 All 的问题**：通过 API 实机探查发现 VictoriaMetrics 中时序数据仅存在 `site_id`（如 `site-4eb4ad17a9f3`）和 `sysName`（14 台设备名），根本不存在 `site_name` 和 `hostname`。将所有网络大盘（01-06）模板变量重构为基于 `site_id` 与 `sysName` 的多级联动查询，实机测试 14 台设备及 2 个站点完整枚举。
2. **彻底解决 01 概览「监控站点数」No data 与「在线数」显示异常**：PromQL 纠正为 `count(count by (site_id) (ifOperStatus{site_id!=""}))`，真实返回当前 2 个监控站点；纳管设备数和在线设备数均能正确返回。
3. **彻底解决 Top 20 接口展示为 `3%` 且无全称的问题**：
   - 流量指标自身仅有 `ifIndex`，通过加入 `* on(instance, ifIndex) group_left(ifName) (ifName * 0 + 1) * on(instance) group_left(sysName) (last_over_time(sysName{sysName=~"$device"}[1d]) * 0 + 1)`，成功将 `ifName`（如 `Et0/2`、`GigabitEthernet1/0/9`）与设备名注入查询结果；
   - 在 organize 转换中显式隐藏 `ifIndex` 并映射 `ifName -> 接口全称`、`sysName -> 设备名称`、`instance -> 管理 IP`；
   - 修复表格 fieldConfig，全局 unit 设为 `none`，仅在 overrides 中为利用率数值列设置 `unit: "percent"`，彻底消除了数字 3 被错误渲染为 `3%` 的格式化缺陷。
4. **Linux 服务器监控接入与抓取配置支持**：
   - 在 `backend/services/monitoring_compiler.py` 的 `render_vmagent_config` 中正式加入 `linux_servers`（9100 端口）和 `windows_servers`（9182 端口）的采集配置；
   - 07 Linux 服务器大盘变量重构为按 `instance`（主机 IP/端口）检索，完美适配 node_exporter 真实指标。
5. **双命名大盘 JSON 编译同步**：
   - 同时生成 `nexora-*.json` 与对应通用 `*.json`，确保无论 Docker 挂载何种命名均能 100% 命中最新配置，Grafana 容器每 30 秒自动热重载生效。

## 实际修改文件
- `monitoring/grafana/generate_dashboards.py`: 修复所有大盘的变量定义、设备/接口 Join 语法、表格字段转换与命名。
- `monitoring/grafana/dashboards/*.json`: 重新编译生成全部 8 组（共 16 个）最新大盘 JSON 文件。
- `backend/services/monitoring_compiler.py`: 在 vmagent 配置生成器中增加 Linux 和 Windows 服务器采集 Job。
- `docs/plans/plan_20260919_2245_01_大盘变量对齐VM标签接口全称关联与Linux主机抓取配置.md`: 实施计划归档。
- `docs/fixes/fix_20260919_2245_01_大盘变量对齐VM标签接口全称关联与Linux主机抓取配置.md`: 提交修复记录。
- `docs/walkthrough/walkthrough_20260919_2245_01_大盘变量对齐VM标签接口全称关联与Linux主机抓取配置.md`: 本走查文档。

## 验证与测试结果
1. **VictoriaMetrics 变量查询实机验证**：
   - `label/site_id/values`: 返回 2 个站点 `['site-4eb4ad17a9f3', 'site-cb2af5818ecd']`；
   - `label/sysName/values`: 返回 14 台设备 `['F1090-10', 'F1090-9', 'R1.eve.lab', 'R2.lab.local', 'R3.lab.local', 'R4.eve.lab', 'S6850-2', 'S6850-3', 'S6850-4', 'S6850-5', 'S6850-6', 'S6850_1', 'SW5.eve.lab', 'SW6.eve.lab']`；
   - 级联筛选匹配验证：选 H3C 返回 8 台设备，选 Cisco 返回 6 台设备。
2. **PromQL 接口全称与设备 Join 语法验证**：
   - Top 利用率与丢包率查询成功返回样本：`{'ifName': 'Et0/2', 'sysName': 'R2.lab.local', 'instance': '192.168.96.102', ...}`，耗时 6ms；
   - 监控站点数查询实机返回 `2`；全网在线设备实机返回 `14`；全网接口总流量实机返回 `226.5 kb/s`。
3. **大盘 JSON 编译与语法检查**：
   - `python monitoring/grafana/generate_dashboards.py` 成功生成全部大盘；
   - `python -m py_compile backend/services/monitoring_compiler.py` 语法校验通过。
