# SNMP 硬件告警与巡检状态接线走查

## 完成摘要

- 将本地 LibreNMS 硬件库存中的风扇/电源状态接入统一服务，按可信来源、当前发现状态、good 质量和采样 freshness 筛选；多个传感器取最差状态。
- 后台监控复用已有硬件 poller 的样本触发风扇/电源故障告警，不发起新的设备 SNMP 请求；缺失、陈旧或不支持的状态不触发故障或恢复。
- SNMP 巡检只把 memory_usage_percent 传入内存阈值，不再把内存字节数作为百分比；新鲜风扇/电源状态写入既有结果字段，明确 failed 状态生成 critical 巡检 finding。
- 接口清单刷新把完整 IF-MIB/CLI 状态快照来源、覆盖数及快照起始时间写入现有 device_collection_status。SNMP 接口巡检只读最近 1800 秒内完整且来源为 IF-MIB 的 CMDB 快照；不重复走接口 OID，admin-down 不计入 down 数，状态未知或快照不完整时返回采集错误。
- 监控 API 和后台告警共用硬件状态汇总逻辑，避免状态码/新鲜度规则分叉。

## 实际修改文件

- backend/services/snmp_hardware_status_service.py（新增）
- backend/services/inspection_service.py
- backend/services/interface_collection_service.py
- backend/services/background_monitor_service.py
- backend/api/monitoring.py
- docs/plans/plan_20261014_1415_01_SNMP硬件告警与巡检状态接线.md

## 关键实现说明

- LibreNMS 通用状态码映射为 0=ok、1=warning、2=failed、3=unknown；设备级 fan/PSU 状态按 failed > warning > unknown > ok 汇总。
- 状态查询只读风扇/电源类别，并要求当前 collector 版本、可信规则来源、已启用、active/present、good 质量及未过期的 last_success。
- 接口快照使用现有 collection_status freshness 规则（1800 秒）；CMDB 行的 last_seen 必须不早于快照起始时间，去重后的行数还必须等于采集覆盖数。
- 接口状态采集失败会把 interface_status 标成 failed，防止巡检继续使用前一次成功快照；CLI fallback 快照不会被 SNMP 巡检误认为 IF-MIB 数据。
- IF-MIB error/discard 和 interface flap 仍未接入活跃告警闭环。现有路径没有稳定的 counter snapshot owner；启用前需要把采样、baseline/delta、重启/rollover 识别和告警恢复接入一个统一快照流程。

## 验证命令与结果

- python -m py_compile backend/services/snmp_hardware_status_service.py backend/services/inspection_service.py backend/services/interface_collection_service.py backend/services/background_monitor_service.py backend/api/monitoring.py：通过。
- git diff --check：通过；Git 仅提示若干既有文件将按仓库属性转换行尾格式。
- 未执行自动化测试或前端 lint；本次改动为后端 Python，且本轮未要求运行测试。

## 剩余风险与后续建议

- 首次刷新前，或最近一次接口刷新走 CLI fallback 时，SNMP 接口巡检会显示明确的快照不可用原因；完成 IF-MIB 刷新后再采样即可。
- 需要单独确定 error/discard rate 的单位与阈值语义，以及 flap 告警的观察窗口、去重粒度、恢复条件；随后由唯一 IF-MIB 快照 owner 统一写 counters、基线和告警，避免并行 pollers。
