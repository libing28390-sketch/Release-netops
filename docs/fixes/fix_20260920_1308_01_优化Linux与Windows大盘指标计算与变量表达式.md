# 修复记录 - 优化 Linux 与 Windows 大盘指标计算与变量表达式

## 1. 问题现象
1. Grafana 打开 Linux 服务器监控大盘时弹出黄色报错弹窗：
   `Validation failed: cannot parse matches[]={job="linux_servers"} or {__name__=~"node_.*"}: expecting metricSelector; got " {job=\"linux_servers\"} or {__name__=~\"node_.*\"}"`
   且【站点】和【服务器】下拉框无法读取出列表数据。
2. 仪表盘“物理内存与 Swap 空间消耗走势”显示为 `1500000000%`（15亿%）。
3. 仪表盘“文件句柄利用率”显示为科学计数法 `2.64e-14%`。
4. 仪表盘“CPU 利用率趋势”在多核主机上为每个 CPU 核心重复输出同名图例，且与系统负载（Load）混用同一个百分比 Y 轴。

## 2. 根因分析
1. Prometheus/VictoriaMetrics 的 `/api/v1/series?match[]={...}` 接口只接受单项指标选择器，不支持 PromQL `or` 逻辑运算符。
2. 内存图表把单位设为了 `percent`，却混杂了以字节（Bytes）为单位的已用内存数值，导致 15 亿字节被渲染为 15 亿%。
3. 现代 64 位 Linux 内核将全局文件句柄上限 `node_filefd_maximum` 设为了 `9.22e18`，做除法后变成 `2.64e-14%`，失去监控意义。
4. CPU 空闲率 `node_cpu_seconds_total` 没有做 `avg by (instance)` 核心聚合。
5. 负载（Load）为无量纲的排队进程数，与 0-100% 的 CPU 使用率塞在同一个百分比坐标轴不合理。
6. `server_sql` 仅查询了 `physical_assets` 表，对于录入在 `devices` 表的服务器未能自动提取其 `site_name`。

## 3. 解决方案
1. 变量查询改为单项指标选择器：`label_values({__name__=~"node_uname_info|node_load1|up"}, site_name)` 与 `label_values({__name__=~"node_uname_info|node_load1|up",site_name=~"$site"}, instance)`。
2. 内存图表统一以 `bytes` 容量呈现物理内存已用、可用、缓存缓冲、Swap已用和总量参考线。
3. 文件句柄卡片改为展示“已打开文件句柄数”（`sum(node_filefd_allocated)`）。
4. CPU 利用率统一使用 `avg by (instance)` 聚合为整机使用率，并展示用户态、系统态和 I/O 等待。
5. 系统负载作为独立图表展示（Load 1/5/15），并画出逻辑 CPU 核数阈值对比线。
6. `server_sql` 打通 `physical_assets` 和 `devices`，保证自动为所有受纳管服务器绑定站点标签。

## 4. 实际修改文件
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/nexora-linux-metrics.json`
- `monitoring/grafana/dashboards/nexora-windows-metrics.json`
- `backend/api/monitoring_v1.py`
- `docs/plans/plan_20260920_1308_01_优化Linux与Windows大盘指标计算与变量表达式.md`
- `docs/walkthrough/walkthrough_20260920_1308_01_优化Linux与Windows大盘指标计算与变量表达式.md`

## 5. 验证命令与结果
- 运行测试：`.venv/Scripts/python -m pytest backend/tests/monitoring/test_monitoring_v1_compiler.py -v`
- 结果：17 passed in 42.60s。

## 6. 风险与回滚方式
- **风险**：低。
- **回滚方式**：`git revert HEAD`。
