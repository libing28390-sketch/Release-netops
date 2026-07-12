# 运行数据采集凭据模式收敛实施计划

## 任务目标

修复 `/api/devices/{device_id}/operational-data` 和 `/api/devices/{device_id}/parsed-command` 仍默认使用普通账号导致采集失败的问题，让运行数据采集默认使用与凭据中心主账号/管理员账号一致的 `auto` 模式。

## 现状问题

用户反馈 ACC-SW2 在今日修改前可以连接，但现在运行数据采集报：

```text
Error reading SSH protocol banner
POST /api/devices/{id}/operational-data 500
```

排查发现：

1. `/api/devices/connect` 与 `/api/devices/{id}/operational-data` 是两条不同路径。
2. 连接测试路径已修复加密凭据解析。
3. 运行数据采集路径仍默认 `auth_role='normal'`。
4. 前端快速查询也默认传 `auth_role: normal`。
5. 对 Cisco/Huawei/H3C 等网络设备，运行数据采集通常需要管理员或特权账号，普通账号不一定能执行 show/display 命令。

## 影响范围

- `backend/api/devices.py`
- `backend/services/operational_data_service.py`
- `src/hooks/useAutomation.ts`
- `src/hooks/useDeviceDetail.ts`
- `docs/walkthrough/walkthrough_运行数据采集凭据模式收敛.md`

## 拟修改文件

1. `backend/services/operational_data_service.py`
   - 将默认 `auth_role` 从 `normal` 改为 `auto`。
   - `auto` 模式优先使用凭据中心主账号，其次管理员账号，最后普通账号。
   - 避免用户名来自普通账号、密码来自主凭据的交叉搭配。

2. `backend/api/devices.py`
   - operational-data / parsed-command 默认 `auth_role` 改为 `auto`。
   - 不再提前手动解密旧字段，交给统一 `resolve_device_credentials`。

3. `src/hooks/useAutomation.ts`
   - 快速查询默认 `authRole` 改为 `auto`。
   - parsed-command 不再硬编码 `normal`。

4. `src/hooks/useDeviceDetail.ts`
   - 设备详情运行数据采集请求显式传 `auth_role: auto`。

## 实施步骤

1. 调整后端账号选择策略。
2. 调整 API 默认值。
3. 调整前端默认请求参数。
4. 运行后端语法检查。
5. 运行前端 TypeScript 检查。
6. 运行 diff 空白检查。

## 验证计划

1. `python -m py_compile backend/api/devices.py backend/services/operational_data_service.py`
2. `npm run lint`
3. `git diff --check`

## 风险与回滚思路

- 风险：部分只允许普通账号执行 show 命令的设备可能需要显式选择 normal。
- 回滚：将默认 `auth_role` 恢复为 `normal`。
- 兼容：前端或 API 仍可显式传 `normal` 或 `admin`，不会破坏已有调用。
