# 实施计划 - 凭据残留清理与快捷查询重选按钮修复

## 问题分析

1. **凭据残留与重复问题**：在设备被删除时，关联的 credentials（凭据）表项未能被级联删除。这是因为通过资产列表页面删除资产（调用 `DELETE /assets/{asset_id}`）时，底层调用的 `_delete_linked_device` 级联删除函数中缺少对 credentials 凭据的垃圾回收校验逻辑。
2. **快捷查询“重选设备”按钮不可用问题**：在 `http://192.168.56.1:5150/automation/tasks` 页面选择设备后，右上角弹窗中的“重选设备”按钮点击无响应，迫使必须刷新页面。根本原因是 `QuickQueryOverlay` 中点击“重选设备”触发的 `handleClearSelection` 回调在父组件 `AutomationExecuteTab` 中并未被正确解构和定义，导致向子组件传递了 `undefined`，按钮操作无实际功能。

## 解决方案

1. **后端凭据垃圾回收**：
   在 `backend/api/assets.py` 的 `_delete_linked_device` 级联删除工具函数中，添加类似 `/devices` 接口的 credential 垃圾回收代码：获取被删除设备的 `credential_id`，查询并确认无其他设备占用该凭据后，执行删除。
2. **前端重选设备状态清空**：
   * 在 React 快捷自动化 Hook `src/hooks/useAutomation.ts` 中新建 `handleClearSelection` 回调，同时清除 `selectedDevice` 和 `batchDeviceIds`。
   * 将该回调添加到 Context 并透传解构到 `AutomationExecuteTab` 以及 `QuickQueryOverlay`，使按钮能正确清空当前的设备选择状态并返回第一步。

## 验证计划

1. 确认 pytest 后端测试完美运行通过。
2. 验证前端“重选设备”按钮能立刻关闭弹窗并退回到首步选择界面。
3. 验证删除资产后，对应的 credentials 表项被自动连带清除。
