# 采集日志分析与日志级别调整

## 日志分析结论

本次日志覆盖约 12 分钟，真实采集任务执行了两轮。每轮都完成了：

- ARP：6 台设备，采集 16 条记录，耗时约 4.2–4.8 秒；
- 终端/IP/Prefix：IPAM 与设备侧共同步 22 条 IP，Prefix 更新 22 条，失败数为 0；
- 终端定位：成功同步 17 条 endpoint；
- `poll_endpoints_job`：仅执行缓存投影，没有重复打开设备会话；
- BGP/OSPF：当前无符合采集计划的三层设备，因此未执行协议采集。

需要继续处理的问题：

1. Route Collector 两轮都出现 `tuple index out of range`，当前路由写入不是完全成功状态。
2. 两轮都没有采集到交换机 MAC，系统进入 fallback；如果接入交换机应提供 MAC 数据，需要单独检查 MAC 能力开关、命令输出和解析结果。
3. Prefix 投影本身成功，Loopback/IP 数据链路没有在本次日志中报错。

## 日志级别调整

- 根日志默认保持 `INFO`，保证启动、巡检和采集汇总可见。
- 普通成功 HTTP 请求改为 `DEBUG`。
- 4xx 和慢请求（默认大于等于 500ms）保留 `WARNING`。
- 5xx 保留 `ERROR`。
- 关闭 Uvicorn access log，避免与应用请求中间件重复打印一份访问记录。
- Playbook 列表轮询的“Found N executions”改为 `DEBUG`。
- 支持通过 `LOG_LEVEL` 和 `LOG_SLOW_REQUEST_MS` 配置覆盖默认值。

## 验证建议

修改后重启服务，观察以下内容：

- 正常 200 请求不再逐条出现在 INFO 日志；
- 404 `/api/ipam/reconciliation/runs` 仍会以 WARNING 记录，方便追踪接口问题；
- Route Collector 的 `tuple index out of range` 仍会以 ERROR 记录，不会被日志降级掩盖；
- ARP、Prefix、IP Inventory 等任务的开始、完成、数量和失败统计仍保持 INFO。
