# 修复记录 - 修复 SNMP Exporter 热重载调用异常

## 1. 问题现象
后台每 5 分钟或资产发生变动时，采集器自动同步引擎会触发采集器配置重新编译与发布（`collector_sync_service.py` -> `compile_and_publish`）。但在触发 SNMP Exporter 热重载时，日志抛出以下告警：
```text
[WARNING] api.monitoring_v1: SNMP exporter configuration reload is pending
Traceback (most recent call last):
  File "/app/backend/api/monitoring_v1.py", line 199, in _reload_snmp_exporter_config
    with build_opener(ProxyHandler({}))(request, timeout=3) as response:
TypeError: 'OpenerDirector' object is not callable
```

## 2. 根因分析
在 Python 标准库 `urllib.request` 中，`build_opener(...)` 返回的是一个 `OpenerDirector` 类的对象实例，它不是可调用对象（Callable）。
执行 HTTP 请求应调用它的 `.open(request, timeout=...)` 方法。代码中漏掉了 `.open`，导致调用实例引发 `TypeError`。

## 3. 解决方案
将 `backend/api/monitoring_v1.py` 中的：
```python
with build_opener(ProxyHandler({}))(request, timeout=3) as response:
```
修正为：
```python
with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
```
并在 `backend/tests/monitoring/test_monitoring_v1_compiler.py` 中补充单元测试覆盖该热重载逻辑。

## 4. 实际修改文件
- `backend/api/monitoring_v1.py`
- `backend/tests/monitoring/test_monitoring_v1_compiler.py`
- `docs/plans/plan_20260920_1246_01_修复SNMP_exporter热重载调用异常.md`
- `docs/walkthrough/walkthrough_20260920_1246_01_修复SNMP_exporter热重载调用异常.md`

## 5. 验证命令与结果
- 执行：`.venv/Scripts/python -m pytest backend/tests/monitoring/test_monitoring_v1_compiler.py -v`
- 结果：17 passed in 45.01s，单测全部通过。

## 6. 风险与回滚方式
- **风险**：极低。仅修复了调用方法的语法错误，不改变入参和请求目标。
- **回滚方式**：`git revert HEAD`。
