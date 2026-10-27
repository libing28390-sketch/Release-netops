# CMDB接口采集顺带CLI VLAN

- 日期：2026-10-28（Asia/Shanghai）。
- 对应方案：[plan_20261028_0738_01_CMDB接口采集顺带CLI_VLAN.md](../plans/plan_20261028_0738_01_CMDB接口采集顺带CLI_VLAN.md)。
- 状态：已实现并通过聚焦回归，等待推送后 Actions 验证。

## 完成内容

- 现有 `/cmdb/interfaces` 手动任务保持原路径：对启用 VLAN 策略的设备，在同一 `PlatformActionSession` 中请求接口与 `get_vlan_table`，结果写入 CMDB generation 快照。
- Network Reality/NSOT 接口库存任务不再把 VLAN 域交给 Q-BRIDGE SNMP；接口 IF-MIB/IP-MIB 分支仍按原参数采集。VLAN 域调用同一个 CMDB CLI collector 的 `vlan_only` 模式，继续使用已有 action、TextFSM、`cmdb_cli` SSH 容量和独立快照 writer。
- VLAN CLI 失败时写失败的 snapshot attempt，保留 last-good 观测；不会把 CLI VLAN 数据写入共享 `interfaces` 或 `vlans` 表。设备 collection plan 未启用 VLAN 时不会请求 VLAN CLI。
- NSOT 采集预览将 VLAN transport 标记为 `CLI/SSH`。没有新增 VLAN 页面按钮、独立调度器或解析模板。

## 修改文件

- `backend/services/cmdb_cli_collection_service.py`
- `backend/services/interface_collection_service.py`
- `backend/services/nsot_collection_preview_service.py`
- `backend/tests/vendor_audit/test_cmdb_cli_collection.py`
- `backend/tests/vendor_audit/test_nsot_collection_preview_api.py`
- `docs/plans/plan_20261028_0738_01_CMDB接口采集顺带CLI_VLAN.md`
- `docs/walkthrough/walkthrough_20261028_0738_01_CMDB接口采集顺带CLI_VLAN.md`
- `docs/fixes/fix_20261028_0738_01_CMDB接口采集顺带CLI_VLAN.md`

## 验证结果

- `.venv/Scripts/python.exe -m pytest backend/tests/vendor_audit/test_cmdb_cli_collection.py backend/tests/vendor_audit/test_nsot_collection_preview_api.py backend/tests/vendor_audit/test_interface_collection.py backend/tests/vendor_audit/test_snmp_first_interface_collection.py backend/tests/scheduled_jobs/test_nsot_scope_execution.py -q`：40 passed（143.58s）。
- `.venv/Scripts/python.exe -m pytest backend/tests/vendor_audit/test_interface_collection_contract.py -q`：4 passed（42.74s）。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过；只有既有换行格式提示。
- 未触发真实设备采集。没有修改监控代码、Q-BRIDGE/IF-MIB/IP-MIB实现或 TextFSM 模板/解析逻辑。

## 未验证项与风险

- 现场设备命令是否完整仍取决于设备当前发布 profile、VLAN collection plan、账号授权与输出。未绑定/不支持 `get_vlan_table` 的设备会记录失败并保留 last-good。
- Redis现场验收按用户要求忽略。真实多厂商设备输出对账未执行。
