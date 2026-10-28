# pytest 9.2 数据库代理测试隔离修正

- 日期：2026-10-28（Asia/Shanghai）。
- 对应方案：[plan_20261028_0818_01_pytest92数据库代理测试隔离.md](../plans/plan_20261028_0818_01_pytest92数据库代理测试隔离.md)。
- 状态：测试代理修正完成；本地 pytest 9.2.0 聚焦验证通过，最新远端 Actions 待推送后复验。

## 完成摘要

- 远端失败根因为测试 patch 动态代理 `database` 模块。pytest 9.2.0 为非数据描述符目标从实例 `__dict__` 记录旧值；`database.get_db_connection` 由 `_DatabaseModule.__getattr__` 动态代理，且 `__setattr__` 转发至 `database.core`，所以 pytest teardown 将其误认为原先不存在，尝试从代理对象删除，替身残留并污染后续测试。
- 将受影响的连接工厂测试改为直接 patch `database.core.get_db_connection`，生产数据库代理行为保持不变。
- 首次全量 Actions 复测达到 3608 passed、2 skipped，仅剩 `test_rack_read_model.py::test_postgres_asset_check_uses_transaction_scoped_advisory_and_row_locks` 对动态 `_USE_PG` 代理属性的 teardown 错误；已改为直接 patch `database.core._USE_PG`。

## 修改文件

- `backend/tests/security/test_audit_regressions.py`
- `backend/tests/security/test_collector_snmpv3_profile.py`
- `backend/tests/snmp/test_snmp_hardware_probe_service.py`
- `backend/tests/test_rack_read_model.py`
- `backend/tests/vendor_audit/test_collection_plan_bulk_api.py`
- `backend/tests/vendor_audit/test_cmdb_list_performance.py`
- `docs/plans/plan_20261028_0818_01_pytest92数据库代理测试隔离.md`
- `docs/walkthrough/walkthrough_20261028_0818_01_pytest92数据库代理测试隔离.md`
- `docs/fixes/fix_20261028_0818_01_pytest92数据库代理测试隔离.md`

## 验证结果

- `.venv/Scripts/python.exe -m pytest backend/tests/security/test_audit_regressions.py backend/tests/security/test_collector_snmpv3_profile.py backend/tests/snmp/test_snmp_hardware_probe_service.py backend/tests/vendor_audit/test_collection_plan_bulk_api.py backend/tests/vendor_audit/test_cmdb_list_performance.py backend/tests/vendor_audit/test_cmdb_cli_collection.py backend/tests/vendor_audit/test_nsot_collection_preview_api.py backend/tests/vendor_audit/test_interface_collection.py backend/tests/vendor_audit/test_snmp_first_interface_collection.py backend/tests/vendor_audit/test_interface_collection_contract.py backend/tests/scheduled_jobs/test_nsot_scope_execution.py -q`：pytest 9.2.0 下 129 passed、1 skipped（手动 PostgreSQL 性能基准），423.15 秒。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过。
- `backend/services/snmp_service.py`、监控服务及 TextFSM/模板路径无改动。
- pytest 9.2.0 远端 Actions：3608 passed、2 skipped、1 teardown error（`_DatabaseModule` 缺少 `_USE_PG`）；本轮修复后待重跑。
- `.venv/Scripts/python.exe -m pytest backend/tests/test_rack_read_model.py::test_postgres_asset_check_uses_transaction_scoped_advisory_and_row_locks -q`：1 passed（62.31s）。

## 未执行验证与剩余风险

- 本轮 `_USE_PG` 修正尚未提交、推送；远端 release workflow 仍待核验。
- 未触发真实设备采集；本次只修正 pytest 测试替身隔离。
