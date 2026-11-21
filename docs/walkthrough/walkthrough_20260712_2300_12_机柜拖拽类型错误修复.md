# 机柜拖拽类型错误修复完成记录

## 完成摘要

修复了 `npm run lint` 阻塞的 TypeScript 类型错误。

问题位于机柜管理页面：`RackElevation` 子组件要求 `onDeviceMove` 返回 `Promise<void>`，父组件传入的 `handleDeviceMove` 返回 `void`。本轮将父组件回调改为异步函数，保持原有拖拽后打开确认弹窗的行为不变。

## 实际修改文件

1. `src/pages/RackManagement/index.tsx`
   - 将 `handleDeviceMove` 从同步回调改为 `async` 回调。

2. `docs/plans/plan_机柜拖拽类型错误修复.md`
   - 记录实施计划。

## 关键实现说明

`RackElevation` 在拖拽结束时执行：

```ts
await onDeviceMove(activeDevice.id, ghostU);
```

因此父组件传入的函数需要符合：

```ts
(deviceId: string, newStartU: number) => Promise<void>
```

本轮仅修正类型契约，不改变保存逻辑。设备位置实际更新仍由确认弹窗中的 `confirmMoveDeviceAction` 执行。

## 验证命令与结果

### 前端 TypeScript 检查

```powershell
npm run lint
```

结果：通过。

### Diff 空白检查

```powershell
git diff --check
```

结果：通过，仅出现 Windows 换行提示。

## 未执行验证及原因

- 未运行 `npm run build`：本轮是单点类型修复，且 `npm run lint` 已覆盖触发错误的 TypeScript 类型契约。
- 未做浏览器拖拽验证：本轮不改变拖拽业务行为，只修正返回类型。

## 剩余风险

风险低。该修改不会改变拖拽确认、保存或回滚流程。

## 后续建议

继续执行 CMDB-002：梳理 `physical_assets`、`devices`、`interfaces` 的字段权威边界和迁移路径。
