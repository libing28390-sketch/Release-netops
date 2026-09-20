# 验证报告 - 修复 SNMP Exporter 热重载调用异常

## 1. 完成摘要
修复了后端在自动编译发布采集器配置后，向 `snmp-exporter` 发送 HTTP POST `/-/reload` 热重载信号时因 `OpenerDirector` 缺少 `.open()` 方法导致的 `TypeError: 'OpenerDirector' object is not callable` 警告。

## 2. 实际修改文件
- [backend/api/monitoring_v1.py](file:///d:/nexora/nexora-private/backend/api/monitoring_v1.py#L195-L204)：将 `build_opener(ProxyHandler({}))(request, timeout=3)` 修正为 `build_opener(ProxyHandler({})).open(request, timeout=3)`。
- [backend/tests/monitoring/test_monitoring_v1_compiler.py](file:///d:/nexora/nexora-private/backend/tests/monitoring/test_monitoring_v1_compiler.py#L341-L368)：增加 `test_reload_snmp_exporter_config_uses_opener_open` 单元测试，验证热重载请求的方法（POST）、URL 和超时参数。

## 3. 关键实现说明
- 在 `urllib.request` 中，`build_opener(...)` 返回的是 `OpenerDirector` 对象，必须通过 `.open(req, timeout=...)` 发送请求。
- 修复后，`_reload_snmp_exporter_config()` 能成功触发 `http://snmp-exporter:9116/-/reload`，使 SNMP Exporter 能够在无需重启容器的情况下秒级热加载新的 OID 模块与变体。

## 4. 验证命令与结果
- 运行测试：
  ```powershell
  .venv/Scripts/python -m pytest backend/tests/monitoring/test_monitoring_v1_compiler.py -v
  ```
- 测试结果：
  ```text
  17 passed in 45.01s (包含 test_reload_snmp_exporter_config_uses_opener_open PASSED)
  ```
