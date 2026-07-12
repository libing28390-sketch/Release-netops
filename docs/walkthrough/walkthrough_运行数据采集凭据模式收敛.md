# 运行数据采集凭据模式收敛完成记录

## 完成摘要

修复运行数据采集与自定义解析命令默认使用普通账号的问题，统一收敛为 `auto` 凭据模式。

用户反馈 ACC-SW2 今日修改前可以连接，但当前 `/api/devices/{id}/operational-data` 报 `Error reading SSH protocol banner`。排查发现连接测试接口与运行数据采集接口是两条不同链路：连接测试已修复加密凭据解析，但运行数据采集仍默认 `auth_role='normal'`。

本轮将运行数据采集默认切换为 `auto`：优先使用凭据中心主账号，其次管理员账号，最后普通账号，并保证用户名和密码成对选择，避免交叉搭配。

## 实际修改文件

1. `backend/services/operational_data_service.py`
   - 默认 `auth_role` 从 `normal` 改为 `auto`。
   - 新增 `_first_complete_pair`，保证用户名和密码来自同一组凭据。
   - `auto` 模式优先使用：
     1. `credentials.username` + `credentials.encrypted_password` 解密结果
     2. `admin_username` + `admin_password`
     3. `normal_username` + `normal_password`

2. `backend/api/devices.py`
   - `/operational-data` 默认 `auth_role` 改为 `auto`。
   - `/parsed-command` 默认 `auth_role` 改为 `auto`。
   - 移除 API 层提前手动解密旧字段的逻辑，统一交给 `resolve_device_credentials`。

3. `src/hooks/useAutomation.ts`
   - 快速查询默认 `authRole` 改为 `auto`。
   - 自定义解析命令不再硬编码 `normal`。

4. `src/hooks/useDeviceDetail.ts`
   - 设备详情页运行数据采集显式传 `auth_role: auto`。

5. `docs/plans/plan_运行数据采集凭据模式收敛.md`
   - 记录实施计划。

## 关键实现说明

### 为什么不是继续默认 normal

运行数据采集会执行 `show ip interface brief`、`show lldp neighbors detail`、`show arp`、`show mac address-table` 等命令。很多网络设备上，普通账号可能无法执行完整 show/display 命令，或者登录权限/AAA 受限。

因此默认使用 `normal` 不适合作为企业级网络采集默认策略。

### 为什么使用 auto

`auto` 的目标是兼容历史数据和凭据中心：

```text
主凭据 -> 管理员凭据 -> 普通凭据
```

这样可以最大程度恢复此前“主账号/admin 能连通”的行为，同时保留显式传 `normal` 或 `admin` 的能力。

## 验证命令与结果

### 后端语法检查

```powershell
python -m py_compile backend\api\devices.py backend\services\operational_data_service.py
```

结果：通过。

### 前端 TypeScript 检查

```powershell
npm run lint
```

结果：通过。

### Diff 空白检查

```powershell
git diff --check
```

结果：通过，仅出现 Windows 换行提示。

## 剩余风险

1. 如果 ACC-SW2 仍然返回 `Error reading SSH protocol banner`，则说明设备或中间网络仍然在 TCP 建立后没有返回 SSH banner。
2. 如果错误变成 `Authentication failed`，说明 SSH banner 和协议协商已恢复，下一步应检查账号密码、AAA 或 enable secret。
3. 如果只有运行数据采集失败而连接测试成功，需要继续看具体 command 的权限和设备返回。

## 建议下一步

1. 重启后端与前端开发服务，让后端和前端默认参数同时生效。
2. 重新测试 ACC-SW2 的：
   - SSH 校验
   - 运行数据采集
   - 快速查询
3. 如果仍是 banner 失败，优先检查设备 VTY/SSH 服务状态、ACL、AAA、会话占用和中间安全策略。
