# Huawei VRP5 命令契约收口 Walkthrough

## 完成摘要

完成最新 2026-08-04 审查清单的 P0-1 代码收口：将 Huawei VRP5 `get_link_aggregation` 的旧兼容目录与平台注册正式契约统一为 `display eth-trunk`，保留 `dis eth-trunk` 历史回显解析兼容。P0-1 的本地代码/测试门禁已通过；真实 VRP5 设备执行和独立 PostgreSQL fresh/upgrade 仍未宣称完成。

## 实际修改文件

- `backend/services/operational_data_service.py`
- `backend/tests/vendor_audit/test_huawei_vrp5_cli_output.py`
- `docs/plan/20260804_自定义平台_TextFSM_Playbook审查后任务清单.md`

## 关键实现说明

- 旧 `COMMAND_CATALOG['huawei_vrp']['eth_trunk']` 从 `dis eth-trunk` 改为 `display eth-trunk`。
- 注释明确：标准发送命令跟随已发布 Platform Registry；历史缩写只作为解析输入兼容，不作为新任务发送命令。
- 厂商回归断言改为正式标准命令；原有 `dis eth-trunk` 输出解析用例未删除。
- 未新增或修改数据库迁移；现有 m0094 继续负责已发布 SYSTEM Release 的命令和 checksum 修复。

## 验证命令与结果

```text
pytest backend/tests/vendor_audit/test_huawei_vrp5_cli_output.py -q -p no:cacheprovider
15 passed in 2.27s

pytest backend/tests/platform_registry/test_platform_registry.py backend/tests/platform_registry/test_huawei_command_migration.py -q -p no:cacheprovider
11 passed in 30.81s

pytest backend/tests/vendor_audit -q -p no:cacheprovider
285 passed in 20.87s

npm run lint
tsc --noEmit 通过

git diff --check
通过（仅有工作树 LF/CRLF 提示）
```

## 未执行验证及原因

- 未连接真实 Huawei VRP5 设备；本次没有设备变更授权，且现有回显均为脱敏 fixture。
- 未执行 PostgreSQL fresh/upgrade 验收；该项属于后续独立数据库门禁。
- 未执行完整 `pytest backend/tests -q` 和 production build；当前步骤只涉及后端命令目录和厂商回归，完整门禁留待 P0-2 收口后统一执行。

## 剩余风险/后续建议

- 需在真实 VRP5 设备确认 `display eth-trunk` 的可执行性，尤其是不同 VRP5 版本差异。
- 需完成 P0-2：TextFSM 页面根据能力状态和资源权限隐藏/禁用写入操作，并保持中英文随系统语言。
- 需完成 PostgreSQL fresh/upgrade、完整后端测试、页面写流程和真实设备验收后，才能关闭整份任务清单。

