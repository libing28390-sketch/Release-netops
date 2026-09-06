# RackVision 当前项目架构基线

基线日期：2026-09-06  
页面：`/cmdb/racks`  
状态：已按当前仓库代码核对；本文描述真实实现，不把需求附件中的示例路径当作现状。

## 1. 代码入口

| 层 | 当前入口 |
|---|---|
| React 页面 | `src/pages/RackManagement/index.tsx` |
| 2D 视图 | `src/pages/RackManagement/components/RackElevation.tsx` |
| 3D 容器 | `src/pages/RackManagement/Rack3D/index.tsx` |
| 3D 场景 | `src/pages/RackManagement/Rack3D/RackScene.tsx` |
| 3D 设备 | `src/pages/RackManagement/Rack3D/RackDeviceItem.tsx` |
| FastAPI 路由 | `backend/api/racks.py`、`assets.py`、`device_health.py`、`topology.py` |
| 机柜服务 | `backend/services/rack_service.py` |
| 位置写模型 | `backend/services/rack_placement_service.py` |
| 数据质量 | `backend/services/rack_data_quality_service.py` |
| 数据库基线 | `backend/database/schema.py` |
| 迁移 | `backend/database/migrations/m0210_rackvision_canonical_placement.py` |

## 2. 真实数据流

```text
2D Rack Management
  ├─ GET /api/racks/{id}/layout
  ├─ POST/PUT/DELETE /api/rack-devices
  └─ POST/PUT /api/assets
          ↓
PostgreSQL: racks + rack_devices + device_types + physical_assets
          ↓
同一份 RackLayout read model
  ├─ 2D elevation：只绘制合法 u_mount
  ├─ 3D viewer：只读消费合法 u_mount
  ├─ list/statistics：标准 U 与非 U 分开统计
  └─ quality API：查询、审计、关闭数据问题
```

3D 不拥有独立的位置保存接口。资产解析只决定视觉模型，不改变 CMDB 的设备身份、资产编号或位置。

## 3. 当前持久化关系

- `racks`：机柜容量、站点和 `mount_policy`。
- `rack_devices`：唯一安装写模型；`start_u` 可为空，非 U 设备使用 `mount_kind`、`position`、`location_note`。
- `device_types`：设备型号、U 高度、物理尺寸、尺寸状态和默认安装方式。
- `physical_assets`：资产主数据；通过 `rack_id`、`rack_position`、`rack_mount_kind` 等投影字段与安装写模型同步，兼容旧的 `rack/rack_unit/planned_start_u` 字段。
- `rack_data_quality_issues`：位置冲突、未知尺寸、重复安装等问题的可查询记录。

## 4. 安全基线

- assets、health、topology 的读取路由要求 Viewer。
- 资产/机柜/拓扑变更要求 Operator；删除和批量敏感操作要求 Administrator。
- 资产密码、SNMP community、Vault 路径不进入普通响应。
- 3D 资产解析返回的是静态目录元数据和解析级别，不返回凭据或设备连接信息。

## 5. 现有 3D 现状和本次边界

当前 3D 设备由 React Three Fiber 的程序化/程序纹理模型组成，仓库中尚没有可发布的 GLB 生产资产。已加入：

- 可追溯 `assets/catalog` 目录和 `asset_registry`；
- exact/family/vendor generic/global generic 解析器；
- GLB 尚未生成时的程序化兜底状态；
- Blender headless 生成、验证、导出和缩略图脚本；
- 2D/3D 共用位置读模型。

因此，模型文件发布仍是后续有外部 Blender 运行环境和人工审核后才能完成的任务，不把“已登记模型”误报成“已有 GLB”。

## 6. 已知偏差和处理方式

1. 旧数据可能只有自由文本机柜/机柜 U 位，迁移不会启动时静默回填；使用 `backend/scripts/rackvision_backfill.py` 先 dry-run，再审批 apply。
2. SQLite 只作为兼容开发路径；生产以 PostgreSQL 迁移和事务语义为准。
3. 由于当前没有已审核 GLB，3D 先显示程序化模型，并在 Inspector 中显示 visual fidelity。
4. 非 U 设备仍出现在列表、Inspector 和质量面板中，但不参与标准 U 容量，也不被强行绘制在 U1。

