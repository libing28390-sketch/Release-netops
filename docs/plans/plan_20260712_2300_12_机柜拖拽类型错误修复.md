# 机柜拖拽类型错误修复实施计划

## 任务目标

修复 `npm run lint` 当前阻塞的 TypeScript 类型错误，为后续 CMDB/IPAM 整改恢复干净的前端质量检查基线。

## 现状问题

`src/pages/RackManagement/components/RackElevation.tsx` 中 `onDeviceMove` 的类型为：

```ts
(deviceId: string, newStartU: number) => Promise<void>
```

但父组件 `src/pages/RackManagement/index.tsx` 传入的 `handleDeviceMove` 返回 `void`，导致 `npm run lint` 失败：

```text
Type '(deviceId: string, newStartU: number) => void' is not assignable to type
'(deviceId: string, newStartU: number) => Promise<void>'.
```

## 影响范围

- `src/pages/RackManagement/index.tsx`
- `docs/walkthrough/walkthrough_机柜拖拽类型错误修复.md`

## 拟修改文件

1. `src/pages/RackManagement/index.tsx`
   - 将 `handleDeviceMove` 改为异步回调，满足子组件类型契约。
   - 保持现有行为不变：拖拽后仍先打开确认弹窗，真正保存由确认动作执行。

## 实施步骤

1. 检查 `RackElevation` 的 props 类型定义。
2. 检查父组件 `handleDeviceMove` 的实际行为。
3. 修改父组件回调返回类型为 `Promise<void>`。
4. 运行 `npm run lint`。
5. 运行 `git diff --check`。

## 验证计划

1. `npm run lint`
2. `git diff --check`

## 风险与回滚思路

- 风险低：只改变函数返回类型，不改变业务行为。
- 回滚：将 `handleDeviceMove` 恢复为普通同步回调即可。
