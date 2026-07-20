# 快捷查询凭据角色自动选择修复计划

## 任务目标

修复自动化执行页快捷查询入口强制使用普通账号 `normal` 导致设备可在操作工作台登录、但快捷查询/运行数据采集认证失败的问题。

## 现状 / 问题

- 后端运行数据采集接口已默认使用 `auth_role: auto`。
- `useAutomation.runQuickQuery()` 也默认使用 `authRole = 'auto'`。
- 但 `QuickQueryOverlay` 中点击预设查询按钮时显式传入 `'normal'`，覆盖了默认自动选择策略。
- 如果设备普通账号不可 SSH 登录，而特权账号/admin 可以登录，就会出现：
  - 操作工作台可以登录；
  - 快捷查询显示 `SSH 认证被拒绝`。

## 影响范围

- 前端快捷查询入口：`src/pages/AutomationExecute/components/QuickQueryOverlay.tsx`
- 不修改设备配置、不修改凭据、不改变后端 SSH 连接实现。

## 拟修改文件

- `src/pages/AutomationExecute/components/QuickQueryOverlay.tsx`
- `docs/walkthrough/walkthrough_快捷查询凭据角色自动选择修复.md`

## 实施步骤

1. 将快捷查询预设按钮传入的 `authRole` 从 `'normal'` 改为 `'auto'`。
2. 确认代码中没有其它快捷查询入口继续硬编码 `normal`。
3. 运行 TypeScript/构建相关验证。

## 验证计划

- `rg -n "onRunQuickQuery|auth_role: 'normal'|auth_role: \"normal\"" src backend`
- `npm run lint`
- 必要时执行 `npm run build`

## 风险与回滚思路

- 风险：某些只允许普通账号登录的设备会由 `auto` 优先尝试主账号/admin，再回落到 normal；这符合当前统一凭据策略。
- 回滚：将 `QuickQueryOverlay` 中的 `authRole` 参数恢复为 `'normal'`。
