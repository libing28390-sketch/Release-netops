# 快捷查询凭据角色自动选择修复完成记录

## 完成摘要

已修复自动化执行页快捷查询预设按钮强制使用普通账号 `normal` 的问题。现在快捷查询会传入 `auth_role: auto`，与后端运行数据采集接口、手动解析命令入口保持一致。

这可以解释用户截图中的差异：

- 操作工作台可以登录：该入口可能使用了可登录的主账号或 admin/特权账号。
- 图二快捷查询失败：快捷查询预设按钮此前强制 `normal`，如果设备普通账号不可 SSH 登录，就会被设备拒绝认证。

## 实际修改文件

- `src/pages/AutomationExecute/components/QuickQueryOverlay.tsx`
- `docs/plans/plan_快捷查询凭据角色自动选择修复.md`

## 关键实现说明

将快捷查询预设按钮调用：

```ts
onRunQuickQuery(..., 'normal')
```

调整为：

```ts
onRunQuickQuery(..., 'auto')
```

后端 `auto` 策略会按当前统一规则选择可用凭据：

1. 主凭据 `username/password`
2. 特权凭据 `admin_username/admin_password`
3. 普通凭据 `normal_username/normal_password`

## 验证命令与结果

### 搜索确认

```powershell
rg -n 'onRunQuickQuery' src backend
rg -n "auth_role: 'normal'" src backend
rg -n 'auth_role: "normal"' src backend
```

结果：

- 快捷查询入口已传 `auto`
- 未发现 `auth_role: 'normal'` 或 `auth_role: "normal"` 残留

### TypeScript 检查

```powershell
npm run lint
```

结果：通过。

### 差异检查

```powershell
git diff --check -- src/pages/AutomationExecute/components/QuickQueryOverlay.tsx docs/plans/plan_快捷查询凭据角色自动选择修复.md
```

结果：通过；仅出现 Git 的 LF/CRLF 工作区提示，不影响代码逻辑。

## 未执行验证及原因

- 未执行真实设备快捷查询：需要用户当前浏览器会话、目标设备和现场凭据配合。代码侧已完成参数链路修复。
- 未运行完整生产构建：本次为单行前端参数修复，已通过 TypeScript 检查。

## 剩余风险 / 后续建议

- 如果改为 `auto` 后仍失败，需要继续检查 Core-SW1 设备侧 AAA/VTY 配置，以及凭据中心中主账号/admin/normal 三组账号实际保存内容。
- 建议后续在快捷查询 UI 上显示当前使用的凭据角色或 `auto` 策略结果，便于运维人员判断到底用了哪一组账号。
