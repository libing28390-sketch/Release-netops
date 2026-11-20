# 跳过未配 SNMP 凭证设备以解除监控编译阻塞走查记录

## 1. 验证摘要
- 排查了在宿主机上调用 `sync_all_monitoring_collectors()` 报错 `AUTH_NOT_CONFIGURED: asset=asset-5c788264d2fc` 的根本原因：
  - CMDB 设备表中存在尚未配置 SNMP 凭据的设备（或服务器被传入 SNMP 采集计划匹配列表）；
  - 底层 `build_assignments` 对未配置 SNMP 的设备直接抛出异常中断了整个事务，导致后续生成 `linux_targets.yml` 和 `publish_collector` 全部被跳过。
- 修复方案：在 `backend/api/monitoring_v1.py` 的 `_load_compile_inputs` 中：
  - 自动跳过 `role='server'` 的服务器设备（服务器专由 `server_sql` 处理并生成 `linux_targets.yml`）；
  - 对未配置 SNMP 凭证且无法解析出 Community 的网络设备，跳过其进入 SNMP 采集编译并打印 Warning 日志，不再阻断整体编译流程与服务器目标发布。
- 本地回归测试验证通过（`22 passed in 42.85s`）。

## 2. 实际修改文件
- [monitoring_v1.py](file:///d:/nexora/nexora-private/backend/api/monitoring_v1.py)

## 3. 验证命令与结果
```bash
& "d:\nexora\nexora-private\.venv\Scripts\python.exe" -m pytest backend/tests/monitoring/test_monitoring_v1_compiler.py backend/tests/monitoring/test_domestic_and_wireless_monitoring.py
# 结果：22 passed in 42.85s
```
