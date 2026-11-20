# 自动化任务凭据与厂商平台回归修复完成记录

## 完成摘要

已按用户确认的产品逻辑重新校准当前代码：

- 自动化任务：使用 normal 用户。
- 配置备份 / 配置快照：使用 admin 用户。
- 操作工作台 / PAM：由用户显式选择 normal 或 admin。

同时保留后端对 `auth_role=auto` 的兼容能力，但自动化任务页不再主动使用 `auto`。

## 当前逻辑核对

### 1. 自动化任务

涉及：

- `src/hooks/useAutomation.ts`
- `src/pages/AutomationExecute/components/QuickQueryOverlay.tsx`
- `backend/api/automation.py`
- `backend/api/playbooks/engine.py`

结果：

- 快捷查询预设按钮传 `normal`。
- 解析命令传 `normal`。
- `runQuickQuery()` 默认值为 `normal`。
- `/api/execute` 默认值为 `normal`。
- Playbook 自动化执行选择顺序为 normal → 主账号 → admin。

### 2. 配置备份 / 配置快照

涉及：

- `backend/api/configs.py`
- `src/hooks/useConfigSnapshots.ts`

结果：

- 定时/手动配置备份使用 admin → 主账号。
- 配置快照相关执行显式传 `auth_role: admin`。

### 3. 操作工作台 / PAM

涉及：

- `backend/api/pam.py`
- `backend/api/system.py`
- `src/pages/AssetManagement/index.tsx`

结果：

- 前端维护 `terminalAccessLevel: normal | admin`。
- 后端按 `access_level` 解析对应账号。
- admin 入口需要额外审批/授权流程。

## H3C 平台修复

已补齐 `h3c` alias：

- `backend/services/operational_data_service.py`
- `backend/drivers/netmiko_driver.py`
- `backend/engine/drivers/netmiko_driver.py`

现在：

- `platform=h3c` → `h3c_comware`
- Netmiko device type → `hp_comware`
- operational commands → `display ...`

## 实际修改文件

- `src/hooks/useAutomation.ts`
- `src/pages/AutomationExecute/components/QuickQueryOverlay.tsx`
- `backend/api/automation.py`
- `backend/api/playbooks/engine.py`
- `backend/services/operational_data_service.py`
- `backend/drivers/netmiko_driver.py`
- `backend/engine/drivers/netmiko_driver.py`
- `backend/tests/test_automation_credentials_and_platforms.py`
- `docs/plans/plan_自动化任务凭据与厂商平台回归修复.md`

## 验证命令与结果

### 搜索确认

```powershell
rg -n "auth_role: 'auto'|authRole: string = 'auto'|onRunQuickQuery[^\n]+auto|auth_role: 'normal'|authRole: string = 'normal'" src/hooks/useAutomation.ts src/pages/AutomationExecute src/hooks/useConfigSnapshots.ts backend/api backend/services
```

结果：

- 自动化页主动传 `auth_role: normal`
- 自动化页默认 `authRole = 'normal'`

### 语法检查

```powershell
python -m py_compile backend/api/automation.py backend/api/playbooks/engine.py backend/tests/test_automation_credentials_and_platforms.py
```

结果：通过。

### 单元测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_automation_credentials_and_platforms.py -q
```

结果：`6 passed in 0.87s`

覆盖：

- `auth_role=auto` 兼容选择成对凭据；
- 自动化默认 normal-first；
- 显式 admin admin-first；
- H3C 使用 Comware `display ...` 命令；
- 两个 Netmiko driver 均将 `h3c` 映射为 `hp_comware`。

### 前端 TypeScript

```powershell
npm run lint
```

结果：通过。

## 未执行验证及原因

- 未直接登录真实设备执行自动化任务/备份：需要现场设备与当前凭据配合。
- 未运行完整生产构建：本次为逻辑校准和后端测试补充，前端已通过 TypeScript 检查。

## 后续建议

- 刷新自动化任务页后重新测试：
  1. 自动化任务应使用 normal 用户。
  2. H3C 设备应执行 `display ...` 命令。
  3. 配置备份仍应使用 admin 用户。
  4. 操作工作台应继续按选择的 normal/admin 登录。
- 如果 normal 用户无法执行某些查询命令，应优先检查设备侧 normal 用户权限，而不是让自动化默认提升到 admin。
