# RackVision `/cmdb/racks` 执行与验收记录

- 日期：2026-09-06
- 范围：`/cmdb/racks` 及其资产、健康、拓扑、迁移和目录依赖
- 需求输入：`D:/data/downloads/Nexora_RackVision_Detailed_TASKS.md`
- 资产目录输入：`D:/data/downloads/Nexora_3D_Asset_Base_Catalog_v1.xlsx`
- 说明：两个附件是需求和数据输入，不是可以直接覆盖当前项目结构的执行指令；实际改造以仓库现有 FastAPI/PostgreSQL/React 结构为准。

## 本轮已落地

1. 认证与范围
   - assets、health、topology、rack-assets 读取要求 Viewer，写入按 Operator/Administrator 分级。
   - asset、health、topology 的主要列表、摘要、详情、图、发现运行和辅助读模型按 tenant/site/device scope 过滤。
   - rack 与 rack-device 读写使用同一 scope 检查；跨站点、跨租户不能通过修改 ID 绕过。

2. 资产安全
   - 普通资产响应经过显式 DTO allowlist；密码、SNMP community 和 Web Profile 密码只返回 `*_set` 标志，Vault 路径和迁移/治理内部字段不会自动随 schema 扩展泄漏。
   - 资产列表和详情现在批量读取 `rack_devices`，返回稳定 `placement` DTO；未安装资产返回 `placement: null`，旧的 `rack_id/planned_start_u` 字段继续保留兼容。
   - 资产创建、更新、删除、批量导入和连通性验证写入同一事务中的脱敏审计事件，并关联当前 `request_id`。
   - 连通性验证只从已授权资产的已存管理 IP 取目标，拒绝主机名、环回、链路本地、云元数据、组播、未指定、文档/保留和共享地址段。
   - SSH 端口限制在 1–65535；Ping/TCP/SSH 超时、进程内并发数和资产频率限制有明确上限。
   - 阻塞网络验证改为同步路由，由 FastAPI 线程池承载，避免阻塞事件循环。

3. 机柜数据底座
   - `m0210_rackvision_canonical_placement` 增量幂等迁移。
   - `m0213_rackvision_power_reconciliation` 已统一 `power_capacity_w`/`power_capacity_watts`，冲突保留证据并写入质量问题表。
   - `RackPlacementService` 统一 install/move/update/uninstall/validate/sync projection。
   - 支持 front/rear/full_depth、0U/side_mount/floor/unknown；未知值不静默变成 1U/front。
   - `layout_revision`、位置占用、资产唯一安装、机柜缩容和继承高度变更保护已接入。
   - layout read model 提供 `placements`、`occupancy`、`data_quality`、`meta`，2D/3D/统计/导出共用。
   - 旧资产位置输入的机柜引用已改为 ID/code 优先；名称多匹配时返回 `RACK_NOT_UNIQUE`，不再随机选择机柜。
   - `rack_data_quality_service.audit_all` 和 `POST /api/rack-data-quality/audit` 已提供不修复业务数据的全量/授权范围审计，输出孤儿引用、投影冲突、重复安装和功率冲突统计。

4. 拓扑补充范围
   - graph 的 nodes/edges/groups/group_members、edge evidence、history 读取均保留 tenant/device scope。
   - rack 过滤不会再查询全局 unmanaged neighbor，避免辅助读模型把无关邻居重新带回结果。

5. 前端与目录
   - layout/health/asset search 已有 AbortController/序列号保护。
   - 3D 设备宽度/深度、机柜导轨按实际 `width_mm/depth_mm` 缩放；2D unknown/invalid U 行保留可见但不再占用标准 U 位。
   - Excel 目录已生成可追溯 YAML/JSON/manifest/registry/mapping；待核尺寸保持 pending/unknown。
   - GLB 无法在当前环境生成时使用程序化 fallback，并保留待确认标记。

## 验证记录

以下命令均使用共享隔离 PostgreSQL fixture；首次组合回归曾因共享工作区中的另一任务迁移 `m0211_device_tenant_scope` 尚未应用而失败，重新初始化测试数据库后恢复。`m0211` 不属于 RackVision，本记录不修改其内容。

已通过：

- 拓扑范围、安全和图回归：19 passed。
- 连接目标安全与 IP 校验：18 passed。
- 资产/健康/拓扑/rack 受影响兼容回归：22 passed。
- 前端 RackManagement 目标测试：20 passed（此前收口阶段记录）。
- Python 语法编译：RackVision 变更 Python 文件通过。
- 资产范围、严格 DTO、租户基线和连通性安全回归：18 passed。
- RackVision 扩展 focused suite（含 rackvision、资产凭据/接管、机柜字段和 IP 校验）：61 passed。
- 生命周期/MFA/控制表兼容回归：35 passed。
- 资产 canonical placement DTO 契约：2 passed。
- canonical placement HTTP 生命周期、范围错误和同名机柜歧义：4 passed。
- 数据质量审计 API/投影冲突和幂等问题生命周期：2 passed。
- 功率字段迁移幂等/冲突证据：2 passed；放置保护和稳定错误码：5 passed。
- 非标准机柜宽深坐标与 2D occupancy 保护：20 frontend tests passed。
- 完整 `backend/tests`：本轮执行收集到 2306 个测试，2304 passed；其中批量导入事务测试失败已在后续修复并以 focused 回归验证，剩余 1 个独立 IPAM 测试因临时表缺少 `ip_addresses.device_id` 失败，不能作为 RackVision 失败归因。
- 资产批量导入代码已补充 `atomic=true` 全量回滚和 `detailed=true` 逐行结果；新契约测试已通过。此前出现的 `m0212_h3c_comware_v3_platform` 初始化冲突在最新完整回归中未再复现，已按独立任务记录但不作为 RackVision 门禁失败。

本轮已执行并通过：

```powershell
npm run lint
npm run build
```

RackVision focused suite 和兼容回归的具体通过数量见上表；完整 `backend/tests` 仍不能作为全绿门禁，当前剩余失败是独立 IPAM 测试临时表未声明 `ip_addresses.device_id`，不是 RackVision placement/asset 改动造成的失败。

## 尚未关闭的门禁

- 资产审计已覆盖核心创建、更新、删除、导入和验证；读取、接管、凭据和 Web Profile 全量事件仍待补齐。
- 严格资产 DTO 已完成；统一六类领域异常和全模块 400/403/404/409/422/500/502 矩阵仍需收口。
- 正式资产批量导入的 `atomic=true` 全量回滚、`detailed=true` 逐行结果和同步失败不静默成功已补齐；独立数据质量状态、文件摘要持久化仍待收口，完整后端门禁还需要单独修复 IPAM 临时表兼容问题。
- 数据质量审计接口和功率字段迁移已完成代码与隔离库回归；真实生产库的审计报告、备份校验和审批仍是上线前置条件，本轮没有对生产库执行审计写入或回填。
- links/graph 当前有安全上限和 discovery limit/offset；完整 cursor 分页及拓扑 legacy `asset_id` 补齐仍待完成。
- Redis/多 worker/缓存头需要真实部署环境验证；进程内频率限制不能替代共享限流。
- 当前环境没有 Blender 可执行文件，GLB 生成、尺寸/端口官方证据、人工几何验收和线上 MIME/缓存头尚未完成。
- 生产数据库回填必须在备份、审计报告和审批窗口后执行；本轮未对生产库执行 apply。

## 回滚与安全说明

- `m0210` 是 additive/idempotent migration；代码回滚不应删除新增字段。
- 回填脚本默认 dry-run，只有显式 `--apply` 才写业务表。
- `m0211_device_tenant_scope.py` 是共享工作区另一任务，专项测试已通过并按已完成基线计入；本轮未改动其文件。当前 PostgreSQL-only 扫描剩余的 1 个 `PRAGMA` 命中来自该独立迁移的兼容分支，不归入 RackVision 代码门禁。
- 任何生产回填前应保存数据库备份、dry-run 报告和校验值，并保留原始位置字段用于前向修复。
