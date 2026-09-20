# 实施计划 - 修复 SNMP Exporter 热重载调用异常

## 1. 任务目标
修复后台自动同步采集器配置后触发 SNMP Exporter 热重载时的 Python 运行时异常：
`TypeError: 'OpenerDirector' object is not callable`，确保 `snmp-exporter` 配置能够正常通过 HTTP POST `/-/reload` 热重载生效。

## 2. 现状与根因分析
- **异常现象**：
  后台在每 5 分钟或资产变动时触发采集器目标与模块配置自动同步（`collector_sync_service.py` -> `compile_and_publish`），在调用 `_reload_snmp_exporter_config()` 时记录以下日志：
  ```text
  [WARNING] api.monitoring_v1: SNMP exporter configuration reload is pending
  Traceback (most recent call last):
    File "/app/backend/api/monitoring_v1.py", line 199, in _reload_snmp_exporter_config
      with build_opener(ProxyHandler({}))(request, timeout=3) as response:
  TypeError: 'OpenerDirector' object is not callable
  ```
- **根因**：
  `urllib.request.build_opener(...)` 返回的是一个 `OpenerDirector` 类的实例，而不是一个可调用函数。
  执行 HTTP 请求必须使用 `opener.open(request, timeout=...)`，而不能像函数一样 `opener(...)`。
  正确写法应为：
  `with build_opener(ProxyHandler({})).open(request, timeout=3) as response:`

## 3. 拟修改文件
- `backend/api/monitoring_v1.py`：修改 `_reload_snmp_exporter_config` 中的调用方式。
- `backend/tests/monitoring/test_monitoring_v1_compiler.py`：增加对 `_reload_snmp_exporter_config` 成功和失败场景的单元测试。

## 4. 实施步骤
1. 修改 `backend/api/monitoring_v1.py` 第 199 行，调用 `.open(request, timeout=3)`。
2. 在 `backend/tests/monitoring/test_monitoring_v1_compiler.py` 中补充单测覆盖该函数。
3. 运行本地 pytest 测试，确保门禁通过。
4. 整理 Walkthrough 并向用户说明。

## 5. 验证计划
- 运行 pytest 测试用例：
  `pytest backend/tests/monitoring/test_monitoring_v1_compiler.py`
- 确保测试全部通过且无警告。
