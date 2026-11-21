# PostgreSQL fresh/upgrade 96 验收 Walkthrough

## 目标 / Goal

在隔离的临时 PostgreSQL 中验证 Nexora schema version 96 的 fresh 初始化、95→96 升级和重复执行幂等性，不写入现有 `netops` 业务库。

Validate fresh initialization, 95→96 upgrade, and repeatability for schema version 96 in disposable PostgreSQL databases without writing to the existing `netops` business database.

## 修复 / Fixes

- `schema.py` now ensures `devices.asset_id` before creating its partial unique index, so a new PostgreSQL baseline does not abort its transaction.
- `m0005_update_racks_table.py` checks `racks_rack_code_key` before adding it and protects the legacy duplicate-data path with a PostgreSQL savepoint.

## 验证 / Verification

| Probe | Result |
| --- | --- |
| Fresh | 96 migrations applied, repeat 0; 193 tables, 552 indexes, 1644 constraints; ~8.894s |
| Upgrade | 95→96 applied 1, repeat 0; final 193 tables, 552 indexes, 1644 constraints; ~7.986s |
| Version continuity | `schema_migrations` contains 1..96 with no gaps |
| Registry contract | Huawei SYSTEM `get_link_aggregation` is `display eth-trunk`; command and release checksums recompute correctly in both probes |
| Cleanup | Both random databases dropped with `WITH (FORCE)` in `finally` |
| Regression gate | 505 backend tests passed, 1 pre-existing Starlette/httpx deprecation warning, 25 subtests passed |

## 边界 / Boundary

No real device commands, browser write workflows, template persistence, Playbook Apply, or approval execution were performed. The duplicate untracked `m0090` file was hash-compared with the official migration and left for the user to decide.
