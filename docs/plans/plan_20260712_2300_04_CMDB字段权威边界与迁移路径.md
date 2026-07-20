# CMDB 字段权威边界与迁移路径实施计划

## 任务目标

为后续 CMDB/IPAM 企业级整改明确 `physical_assets`、`devices`、`interfaces` 与 `ip_addresses` 的字段权威边界，避免继续在多个表中重复维护同一语义字段。

本轮以架构文档和迁移路径为主，不直接执行数据库结构迁移。

## 现状问题

当前项目已经具备 CMDB 主骨架：

- `devices`：设备运维对象。
- `interfaces`：设备接口对象。
- `ip_addresses`：IPAM 地址对象，可关联 `device_id`、`interface_name`、`interface_id`。
- `physical_assets`：物理资产与机柜/采购/PAM 入口字段。

但现有字段存在重复和边界不清：

1. `devices.site` 与 `devices.site_id` 并存。
2. `devices.ip_address` 与 `physical_assets.management_ip` 并存。
3. `devices.vendor/model/sn` 与 `physical_assets.vendor/model/serial_number` 并存。
4. 凭据字段仍在 `devices`、`physical_assets`、`credentials` 多处存在历史副本。
5. IPAM 中仍保留 `interface_name` 字符串，同时已经引入 `interface_id`。
6. 拓扑链路也同时保留端口字符串和 `source_interface_id/target_interface_id`。

## 影响范围

本轮主要影响文档和后续任务定义：

- `docs/architecture/cmdb_field_authority_migration.md`
- `docs/plans/plan_CMDB字段权威边界与迁移路径.md`
- `docs/walkthrough/walkthrough_CMDB字段权威边界与迁移路径.md`

后续真正执行迁移时会影响：

- `backend/database/schema.py`
- `backend/database/migrations/`
- `backend/services/cmdb_service.py`
- `backend/api/assets.py`
- `backend/api/devices.py`
- `backend/services/vault_service.py`
- `src/pages/CmdbManagementTab.tsx`
- `src/pages/DeviceManagement.tsx` 或对应设备资产页面

## 实施步骤

1. 检查当前表结构、迁移逻辑和 CMDB 只读接口。
2. 明确四层权威模型：
   - 资产层：`physical_assets`
   - 设备层：`devices`
   - 接口层：`interfaces`
   - 地址层：`ip_addresses`
3. 明确重复字段的权威归属、过渡读写策略和最终目标。
4. 明确 `site_id`、`interface_id` 两条关键迁移路径。
5. 形成后续可执行任务拆分。
6. 做文档完整性和 diff 检查。

## 验证计划

1. 检查文档是否覆盖：
   - 字段权威矩阵
   - 迁移阶段
   - API 兼容策略
   - 风险与回滚
2. `git diff --check`

## 风险与回滚思路

- 本轮不改数据库，不改变运行时行为，风险低。
- 若后续迁移执行中发现历史数据异常，可以回滚到“兼容读、双写、只读展示”的过渡阶段。
- 真正删除 legacy 字段前，必须完成数据审计、回填校验、API 消费方替换和备份。
