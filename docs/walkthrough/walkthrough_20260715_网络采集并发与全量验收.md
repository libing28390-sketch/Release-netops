# 网络采集并发与全量验收

## 目标

完成整改计划剩余的网络采集并发、连接生命周期、可观测性和回归验收工作，确保后台轮询、自动化任务、巡检、备份及多厂商命令执行不会无限制创建 SSH 会话。

## 已完成内容

1. 建立进程级网络访问预算：SSH/CLI、SNMP、ICMP/TCP 探测分开限流；SSH 同时具备全局并发和单设备并发限制。
2. 将拓扑、IP 定位、巡检、运行数据、调度器、自动化执行和驱动上下文统一接入 SSH 限制器。
3. 将 SNMP GET/WALK/BULK WALK 统一接入 SNMP 限制器。
4. 修正 B-Loop 采集节奏：接口和基础指标可高频采集，协议/路由等 CLI 采集按设备角色低频执行。
5. SSH 连接池增加空闲 TTL、最大连接数、定期清理、关闭异常连接和健康状态快照。
6. 健康接口新增 `network_access` 与 `ssh_pool` 状态，便于运行监控和容量诊断。
7. 修复 TextFSM 自定义表格中 `Port` 字段被错误改写成 `INTERFACE` 的问题；playbook 对 Huawei VRPv8 使用统一的 VRP 家族场景键，同时保留设备驱动的精确平台。

## 验证记录

- `python -m compileall -q backend`：通过。
- `pytest backend/tests/vendor_audit/test_connection_pool.py -q`：2 passed。
- `pytest backend/tests/test_custom_textfsm_flow.py backend/tests/test_playbook_platform_aliases.py backend/tests/vendor_audit/test_network_access_limiter.py -q`：8 passed。
- `pytest -q`：502 passed，25 个参数化子测试通过，1 条 Starlette/httpx 弃用警告。
- `git diff --check`：无内容错误；仅提示 Windows 工作区的换行符转换。

## 运行参数

可在 `.env` 或 `.env.local` 调整：

- `NETWORK_SSH_GLOBAL_CONCURRENCY`：进程级 SSH/CLI 总并发。
- `NETWORK_SSH_PER_DEVICE_CONCURRENCY`：单设备 SSH 并发，默认 1。
- `NETWORK_SNMP_GLOBAL_CONCURRENCY`：SNMP 总并发。
- `NETWORK_PROBE_GLOBAL_CONCURRENCY`：ICMP/TCP 探测总并发。
- `NETWORK_POOL_IDLE_SECONDS`：连接池空闲回收时间，默认 300 秒。
- `NETWORK_POOL_MAX_SIZE`：单进程连接池最大连接数，默认 100。

这些限制是单个后端进程的预算；多实例部署时应按实例数量和设备侧会话上限重新分配，并继续使用调度锁避免定时任务重复执行。
