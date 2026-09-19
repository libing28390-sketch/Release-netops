# 走查与验证报告：Grafana 全部大盘变量语法修复与时序标签全链路补全

## 完成摘要

已彻底排查并修复 Grafana 中站点与设备下拉列表仅有 `Selected (1)` 和 `All`、折线图图例显示断头破折号 `-(10.254.0.1)-` 以及表格缺少设备名称与端口编号的问题。全部 8 个 Dashboards 已采用规范的显式 metric 变量语法并重新编译，同时全量补齐纳管设备 targets 基线标签。

## 实际修改文件

- `monitoring/grafana/generate_dashboards.py`：升级变量定义语法与图例模板；
- `monitoring/grafana/dashboards/nexora-network-overview.json`
- `monitoring/grafana/dashboards/network-device.json`
- `monitoring/grafana/dashboards/network-wireless.json`
- `monitoring/grafana/dashboards/network-interface.json`
- `monitoring/grafana/dashboards/monitoring-health.json`
- `monitoring/grafana/dashboards/network-outbound.json`
- `monitoring/grafana/dashboards/linux-metrics.json`
- `monitoring/grafana/dashboards/windows-metrics.json`
- `monitoring/vmagent/targets/snmp_targets.yml`：写入 14 台设备、28 个 targets 的全量业务标签；
- `docs/plans/plan_20260919_2053_01_Grafana全部大盘变量语法修复与时序标签全链路补全.md`
- `docs/fixes/fix_20260919_2053_01_Grafana全部大盘变量语法修复与时序标签全链路补全.md`
- `docs/walkthrough/walkthrough_20260919_2053_01_Grafana全部大盘变量语法修复与时序标签全链路补全.md`

## 关键实现说明

1. **显式 Metric 变量查询**：
   - 站点变量：`label_values(ifOperStatus or ifHCInOctets or sysUpTime or up, site_name)`
   - 厂商变量：`label_values(ifOperStatus{site_name=~"$site"} or sysUpTime{site_name=~"$site"} or up, vendor)`
   - 角色变量：`label_values(ifOperStatus{site_name=~"$site",vendor=~"$vendor"} or up, role)`
   - 设备变量：`label_values(ifOperStatus{site_name=~"$site",vendor=~"$vendor"} or ifHCInOctets{site_name=~"$site",vendor=~"$vendor"} or up, hostname)`
2. **图例格式平滑渲染**：
   - 接口流量图例统一优化为 `{{hostname}} {{instance}} {{ifName}}`；
   - 规避标签缺失时出现的孤立 `- () -` 破折号和空括号。
3. **采集端基线注入**：
   - `monitoring/vmagent/targets/snmp_targets.yml` 注入 `nexora_hostname`, `nexora_site_name`, `nexora_vendor`, `nexora_role`, `nexora_platform` 等全部必要标签。

## 验证结果

- `python monitoring/grafana/generate_dashboards.py` 成功生成全部 8 个 Dashboards JSON；
- 静态 JSON 语法与字段完整性校验 100% 通过；
- 后端监控测试全部通过。
