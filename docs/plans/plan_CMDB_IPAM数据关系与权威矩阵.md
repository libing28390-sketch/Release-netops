# CMDB/IPAM 数据关系与权威矩阵实施计划

## 任务目标

执行企业级整改路线图中的 `ENT-001`，建立当前项目 CMDB、IPAM、Discovery、Device、Asset、Interface 之间的数据关系图和字段权威矩阵，为后续 `CMDB-001`、`CMDB-002`、`IPAM-001`、`REC-002` 等整改任务提供基线。

## 现状与问题

当前项目已经具备 `devices`、`interfaces`、`physical_assets`、`sites`、`vrfs`、`vlans`、`prefixes`、`ip_addresses`、`network_endpoints` 等核心表，但设备、接口、资产、IP、VLAN、站点、发现数据之间仍存在字段重叠和权威边界不清的问题。

## 影响范围

本任务只生成架构文档，不修改业务代码、数据库结构或前端页面。

参考范围：

- `backend/database/schema.py`
- `backend/database/migrations/`
- `backend/api/cmdb.py`
- `backend/api/ipam.py`
- `backend/api/assets.py`
- `backend/api/devices.py`
- `backend/api/interfaces.py`
- `backend/services/cmdb_service.py`
- `backend/services/ipam_service.py`
- `backend/services/endpoint_tracker_service.py`
- `backend/services/topology_service.py`
- `src/pages/CmdbManagementTab.tsx`
- `src/pages/IPVlan/`

## 拟交付文件

- `docs/architecture/cmdb_ipam_data_model.md`
- `docs/architecture/cmdb_ipam_authority_matrix.md`
- `docs/walkthrough/walkthrough_CMDB_IPAM数据关系与权威矩阵.md`

## 实施步骤

1. 盘点核心数据表和模块入口。
2. 梳理 CMDB、IPAM、Discovery、Operational、Security/Audit 五类数据边界。
3. 明确 `device + interface` 在网络 CMDB 中的主骨架地位。
4. 标注重复字段，例如 hostname、IP、MAC、VLAN、site、interface_name。
5. 给出当前一致项、缺口和后续整改任务映射。
6. 生成数据关系文档和权威矩阵文档。
7. 生成 walkthrough，记录完成内容和验证方式。

## 验证计划

- 运行 `git diff --check` 检查 Markdown 格式。
- 核对文档中引用的表名、接口和文件路径是否存在。
- 不运行 pytest/npm build，因为本任务只新增文档，不改代码。

## 风险与回滚

风险：

- 文档可能遗漏某些历史兼容表或迁移辅助字段。
- 当前 schema 中部分字段为兼容旧版本保留，不能直接作为最终模型依据。

回滚：

- 删除本次新增的 `docs/architecture/*.md` 和 walkthrough 文件即可，不影响业务运行。
