# 机柜管理类型模板前端优化计划

## 背景

当前后端已经具备 `rack_types` 机柜类型模型，`racks` 也已经支持 `rack_type_id`、`width_mm`、`depth_mm`、`allow_front_rear_mount` 等字段。前端机柜管理页面仍主要依赖手工填写 `total_u` 和功率容量，用户无法直接选择标准机柜模板。

## 目标

1. 机柜管理页读取 `/api/rack-types`。
2. 新建/编辑机柜时支持选择机柜类型模板。
3. 选择模板后自动带出：
   - 总 U 位
   - 宽度
   - 深度
   - 最大承重
   - 最大功率
   - 是否允许正反面挂载
4. 允许用户在机柜实例上覆盖模板默认值。
5. 导入/导出支持机柜类型和规格字段。
6. 保持已有机柜动态 `total_u`、U 位冲突校验和拖拽逻辑不变。

## 实施步骤

1. 扩展 `src/pages/RackManagement/types.ts`
   - 新增 `RackType`
   - 扩展 `Rack` 和 `RackLayout` 的规格字段
2. 扩展 `src/pages/RackManagement/index.tsx`
   - 增加 `rackTypes` 状态
   - 增加 `loadRackTypes`
   - 初始加载和刷新时读取机柜类型
   - `rackForm` 增加模板和规格字段
   - 新建/编辑弹窗增加模板选择和规格字段
   - 选择模板时自动填充默认值
   - 保存机柜时提交新增字段
3. 扩展导入/导出
   - 模板增加 `Rack Type` / `机柜类型`
   - 导入时通过类型名称匹配 `rack_type_id`
   - 导出时展示类型名称和规格
4. 验证
   - `npm run lint`
   - 相关后端 rack 测试
   - 必要时 `npm run build`

## 验收标准

- 新建机柜可以选择机柜类型。
- 选择类型后自动填充默认规格。
- 用户仍可手动修改实例规格。
- 编辑已有机柜时能看到已关联的类型和规格。
- 导入导出字段完整。
- TypeScript 检查通过。
