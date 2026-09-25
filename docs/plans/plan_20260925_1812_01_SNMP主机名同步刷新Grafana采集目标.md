# SNMP 主机名同步刷新 Grafana 采集目标

## 目标

SNMP 将设备 sysName 同步到 Nexora 后，自动重新编译并发布监控采集目标，使 vmagent 的 `hostname` 标签和 Grafana 设备筛选器跟随资产名称更新。

## 现状与问题

SNMP 主机名同步会更新 `devices.hostname` 和关联资产名，但相关同步路径没有统一在数据库提交后触发采集目标同步。Grafana 设备下拉读取 VictoriaMetrics 中的 `hostname` 指标标签，因此页面刷新本身不会更新标签。

## 影响范围

- 单台和批量 SNMP 主机名同步 API。
- SNMP 发现、后台监控及设备运行数据采集触发的主机名投影。
- 监控目标自动编译/发布，以及 Grafana 设备名称标签。

## 拟修改文件

- `backend/services/hostname_sync_service.py`
- `backend/services/snmp_discovery_service.py`
- `backend/services/background_monitor_service.py`
- `backend/api/devices.py`
- `docs/walkthrough/walkthrough_20260925_1812_01_SNMP主机名同步刷新Grafana采集目标.md`

## 实施步骤

1. 增加可复用的“名称变化后调度”方法，使用规范化后的新旧 hostname 比较。
2. 所有调用 `sync_device_hostname_metadata` 的路径在事务提交后调度采集目标同步。
3. 单台接口仅在名称变化时调度；批量接口在整批完成后最多调度一次，保持响应结构不变。
4. 复核 Grafana label 查询、vmagent relabel 和所有主机名同步调用路径。

## 验证计划

- 审查全部主机名同步调用点，确认触发发生在提交之后，且名称未变时不触发。
- 审查单台与批量 API 响应结构和改动 diff。
- 运行 `.venv\Scripts\python.exe -m pytest backend/tests/snmp/test_hostname_sync.py::test_batch_sync_hostname_mocked -q`，确认批量统计在数据库同步服务返回新旧名称时符合原有接口契约。
- 若 CI mock 未覆盖同步服务新增的数据库读取，修正测试夹具来模拟明确的新旧 hostname；不改变生产统计逻辑。

## 风险与回滚

- 目标同步是异步且带防抖的；短时间内多次改名会合并为一次编译发布。
- 若目标发布失败，现有采集配置仍然保留；可回滚本次代码改动并恢复部署版本。
