# H3C Comware 路由查询解析失败修复

## 问题描述

H3C (Comware V7) 设备 AGG-SW1 (192.168.96.222) 在自动化任务执行 `display ip routing-table` 时报错：

```
Pattern not detected: '\[agg\-sw1\]' in output.
```

## 现状/问题分析

### 根因分析

1. **凭据优先级错误**：Playbook 引擎 `engine.py:L117` 硬编码凭据优先级为 `normal_username > username > admin_username`，导致使用低权限用户 `user` 连接设备
2. **低权限用户分页限制**：H3C Comware V7 低权限用户无法执行 `screen-length disable`（返回 `Permission denied.`），导致分页未禁用
3. **输出挂起超时**：`display ip routing-table` 输出在 `---- More ----` 处暂停，Netmiko 等待设备提示符 `<agg-sw1>` 但无法匹配到，最终超时

### 影响范围

- Playbook 执行引擎（所有使用低权限用户的 H3C 设备）
- 运行数据采集服务
- 巡检服务
- IP 定位服务

## 拟修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/drivers/ssh_compat.py` | 新增 `safe_send_command` 包装器 |
| `backend/services/operational_data_service.py` | 替换 `send_command` 为 `safe_send_command` |
| `backend/services/inspection_service.py` | 替换 `send_command` 为 `safe_send_command` |
| `backend/services/ip_locator_service.py` | 替换 `send_command` 为 `safe_send_command` |
| `backend/api/playbooks/engine.py` | 修复凭据优先级为 `auto` 模式 |

## 实施步骤

1. 在 `ssh_compat.py` 新增 `safe_send_command`：对 Comware 设备自动构造灵活的 `expect_string`，失败时回退到 `send_command_timing`
2. 在三个服务文件中替换所有 `client.send_command` 为 `safe_send_command`
3. 修复 `engine.py` 凭据解析优先级，改为 `username > admin_username > normal_username`
4. 验证凭据解析逻辑正确性

## 验证计划

- 脚本验证凭据解析：旧逻辑选 `user`，新逻辑选 `admin` ✅
- 重启后端后在 UI 重试 H3C 路由查询

## 风险与回滚

- 凭据优先级变更可能影响其他设备（低风险：`auto` 优先级与 `automation.py` 一致）
- `safe_send_command` 兜底逻辑使用 `send_command_timing`，对长输出命令可能存在时序风险（已设置 30s read_timeout）
- 回滚：还原 5 个文件的修改即可
