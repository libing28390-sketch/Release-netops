# PostgreSQL fresh/upgrade 96 验收实施计划

## 任务目标

为 2026-08-04 自定义平台、TextFSM、Playbook 审查清单收口 P0-4，在不触碰现有 `netops` 业务库的前提下，验证 PostgreSQL 从空库 fresh 初始化、从 schema version 95 升级到 96、重复执行幂等，以及平台注册表关键对象与 Huawei VRP5 SYSTEM Release checksum 契约。

## 发现与修复

1. `backend/database/schema.py` 在 PostgreSQL fresh 基线中先创建 `devices(asset_id)` 唯一索引、后补 `asset_id` 列，导致事务 aborted。修复为先 `ensure_column('devices', 'asset_id', 'TEXT')`。
2. `backend/database/migrations/m0005_update_racks_table.py` 在已由 fresh 基线创建 `racks_rack_code_key` 时重复添加约束，异常捕获未恢复 PostgreSQL 事务。修复为检查约束存在性，并对历史重复数据使用 savepoint 回滚后继续。

## 验收步骤

1. 读取项目 `.env` 的 PostgreSQL 连接参数，仅连接 `postgres` 管理库创建随机临时库名；禁止使用现有 `netops` 作为探针目标。
2. Fresh 探针：空库执行基线 `_init_db_logic(..., allow_legacy_import=False)`，运行全部迁移至 96，再运行一次迁移；记录迁移数、版本连续性、表/索引/约束数量和关键表。
3. Upgrade 探针：空库执行同一基线，按迁移模块写入 1～95 的追踪记录，运行正式迁移器补齐 96，再运行一次；确认仅应用 m0096 一次。
4. 在 fresh/upgrade 两个数据库分别查询 SYSTEM Huawei VRP Release 的 `get_link_aggregation` 动作，确认命令为 `display eth-trunk`，command checksum 与 release checksum 可复算一致。
5. 在每个探针的 `finally` 中使用 `DROP DATABASE ... WITH (FORCE)` 清理随机临时库；不删除工作树文件。

## 验收结果

- PostgreSQL 18.4。
- Fresh：96/96 迁移，重复 0；约 8.894 秒；193 tables、552 indexes、1644 constraints。
- Upgrade：95→96 应用 1，重复 0；约 7.986 秒；最终同为 193 tables、552 indexes、1644 constraints。
- fresh/upgrade 关键 parser audit 表和两个 audit 索引均存在；版本 1～96 无缺失。
- fresh/upgrade 各 1 个 Huawei SYSTEM Release，命令与 command/release checksum 均通过复算。
- 临时库均已清理；现有业务库只做了只读版本查询。

## 未覆盖项

真实 VRP5 设备执行、五类角色页面自动化、浏览器写流程、国产设备在线识别和真实 Playbook Apply/审批仍需明确授权与外部环境，不能用本次临时数据库验收替代。
