# 自动化任务凭据与厂商平台回归修复计划

## 任务目标

按当前产品逻辑重新校准自动化、备份、操作工作台三类入口的凭据使用规则，并修复 H3C 平台被错误回退为 Cisco 命令的问题。

明确规则：

- 自动化任务：使用 normal 用户。
- 配置备份 / 配置快照：使用 admin 用户。
- 操作工作台 / PAM：由用户显式选择 normal 或 admin。

## 现状 / 问题

- 自动化页部分快捷查询曾被改为 `auth_role: auto`，不符合“自动化任务使用 normal 用户”的规则。
- Playbook 自动化执行曾被调整为 admin-first，也不符合“自动化任务使用 normal 用户”的规则。
- 配置备份逻辑当前使用 admin-first，符合规则，应保留。
- 操作工作台/PAM 当前支持 `access_level: normal | admin`，符合规则，应保留。
- H3C 设备如果数据库中平台值为裸 `h3c`，后端运行数据采集和 Netmiko driver 可能 fallback 到 Cisco，需要补齐平台别名。

## 影响范围

- 自动化任务页快捷查询、解析命令、`/api/execute`
- Playbook 自动化执行
- 配置备份 driver 平台映射
- H3C/Comware operational command catalog

## 拟修改文件

- `src/hooks/useAutomation.ts`
- `src/pages/AutomationExecute/components/QuickQueryOverlay.tsx`
- `backend/api/automation.py`
- `backend/api/playbooks/engine.py`
- `backend/services/operational_data_service.py`
- `backend/drivers/netmiko_driver.py`
- `backend/engine/drivers/netmiko_driver.py`
- `backend/tests/test_automation_credentials_and_platforms.py`

## 实施步骤

1. 自动化页快捷查询和解析命令统一传 `auth_role: normal`。
2. `/api/execute` 默认保持 `normal`，同时保留 `admin/auto` 兼容能力，供显式调用使用。
3. Playbook 自动化执行加载设备时使用统一凭据 resolver，但选择顺序改为 normal → 主账号 → admin。
4. 配置备份保持 admin → 主账号 的选择逻辑，不改为 normal。
5. 操作工作台/PAM 保持用户显式选择 `normal/admin`。
6. 补齐 H3C 平台别名，使 `h3c` 归一化为 `h3c_comware`，Netmiko 使用 `hp_comware`。
7. 用测试锁定：
   - 自动化默认 normal-first；
   - 显式 admin admin-first；
   - H3C 不再使用 Cisco 命令目录。

## 验证计划

- `rg` 搜索自动化页是否仍主动传 `auto`
- `python -m py_compile ...`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_automation_credentials_and_platforms.py -q`
- 相关后端回归测试
- `npm run lint`
- `git diff --check`

## 风险与回滚思路

- 风险：如果某些自动化任务确实需要 admin 权限，应通过明确入口或授权流程传 `auth_role=admin`，不能由默认逻辑隐式提升。
- 风险：H3C alias 扩大后，裸 `h3c` 会执行 Comware/H3C 命令，这是符合预期的修复。
- 回滚：恢复自动化页 auth_role、Playbook 凭据顺序和 H3C alias 变更即可。
