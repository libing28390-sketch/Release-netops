# 实施计划 - 优化 Linux 与 Windows 大盘指标计算与变量表达式

## 1. 任务目标
根据真实 Linux 运行环境中的反馈与审查结果，解决 Grafana 大盘中的指标计算异常与变量语法报错：
1. 消除 VictoriaMetrics 变量查询校验失败的黄色弹窗（`Validation failed: cannot parse matches[]... expecting metricSelector`）；
2. 修复“物理内存与 Swap 空间消耗走势”中混杂 Bytes 与 Percent 导致 Y 轴飙升至 `1500000000%` 的严重错误；
3. 修复文件句柄除以内核极限值（`9.22e18`）导致显示为 `2.64e-14%` 的无意义计算，改为展示已分配句柄数；
4. 修复 CPU 利用率未按单机核心聚合（`avg by (instance)`）导致多核重复图例问题；
5. 将系统平均负载（Load 1/5/15）从百分比图表中剥离，作为独立无量纲指标并对比 CPU 逻辑核心数；
6. 同步修正 Windows 大盘中的类似变量与指标计算问题。

## 2. 现状与根因分析
1. **变量报错弹窗**：
   `label_values` 的底层调用是 `/api/v1/series?match[]={...}`，不支持 PromQL 的 `or` 逻辑运算符。代码中的 `{job="linux_servers"} or {__name__=~"node_.*"}` 导致解析语法错误。
2. **15亿% 内存走势**：
   折线图全局单位被设置为 `percent`，但 targets 中包含以字节为单位的 `node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes`（约 15 亿字节），Grafana 将其直接渲染为 15 亿%。
3. **文件句柄 2.64e-14%**：
   现代 64 位 Linux 内核将 `filefd_maximum` 设为 `LONG_MAX`（`9.22e18`），除法计算失去实际监控意义。
4. **CPU 与 Load 混用**：
   Load 是无量纲的排队进程数，与 0-100% 的 CPU 使用率混在一个图表且单位为 `%`，导致刻度混淆。

## 3. 拟修改文件
- `monitoring/grafana/generate_dashboards.py`：重构 `build_linux_dashboard()` 与 `build_windows_dashboard()` 的指标表达式与变量定义。
- `monitoring/grafana/dashboards/nexora-linux-metrics.json`：重新生成优化后的 Linux 大盘。
- `monitoring/grafana/dashboards/nexora-windows-metrics.json`：重新生成优化后的 Windows 大盘。
- `backend/tests/monitoring/test_monitoring_v1_compiler.py` 或新增大盘 JSON 校验测试。

## 4. 实施步骤
1. 修改 `generate_dashboards.py`：
   - 变量查询改为单项合法 metricSelector，例如 `label_values({__name__=~"node_uname_info|node_load1|up"}, site_name)`；
   - 内存图表重构为以 `bytes` 为单位的物理内存与 Swap 分布（已用、可用、缓存缓冲、Swap已用、总量参考线）；
   - CPU 使用率按 instance 聚合多核，并独立展示 CPU 用户态、系统态、I/O等待；
   - 独立展示系统负载图表（Load1/5/15），并画出逻辑 CPU 核数对比线；
   - 文件句柄面板改为展示“已分配文件句柄数”；
   - 同样检查并修复 Windows 大盘。
2. 运行 `generate_dashboards.py` 更新大盘 JSON 文件。
3. 运行自动化测试验证大盘合法性。
4. 创建 Walkthrough 与 Fix 记录，并执行 `git push`（用户已明确授权“完成后自行push代码”）。

## 5. 验证计划
- 运行 Python 脚本生成 JSON；
- 编写测试断言 JSON 中不含未聚合多核 CPU、不含非法的 `label_values` or 表达式、内存图表单位正确为 `bytes`；
- 执行 pytest 门禁确保全绿。
