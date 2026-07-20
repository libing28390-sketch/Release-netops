# CMDB/IPAM 数据关系与权威矩阵完成报告

## 完成摘要

已完成企业级整改路线图 `ENT-001` 的第一段基线工作：梳理当前项目 CMDB、IPAM、Discovery、Asset、Device、Interface 的数据模型关系，并形成字段权威矩阵。

本次只新增文档，不修改业务代码、数据库结构或前端页面。

## 新增文件

- `docs/plans/plan_CMDB_IPAM数据关系与权威矩阵.md`
- `docs/architecture/cmdb_ipam_data_model.md`
- `docs/architecture/cmdb_ipam_authority_matrix.md`
- `docs/walkthrough/walkthrough_CMDB_IPAM数据关系与权威矩阵.md`

## 关键结论

1. 当前项目底层已经具备 `devices + interfaces` 作为网络 CMDB 主骨架的基础。
2. `interfaces` 已有 `device_id` 外键和 `(device_id, interface_name)` 唯一索引，方向正确。
3. `topology_links` 已支持 `source_interface_id` 和 `target_interface_id`，拓扑已经开始向接口级关系收敛。
4. `prefixes` 已绑定 VRF、VLAN、site、tenant，IPAM 与 CMDB 基础对象已有关系。
5. `ip_addresses` 已预留 `interface_id`，但当前主路径仍偏向 `interface_name` 字符串。
6. CMDB 页面和 `/api/cmdb/*` 当前主要覆盖 credentials、sites、racks、VRFs、VLANs、tenants，尚未把 devices/interfaces 纳入 CMDB 主入口。
7. `network_endpoints` 和 IPAM reconciliation 已有基础对账能力，但还缺 finding/action/audit 的闭环状态机。

## 验证方式

已人工核对以下文件和模块：

- `backend/database/schema.py`
- `backend/api/cmdb.py`
- `backend/api/ipam.py`
- `backend/api/assets.py`
- `backend/api/devices.py`
- `backend/api/interfaces.py`
- `backend/services/cmdb_service.py`
- `backend/services/ipam_service.py`
- `src/pages/CmdbManagementTab.tsx`
- `src/pages/IPVlan/`

## 未执行验证

- 未运行 `pytest`。
- 未运行 `npm run lint`。
- 未运行 `npm run build`。

原因：本任务只新增 Markdown 架构文档，不涉及代码、schema、API contract 或前端行为变更。

## 剩余风险

- 当前文档基于代码结构和 schema 静态分析，未连接真实生产数据库检查历史脏数据。
- `backend/database/schema.py` 中存在历史兼容字段和迁移辅助逻辑，后续落地迁移前仍需基于真实数据进行 dry run。
- 下一阶段如果开始修改 schema，必须单独创建迁移计划并执行数据备份/回滚设计。

## 下一步建议

建议执行 `CMDB-000：确立 device + interface 为 CMDB 主骨架`，目标是将设备和接口正式纳入 CMDB 聚合 API、页面导航和后续 IPAM/拓扑/监控关系中。
