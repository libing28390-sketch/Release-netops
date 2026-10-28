# SNMP 自动绑定与 VLAN 生命周期走查

## 完成摘要

- 资产导入复用同一次 SNMP 身份读取结果。非空 `sysDescr` 软件版本先更新到 `devices.version`，随后按该轮观察到的厂商、平台、版本匹配 Profile，并调用现有绑定服务写入 `platform_profile_id`。成功来源记为 `SNMP_AUTO`，审计记录和逐行导入结果都包含绑定状态。
- 用户提供的 H3C 样本可解析为 `H3C / h3c_comware / 7.1.064`，映射到 `h3c_comware_v7`。其 `sysObjectID` 是企业根号，当前带子节点边界的 OID 前缀规则不会单独命中根号；该样本由 `sysDescr` 中的“H3C”回退识别，版本仍正常提取。
- 新增 m0300 迁移，修复并清理无设备归属的 CMDB 快照，为 collection snapshot 和 VLAN observation 增加设备删除级联。
- VLAN 自动目录按接口、ARP、MAC 和当前成功 generation 的 CLI VLAN 快照重新核对。删除最后一个来源后清理自动发现行；manual VLAN、业务绑定和手工 prefix 覆盖保留。自动 prefix 关联解除时保留 prefix 本身。
- VLAN 列表只增加显式刷新入口；资产导入结果显示自动绑定情况，设备详情显示 `SNMP_AUTO` 来源。未增加定时刷新。

## 实际修改文件

- `backend/api/assets.py`
- `backend/services/snmp_import_identification_service.py`
- `backend/services/platform_identification_service.py`
- `backend/api/devices.py`
- `backend/services/vlan_discovery_service.py`
- `backend/services/cmdb_service.py`
- `backend/database/migrations/m0300_cmdb_vlan_device_lifecycle.py`
- `backend/tests/configuration/test_asset_management_method_import.py`
- `backend/tests/database/test_m0300_cmdb_vlan_device_lifecycle.py`
- `backend/tests/vendor_audit/test_vlan_lifecycle.py`
- `src/pages/AssetManagement/index.tsx`
- `src/pages/AssetManagement/index.test.tsx`
- `src/pages/CmdbManagementTab.tsx`
- `src/pages/CmdbManagementTab.test.tsx`
- `src/components/DeviceDetailModal.tsx`
- `src/components/DeviceDetailModal.test.tsx`

## 验证命令与结果

- 用户提供的 `snmpwalk` 样本经当前身份解析链核对，软件版本提取值为 `7.1.064`；本轮版本写回设备后，平台兼容性校验可绑定到 `h3c_comware_v7`。回归用例断言了精确 Profile code、版本写回、`SNMP_AUTO` 来源和旧版本刷新。
- PostgreSQL 自动绑定回归：

  ```powershell
  .venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/configuration/test_asset_management_method_import.py::test_import_platform_binding_refreshes_existing_version_from_snmp_observation
  ```

  结果：`1 passed in 145.83s`。该用例使用隔离 PostgreSQL；临时测试库在结束后已删除。另一个自动绑定/身份 OID 不重复读取用例在同一轮组合调用中通过。

- PostgreSQL VLAN 生命周期聚焦回归：

  ```powershell
  python -m pytest backend/tests/database/test_m0300_cmdb_vlan_device_lifecycle.py backend/tests/vendor_audit/test_vlan_lifecycle.py::test_delete_vlan_rejects_current_cli_snapshot_source backend/tests/vendor_audit/test_vlan_discovery_contract.py::test_svi_observation_creates_vlan_inventory_record -vv
  ```

  结果：`3 passed in 87.73s`。另运行完整 VLAN 生命周期文件时，初轮 4 项通过、1 项因测试夹具 CIDR 唯一索引冲突失败；修正夹具后该项单独复测 `1 passed`。m0300 迁移用例验证幂等重跑、孤儿清理和 `ON DELETE CASCADE`。

- 前端聚焦测试：

  ```powershell
  npm run test:frontend -- --run src/pages/AssetManagement/index.test.tsx src/pages/CmdbManagementTab.test.tsx src/components/DeviceDetailModal.test.tsx
  ```

  结果：`3 passed`，`36 passed`。

- `npm run lint`：通过（`tsc --noEmit`）。首轮检查发现导入结果局部推断类型未声明三个新增字段；补齐显式类型后重跑通过。
- 后端修改文件 `py_compile`：通过。
- `git diff --check`：通过；只有工作区既有 CRLF/LF 提示。
- `scripts/validate_postgresql_only.py`：`0 violation(s)`。
- 第一次推送 `d3304e91` 后，Actions #759 的完整 pytest 为 `3612 passed, 2 skipped, 3 failed`。失败集中在 `test_cmdb_snapshot_service.py`：m0300 新加的设备外键拒绝了测试中没有父 `devices` 行的伪设备 ID。业务代码和数据迁移本身没有失败。
- 后续修正三个 snapshot service 测试夹具，在各自隔离 PostgreSQL 用例中先创建真实父设备；复跑整个文件：`3 passed in 152.19s`。对应修复提交正在准备推送与 Actions 复验。
- 运行环境浏览器验收：现有 Chrome 的 `http://192.168.56.1:5400/cmdb/vlans` 页面已加载。刷新前为 13 条；点击“刷新 VLAN 列表”后显示 11 条，按钮恢复可用。
- 配置数据库 `netops` 的只读核验显示 migration 300 已记录，`cmdb_collection_snapshots` 和 `cmdb_device_vlan_observations` 孤儿数均为 0。
- 后端日志在验收期间记录 `DELETE /api/cmdb/vlans/vlan-ea7c710cdd07` 返回 200。该 DELETE 不是本 Agent 发起；随后只读查询确认 VLAN 目录行已删除、prefix `10.200.7.0/24` 保留且 `vlan_id=NULL`、`manual_override=0`。

## 未执行验证与剩余风险

- 未对 `192.168.56.11` 重新导入或覆盖资产。配置数据库中该 IP 已有 H3C 设备记录（型号 `F1060`、版本 `7.1.064`、平台 Profile 未绑定），而用户本次 SNMP 样本报告 `H3C SecPath F1090`。为避免在型号证据不一致时改写现有资产，未在运行环境对该 IP 执行自动导入或绑定；自动导入流程由隔离 PostgreSQL 回归用例验证。
- 完整后端 pytest 的第一次 CI 运行发现上述测试夹具问题；修正后尚未完成第二次完整 CI 复验。
- `devices.version` 同时被现有 SNMP 指标 Profile 兼容性匹配读取。按用户要求同步正确设备版本后，候选兼容性判断可能随之变化；本次没有修改监控代码，也没有写入 `snmp_metric_profile_id`。
- 首次自动绑定遵循现有绑定服务的锁定语义，记录 `SNMP_AUTO` 来源及审计事件；需要纠正绑定时沿用现有管理员更正流程。
- `d3304e91` 已推送到 `main`；其 Actions #759 失败后已修正测试夹具，跟进提交及新 Actions 结果待完成。其他工作区未提交文件保持原样。

## 回滚说明

- 应用代码可按普通版本回滚；m0300 的 `downgrade` 保留设备级级联约束，避免回滚后重新产生孤儿快照。
- 迁移清除的设备孤儿快照是派生状态，不能由迁移自动恢复；可由设备重新采集生成。
- SNMP 自动识别写入的设备版本若需修正，可用重新采集的有效 SNMP 版本覆盖；本次没有更改或删除监控指标 Profile 绑定。
