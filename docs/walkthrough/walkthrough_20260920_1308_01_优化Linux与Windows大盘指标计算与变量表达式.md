# 验证报告 - 优化 Linux 与 Windows 大盘指标计算与变量表达式

## 1. 完成摘要
全面审查并解决了 Linux 与 Windows 主机监控大盘中的指标计算异常与变量报错问题：
1. 修复了 VictoriaMetrics 变量查询校验失败的黄色弹窗（去除非法的 PromQL `or` 逻辑运算符，使用合法单项选择器）；
2. 修复了“物理内存与 Swap 空间消耗走势”因混用字节数与百分比导致的 `1500000000%` 异常，统一以 `bytes` 呈现已用、可用、缓存缓冲、Swap已用与总容量；
3. 修复了文件句柄利用率除以 `9.22e18` 内核极限值导致的 `2.64e-14%`，改为展示真实的系统已打开文件句柄数；
4. 修复了整机 CPU 利用率未按多核平均（`avg by (instance)`）导致的双核重复图例问题；
5. 将系统平均负载（Load1/5/15）从百分比图表中独立拆分，对齐 CPU 逻辑核心数参考线；
6. 在采集编译器 `server_sql` 中打通 `physical_assets` 与 `devices` 双表兼容，确保服务器纳管时无论录入在哪个入口都能正确绑定 `site_name`。

## 2. 实际修改文件
- [monitoring/grafana/generate_dashboards.py](file:///d:/nexora/nexora-private/monitoring/grafana/generate_dashboards.py)：重构 Linux 和 Windows 看板的指标表达式、单位与变量查询。
- [monitoring/grafana/dashboards/nexora-linux-metrics.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-linux-metrics.json)：重新生成 Linux 看板 JSON。
- [monitoring/grafana/dashboards/nexora-windows-metrics.json](file:///d:/nexora/nexora-private/monitoring/grafana/dashboards/nexora-windows-metrics.json)：重新生成 Windows 看板 JSON。
- [backend/api/monitoring_v1.py](file:///d:/nexora/nexora-private/backend/api/monitoring_v1.py#L1120-L1135)：在 `_load_compile_inputs` 中增强 `server_sql`，全面捕获 server 资产与设备，并注入正确的 `site_name`。

## 3. 关键验证与测试
- 运行测试：
  ```powershell
  .venv/Scripts/python -m pytest backend/tests/monitoring/test_monitoring_v1_compiler.py -v
  ```
- 结果：17 passed in 42.60s，全部通过。
