# 华为多平台自动化场景兼容计划

## 任务目标

修复华为多平台场景下自动化任务平台匹配不完整的问题。重点解决 `huawei_vrpv8`、`vrp`、`ce`、`ne` 等平台变体无法复用 `huawei_vrp` 自动化场景模板的问题。

## 现状 / 问题

- 当前 operational/driver 层已能将华为变体连接到 Huawei Netmiko driver。
- 但 Playbook 自动化场景的 `supported_platforms` 和 `platform_phases` 多数只包含 `huawei_vrp`。
- 前端场景筛选和后端 preview/execute 目前使用平台字符串精确匹配。
- 因此设备平台为 `huawei_vrpv8`、`ce`、`vrp` 等时，可能被判断为“不支持该场景”。

## 影响范围

- 自动化场景筛选
- 快捷 Playbook 平台自动识别
- `/api/playbooks/preview`
- `/api/playbooks/execute`

## 拟修改文件

- `src/pages/AutomationExecute/helpers.ts`
- `src/pages/AutomationExecute/index.tsx`
- `src/hooks/useAutomation.ts`
- `backend/api/playbooks/routes.py`
- `backend/tests/test_playbook_platform_aliases.py`
- `docs/walkthrough/walkthrough_华为多平台自动化场景兼容.md`

## 实施步骤

1. 前端新增 `normalizeAutomationPlatform()`，将华为平台变体归一到 `huawei_vrp`。
2. 自动化场景筛选时使用归一化平台匹配。
3. 快捷 Playbook 自动检测平台时使用归一化平台。
4. 后端 preview/execute 使用 `_normalize_playbook_platform()` 查找 `platform_phases`。
5. 保留原始设备平台给 driver/连接层，不把设备本身改写为 `huawei_vrp`。
6. 新增测试覆盖 `huawei_vrpv8/vrp/ce/ne` 能匹配 `huawei_vrp` 场景。

## 验证计划

- `python -m py_compile backend/api/playbooks/routes.py backend/tests/test_playbook_platform_aliases.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_playbook_platform_aliases.py -q`
- `npm run lint`
- `git diff --check`

## 风险与回滚思路

- 风险：华为不同平台在基础查询命令上大体一致，但配置类模板仍可能存在 VRP5/VRP8 差异；本次只解决平台匹配与模板复用，不新增专属配置模板。
- 回滚：移除前后端平台归一化 helper 和对应测试即可。
