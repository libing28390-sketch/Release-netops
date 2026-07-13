# H3C Comware 路由查询解析失败修复 Walkthrough

## 完成摘要

- 保留自动化查询默认使用普通账号的最小权限策略，未将 Playbook 全局改为管理员账号优先。
- 在 SSH 兼容层新增通用分页提示识别与分页 drain 逻辑，覆盖 H3C `---- More ----` 以及常见 `--More--` 提示。
- 在两套 Netmiko 命令执行路径中接入分页 drain，避免普通账号无法关闭分页时长输出命令挂起。

## 实际修改文件

- `backend/drivers/ssh_compat.py`
- `backend/engine/drivers/netmiko_driver.py`
- `backend/drivers/netmiko_driver.py`
- `backend/tests/test_ssh_compat_paging.py`
- `docs/plans/plan_H3C路由查询修复.md`

## 关键实现说明

- `contains_paging_prompt` 统一识别厂商分页提示。
- `drain_paged_output` 在发现分页提示后向设备发送空格并继续读取，直到最新输出不再包含分页提示或达到页数上限。
- V3 `backend/engine/drivers/netmiko_driver.py` 与旧版 `backend/drivers/netmiko_driver.py` 都在命令输出返回前调用分页 drain，保证 Playbook 和旧调用链都受益。
- 凭据优先级不变：自动化查询默认普通账号；备份、配置保存、回滚、变更和显式特权借用继续使用管理员账号或 enable/admin 凭据。

## 验证命令与结果

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_ssh_compat_paging.py backend/tests/test_racks_new_fields.py -q`
- 结果：`8 passed in 4.63s`
- `npm run lint`
- 结果：通过，`tsc --noEmit` 退出码 `0`

## 未执行验证及原因

- 未连接真实 H3C 设备验证；当前环境没有生产设备交互授权与现场 SSH 会话。

## 剩余风险与建议

- 如果设备分页提示格式不在当前正则集合内，仍可能需要追加匹配样式。
- 建议后续在真实 H3C Comware V7 上重试 `display ip routing-table`，确认 UI 输出完整返回。
