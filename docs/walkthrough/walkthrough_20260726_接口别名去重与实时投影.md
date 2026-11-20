# 接口别名去重与实时投影

## 目标

- 同一设备的同一接口只展示一行。
- H3C 的 `GE/GigabitEthernet`、`Loop/LoopBack`、`RAGG/Route-Aggregation` 等展示别名统一按规范接口键匹配。
- `ip_inventory` 只作为最新地址投影，不因名称别名再次生成一条接口记录。

## 实现

- `cmdb_service.list_cmdb_interfaces` 按设备与规范化接口键去重，并将 `ip_inventory` 的最新地址合并到已有接口骨架。
- `m0036_consolidate_interface_aliases` 合并已有历史别名记录，同时修复 IP、拓扑和接口时间线引用。
- `m0037_consolidate_short_loop_aliases` 覆盖 `Loop0` 与 `LoopBack0` 这类短名称别名。
- `InventoryRepository.save_interface` 按规范化接口键复用已有行，避免后续通用同步再次创建别名记录。

## 验证

- H3C 当前数据库 `interfaces` 规范化重复行：`0`
- `S6850-3` 接口目录：由 `6` 行收敛为 `5` 行
- `.venv\\Scripts\\python.exe -m pytest backend/tests/vendor_audit/test_interface_alias_consolidation.py backend/tests/vendor_audit/test_interface_collection.py backend/tests/vendor_audit/test_interface_collection_contract.py backend/tests/vendor_audit/test_topology_link_normalization.py -q`：`13 passed`
