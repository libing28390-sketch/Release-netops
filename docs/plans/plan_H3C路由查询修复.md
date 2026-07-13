# H3C Comware 路由查询解析失败修复

## 问题描述

H3C (Comware V7) 设备 AGG-SW1 (192.168.96.222) 在自动化任务执行 `display ip routing-table` 时报错：

```
Pattern not detected: '\[agg\-sw1\]' in output.
```

## 现状/问题分析

### 根因分析

1. **凭据边界需要保留**：Playbook 引擎 `engine.py:L117` 当前优先使用 `normal_username > username > admin_username`，这符合“自动化查询默认普通账号、备份/变更显式提权”的最小权限策略，不应为本问题全局改成管理员优先
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
| `backend/drivers/ssh_compat.py` | 新增分页提示识别与 `drain_paged_output` |
| `backend/engine/drivers/netmiko_driver.py` | V3 Netmiko 命令执行后自动 drain 分页输出 |
| `backend/drivers/netmiko_driver.py` | 旧 Netmiko 驱动命令执行后自动 drain 分页输出 |
| `backend/tests/test_ssh_compat_paging.py` | 覆盖 H3C/通用 More 提示识别与翻页读取 |

## 实施步骤

1. 在 `ssh_compat.py` 新增 `contains_paging_prompt` 与 `drain_paged_output`，识别 `---- More ----`、`--More--` 等分页提示
2. 在两套 Netmiko 驱动命令执行路径中接入 `drain_paged_output`，遇到分页提示时发送空格继续读取
3. 保持 Playbook 默认普通账号策略不变；管理员账号仍用于备份、显式特权借用和配置变更类任务
4. 增加单元测试验证分页提示识别与连续翻页逻辑

## 验证计划

- 单元测试验证 H3C/通用分页提示识别与 drain 逻辑
- 单元测试验证两页分页输出会连续发送空格直到提示符返回
- 重启后端后在 UI 重试 H3C 路由查询

## 风险与回滚

- 不变更凭据优先级，避免自动化查询默认提权
- `drain_paged_output` 最多读取 200 页，避免异常设备无限分页
- 回滚：还原 `backend/drivers/ssh_compat.py`、两套 Netmiko 驱动和新增测试即可
