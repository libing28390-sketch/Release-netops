# Walkthrough：TextFSM → Platform Release → Playbook

## 用户要完成的事情

用户创建一个 TextFSM 模板并发布后，希望 Playbook 执行某个逻辑动作时使用该模板解析设备回显。

## 最短可验证路径

```text
1. Template Registry：创建/ Fork 模板
2. Sandbox：fixture 解析通过并保存加密样例
3. TextFSM lifecycle：Submit → Approve → Publish
4. Platform Registry：在 DRAFT Release 的 action mapping 中绑定
   parser_template_version_id
5. Release lifecycle：Validate → Submit → Approve → Publish
6. Controlled Playbook：只写 action_code
7. Dry Run：检查 action_code、command、release_checksum、parser version id
8. Apply：检查 records 和 parser version id
```

## 关键代码证据

### TextFSM 发布

- `backend/services/parser_template_service.py`：`_transition_version` 要求发布前 `test_summary.passed == true`，并执行历史样例回归。
- `backend/api/parser_templates.py`：提供 `/sandbox-test`、版本生命周期、`/samples` 和 `/regression-test` 接口。

### 真实绑定点

- `backend/services/platform_registry_service.py`：`update_release_action` 将 `command`、`parser_template_version_id`、`field_contract_json` 写入 `platform_release_actions`；`list_compatible_parser_versions` 提供同一套可选版本过滤。
- 两个服务函数都拒绝非 `PUBLISHED` 解析版本，并校验模板 `platform_code` 与 Profile 的 `parser_platform`、租户和 Profile 作用域。

### Playbook 执行

- `backend/api/playbooks/scenarios.py`：`validate_controlled_phases` 拒绝裸字符串命令，只接受 `action`、`branch`、`notification`、`approval` 等受控步骤。
- `backend/api/playbooks/engine.py`：`_execute_registry_actions` 在 Dry Run 调用 `preview_platform_action`，真实执行调用 `execute_platform_action`。
- `backend/services/platform_registry_service.py`：真实执行后使用绑定的 TextFSM 版本解析、规范化记录、校验字段契约，并返回 `parser_template_version_id` 和 `records`。

## 当前产品边界

Playbook 版本不直接保存 TextFSM 版本 ID；它保存 `action_code`。因此必须先发布平台 Release，再让设备通过 Profile 使用该 Release。平台注册表动作编辑器现在可以从后端过滤的候选集中选择/替换解析版本；API 仍可用于自动化绑定和故障排查。

## 安全边界

- 仅使用脱敏 fixture 和加密样例。
- 不在文档、截图或脚本中写入账号密码、Token、Cookie 或原始设备回显。
- 生产 Apply 前先单台设备 Dry Run/测试设备验证。
