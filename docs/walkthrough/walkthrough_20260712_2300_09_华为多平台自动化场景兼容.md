# 华为多平台自动化场景兼容完成记录

## 完成摘要

已补齐华为多平台在自动化场景层面的兼容逻辑。

本次处理的重点不是连接 driver，而是 Playbook/自动化场景的平台匹配：

- 设备平台可以保留为 `huawei_vrpv8`、`ce`、`vrp`、`ne` 等变体；
- 自动化场景模板匹配时归一化为 `huawei_vrp`；
- 这样 VRP8/CE/NE 等华为设备可以复用现有 `huawei_vrp` 场景模板；
- 后续如有 VRP8 专属配置差异，可以再新增专属模板。

## 实际修改文件

- `src/pages/AutomationExecute/helpers.ts`
- `src/pages/AutomationExecute/index.tsx`
- `src/hooks/useAutomation.ts`
- `backend/api/playbooks/routes.py`
- `backend/tests/test_playbook_platform_aliases.py`
- `docs/plans/plan_华为多平台自动化场景兼容.md`

## 关键实现说明

### 1. 前端平台归一化

新增 `normalizeAutomationPlatform()`：

- `huawei` → `huawei_vrp`
- `huawei_vrpv8` → `huawei_vrp`
- `vrp` → `huawei_vrp`
- `ce` / `ce_vrp` / `ne` → `huawei_vrp`

同时也覆盖 Cisco/H3C/Juniper/Arista/Ruijie 的常见别名。

应用位置：

- 场景筛选：设备平台先归一化，再与 `supported_platforms` 匹配。
- 快捷 Playbook：自动识别设备平台时先归一化。

### 2. 后端 Playbook 平台归一化

新增 `_normalize_playbook_platform()`：

- `/api/playbooks/preview`
- `/api/playbooks/execute`

都会先将请求平台归一化，再查 `platform_phases`。

例如：

```text
requested_platform = huawei_vrpv8
execution platform = huawei_vrp
```

preview 响应中保留 `requested_platform`，便于排查。

## 验证命令与结果

### 语法检查

```powershell
python -m py_compile backend/api/playbooks/routes.py backend/tests/test_playbook_platform_aliases.py
```

结果：通过。

### 后端测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_playbook_platform_aliases.py backend\tests\test_automation_credentials_and_platforms.py -q
```

结果：`10 passed in 1.26s`

覆盖：

- 华为平台变体归一化；
- `huawei_vrpv8` 可以复用 `huawei_vrp` 的 preview 模板；
- 多厂商 alias 仍保持正确。

### 前端 TypeScript

```powershell
npm run lint
```

结果：通过。

## 未执行验证及原因

- 未连接真实华为 VRP5/VRP8/CE/NE 设备执行任务：需要现场设备与凭据配合。
- 本次只解决自动化场景平台匹配，不新增 VRP8 专属配置模板。

## 后续建议

- 若后续确认某些 VRP8/CE/NE 配置类命令与 `huawei_vrp` 模板存在差异，应新增专属平台模板，例如：
  - `huawei_vrpv8`
  - `huawei_ce`
  - `huawei_ne`
- 查询类命令可以继续复用 `huawei_vrp` 命令族。
