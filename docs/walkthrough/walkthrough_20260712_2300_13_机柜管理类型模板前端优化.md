# 机柜管理类型模板前端优化执行记录

## 执行时间

2026-07-12

## 本次目标

在已有 `rack_types` 后端模型基础上，补齐机柜管理页面的可用体验：

- 读取机柜类型模板
- 新建/编辑机柜时可选择模板
- 选择模板后自动带出机柜规格
- 导入/导出支持机柜类型和规格字段
- 默认提供常见机柜类型模板

## 完成内容

### 1. 前端类型补充

更新：

- `src/pages/RackManagement/types.ts`

新增：

- `RackType`

扩展：

- `Rack.rack_type_id`
- `Rack.width_mm`
- `Rack.depth_mm`
- `Rack.allow_front_rear_mount`
- `RackLayout.rack_type_id`
- `RackLayout.width_mm`
- `RackLayout.depth_mm`
- `RackLayout.max_weight_kg`
- `RackLayout.power_capacity_watts`
- `RackLayout.allow_front_rear_mount`

### 2. 机柜管理页面读取机柜类型

更新：

- `src/pages/RackManagement/index.tsx`

新增状态：

- `rackTypes`

新增加载逻辑：

- `GET /api/rack-types`

页面初始化和刷新时会同步加载机柜类型。

### 3. 新建/编辑机柜支持模板

机柜表单新增：

- 机柜类型模板选择
- 宽度
- 深度
- 最大承重
- 是否允许正反面挂载

选择模板后自动填充：

- `total_u`
- `width_mm`
- `depth_mm`
- `max_weight_kg`
- `power_capacity_watts`
- `allow_front_rear_mount`

用户仍可在保存前手动覆盖实例规格。

### 4. 机柜列表展示规格摘要

机柜卡片增加：

- 机柜类型名称
- U 数
- 宽度 × 深度

### 5. 导入/导出增强

导入模板新增字段：

- `Rack Type` / `机柜类型`
- `Width(mm)` / `宽度(mm)`
- `Depth(mm)` / `深度(mm)`
- `Max Weight(kg)` / `最大承重(kg)`
- `Allow Front/Rear` / `允许正反面`

导入逻辑增强：

- 可通过机柜类型名称匹配 `rack_type_id`
- 匹配到模板时，缺失规格会自动使用模板默认值
- 未匹配到模板时，仍按手工字段导入，不阻断旧数据

导出增强：

- 导出机柜类型
- 导出宽度、深度、最大承重、正反面挂载能力

### 6. 默认机柜类型种子数据

更新：

- `backend/database/schema.py`

新增幂等内置模板：

- `24U Standard Cabinet`
- `42U Standard Cabinet`
- `48U Network Cabinet`
- `12U Wall Mount Cabinet`

这些模板只在不存在时插入，不覆盖用户自定义数据。

## 验证结果

已执行：

```bash
.\.venv\Scripts\python.exe -m pytest backend/tests/test_rack_types.py backend/tests/test_racks_new_fields.py -q
```

结果：

```text
6 passed
```

已执行：

```bash
.\.venv\Scripts\python.exe -m py_compile backend/database/schema.py backend/api/racks.py backend/services/rack_service.py backend/schemas/schemas.py
```

结果：

```text
passed
```

已执行：

```bash
npm run lint
```

结果：

```text
tsc --noEmit passed
```

已执行：

```bash
npm run build
```

结果：

```text
vite build passed
```

说明：

- 构建仍有既有的大 chunk 提示，不影响本次功能。

## 后续建议

1. 增加机柜类型管理页面，支持用户维护模板。
2. 机柜详情页增加完整规格区域，包括承重、功率、前后挂载能力。
3. U 位冲突校验可进一步结合 `allow_front_rear_mount`，对不允许双面挂载的机柜禁用 rear 侧安装。
4. 资产上架推荐算法可结合机柜类型、功耗和承重做容量推荐。
