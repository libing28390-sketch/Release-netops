# 验证报告与走查记录 - 凭据残留清理与快捷查询重选按钮修复

## 变更内容

1. **后端（Credentials Cleanup）**：
   修改了 [backend/api/assets.py](file:///d:/netops/netsops-main/backend/api/assets.py) 的 `_delete_linked_device` 函数。当用户执行删除资产时，系统不仅删除 `physical_assets` 和 `devices` 记录，还会自动回收清理已无其他设备引用的 `credentials` 表项，彻底解决凭据在凭据中心重复残留的问题。
2. **前端（Reselect Devices Button Fix）**：
   * 在 [src/hooks/useAutomation.ts](file:///d:/netops/netsops-main/src/hooks/useAutomation.ts) 中定义并导出了 `handleClearSelection` 来清空设备选中状态（`setSelectedDevice(null)` 和 `setBatchDeviceIds([])`）。
   * 在 [src/contexts/AutomationContext.tsx](file:///d:/netops/netsops-main/src/contexts/AutomationContext.tsx) 及相关 Provider 中传递该回调。
   * 在 [src/pages/AutomationExecute/index.tsx](file:///d:/netops/netsops-main/src/pages/AutomationExecute/index.tsx) 中解构，并成功绑定到快捷查询遮罩层 `QuickQueryOverlay` 的 “重选设备” 按钮上。

## 验证结果

### 后端单元测试
运行全部后端单元测试，所有 **353 个测试用例全部通过**。
```bash
================= 353 passed, 1 warning in 182.76s (0:03:02) ==================
```

### 交互与逻辑走查
1. **重选设备按钮功能**：
   当在 `/automation/tasks`（即快捷指令执行看板）选择了一台或多台设备，弹窗中右上角的 **“重选设备”** 按钮被点击时，`handleClearSelection` 正确触发，清除 `selectedDevice` 和 `batchDeviceIds` 状态，遮罩层弹窗平滑关闭，页面退回最初的设备选择阶段，不再发生锁死或需要刷新的问题。
2. **凭据残留自动清理**：
   手动录入一台物理资产并绑定凭据，随后点击资产“删除”按钮：后端日志与数据库均显示该物理资产、关联的网络设备以及其在 `credentials` 表中的专属凭据已经成功一次性级联清理，未在“凭据中心”留下多余的残留密码项。
