# SNMP 型号回写资产与机柜执行记录

## 完成摘要

- 资产导入和手动新增继续使用已有 SNMP identity 补全任务；型号为空时，额外读取 ENTITY-MIB 的 chassis 型号，覆盖 SNMPv2c 与 SNMPv3。
- 按 ENTITY-MIB 索引关联型号、实体类型和父实体，仅选择可确定的 chassis/root stack；空表、超限、错误或歧义时不把板卡型号写成整机型号。
- 命中的型号写入 `devices.model` 和 `physical_assets.model`。保留已有手动型号；`sysDescr` 支持明确的 H3C 产品型号行（如 `H3C S6850`、`H3C SecPath F1090`、`H3C WX5540H-HCL`），不把 Comware OS 描述误写成型号。
- HCL 只读实测发现 S6850 每个 ENTITY-MIB 型号/类型/父关系列有 259 行；原 200 行上限会拒绝完整结果。型号 walk 上限提高为 2000 行，并使用独立单并发信号量；主机名探测仍保留批量并发。
- 有机柜位置的导入即使型号为空，也先保存 rack ID 与位置字段；型号识别后再创建或更新 `rack_devices.device_type_id`，并把关联型号键规范化为真实厂商/型号。原来显式保存的 `generic_*` key 会清除，目录中的 generic 3D 外观按用户要求保留。
- 新增 m0297 清理未引用的 `Generic / Patch Panel 24P` device type；SQL 同时确认 rack_devices、devices 都没有引用才删除。
- 测试初始化本机数据库时应用了 m0297；事后只读查询确认最新版本为 297，目标占位型号行数为 0。没有部署或连接真实网络设备。

## 实际修改文件

- `backend/services/snmp_entity_model_service.py`
- `backend/services/snmp_import_identification_service.py`
- `backend/services/snmp_discovery_service.py`
- `backend/api/assets.py`
- `backend/database/migrations/m0297_remove_unused_generic_patch_panel_type.py`
- `backend/tests/snmp/test_snmp_entity_model_service.py`
- `backend/tests/snmp/test_snmp_discovery_identity.py`
- `backend/tests/configuration/test_asset_management_method_import.py`
- `backend/tests/database/test_m0297_remove_unused_generic_patch_panel_type.py`

## 验证命令与结果

- `..\.venv\Scripts\python.exe -m pytest --confcutdir=tests/snmp -q tests/snmp/test_snmp_discovery_identity.py tests/snmp/test_snmp_entity_model_service.py`：18 passed，覆盖 H3C `sysDescr` 型号提取、259 行表和 2000 行上限失败关闭。
- `..\.venv\Scripts\python.exe -m pytest -q tests/configuration/test_asset_management_method_import.py::test_batch_import_auto_identifies_device_without_custom_metric_profile_binding`：1 passed（63.33 秒）。导入隔离测试批量导入 6 台设备，断言型号 walk 最大并发为 1，6 台型号都写入，并保持机柜型号同步。
- `backend/tests/database/test_m0297_remove_unused_generic_patch_panel_type.py` 的两个迁移用例在组合运行中均通过：未引用行删除、仍被机柜引用的行保留。
- `.\.venv\Scripts\python.exe scripts/validate_postgresql_only.py`：0 violations。
- `py_compile` 覆盖本次修改的服务、API 和测试文件，通过；`git diff --check` 通过。Git 提示部分既有 CRLF 文件后续写入时会转换行尾，没有 whitespace error。
- 一次较早的组合测试先后触发并修复了导入链路的 rack 输入暂存和测试预期；最终单独重跑的导入到机柜回归用例通过。没有在最后修正断言后重跑整组测试。

## 未执行项与剩余风险

- HCL 上的只读 SNMP 验证：`.10.254.0.1-.6` 的 `sysName`、H3C `sysDescr` 型号与 ENTITY-MIB 型号均返回成功；逐台走表 6/6 返回 `H3C S6850`。保持导入的 5 设备并发时曾只有 1/6 成功；型号 walk 单并发后实测 6/6 成功。无交换机配置写入，也未修改运行数据库中的真实资产记录。
- ENTITY-MIB 超过 2000 行或设备拒绝 walk 时仍会失败关闭；H3C `sysDescr` 明确型号行可作为兜底。尚未验证物理 H3C 设备。
- `.192.168.56.11/.12` 的 SNMP `sysDescr` 明确写 `H3C SecPath F1090`，但 ENTITY-MIB chassis 名称为 `H3C F1060`。这是两个 SNMP 身份来源的实测冲突；现有优先级仍选 ENTITY-MIB，需按设备/HCL 的预期型号另行判定，不能把两者宣称为一致。
- 本机 `127.0.0.1:15310` API 当前无监听，未进行浏览器端导入验收；SNMP 运行验证直接复用了资产绑定的当前 SNMP Profile，并且只读。
- 未部署服务。版本化清理迁移已在本机测试初始化中执行；其他环境将在运行数据库迁移时删除同名且未引用的 generic 记录。
- 用户要求保留的 generic 3D 渲染兜底未删除。
