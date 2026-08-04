# TextFSM 功能开关与权限状态收口 Walkthrough

## 目标 / Goal

将 `PLATFORM_REGISTRY_ENABLED` 的后端能力状态明确返回给 TextFSM 注册表页面。开关关闭时，页面进入只读审查模式：SYSTEM 模板仍可执行不持久化的 Sandbox，租户模板写入、Fork、版本流转、样例持久化和历史回归均不可用。所有新增提示均通过页面已有的 `language` / `zh` 分支提供中英文文案。

Expose the backend TextFSM capability state to the registry page. When `PLATFORM_REGISTRY_ENABLED` is disabled, the page becomes read-only: SYSTEM templates retain non-persistent Sandbox testing, while tenant writes, forks, lifecycle transitions, sample persistence, and historical regression are unavailable. New messages use the existing `language` / `zh` branch for bilingual system-following text.

## 实施内容 / Implementation

- `GET /api/parser-templates/capabilities` requires `textfsm.view` and returns `write_enabled` plus `read_only_sandbox_enabled`.
- The frontend loads the capability state independently and fails closed if it cannot be read.
- A capability-read failure keeps all writes fail-closed while retaining the statically safe SYSTEM read-only Sandbox path.
- Write controls are hidden or disabled when the backend gate is closed; handlers also guard the same actions so alternate UI paths cannot bypass the gate.
- SYSTEM template content and field contract remain read-only; SYSTEM Sandbox is enabled only when the capability contract allows it.
- Added a bilingual read-only review banner and capability-loading/error states.

## 验证 / Verification

- `.venv/Scripts/python.exe -m pytest backend/tests/platform_registry/test_parser_templates.py -q -p no:cacheprovider` — 10 passed.
- `.venv/Scripts/python.exe -m pytest backend/tests/platform_registry -q -p no:cacheprovider` — 89 passed.
- `npm run lint` — passed (`tsc --noEmit`).
- `npm run build` — passed; Vite emitted only the existing large-chunk warning. Generated `dist/index.html` was restored because build output is not part of this change.
- 登录态浏览器复核已完成：中文和英文均显示只读审查提示，New/Fork/Save/Upload/Regression/生命周期写操作均隐藏或禁用；SYSTEM Huawei Eth-Trunk Sandbox 使用脱敏 fixture 返回 2 条记录，版本仍为 v1、样例仍为空。No write operation was performed.

## 回滚 / Rollback

If the rollout needs to be reverted, remove the capability route and the frontend capability guards together. The existing backend `_enabled()` write protection remains the final safety boundary.
