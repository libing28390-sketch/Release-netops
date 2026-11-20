# 计划：TextFSM 发布版本关联 Playbook 用户手册

## 目标

将 TextFSM 注册模板、平台 Release 动作映射、设备 Profile 和受控 Playbook 的真实代码链路整理成可执行的中英文用户手册，明确最终绑定键、验证方法和权限边界，并补齐自定义模板替换时的 Profile/解析平台一致性。

## 范围

- TextFSM 模板创建/Fork、Sandbox、加密样例、回归和版本发布。
- `platform_release_actions.parser_template_version_id` 的绑定规则。
- 平台 Release 的 Validate/Submit/Approve/Publish 生命周期。
- Playbook 的 `action_code` 步骤、版本生命周期、Dry Run、执行审批和 Apply。
- Netmiko 平台键与当前平台注册表九个 SYSTEM 平台族的边界。
- 不在文档中保存账号、密码、Token 或回显密文。

## 执行记录

1. 已核对 `backend/api/parser_templates.py`、`backend/services/parser_template_service.py`：TextFSM 版本发布前必须通过 Sandbox，发布时会执行保留样例回归。
2. 已核对 `backend/api/platform_registry.py`、`backend/services/platform_registry_service.py`：Release Action 通过 `PUT /api/platform-registry/releases/{release_id}/actions/{action_code}` 写入命令、解析版本和字段契约；只有发布后的版本可绑定。
3. 已核对 `backend/api/playbooks/scenarios.py`、`backend/api/playbooks/engine.py`、`backend/services/playbook_version_service.py`：Playbook 受控步骤只引用 `action_code`；Dry Run 走 `preview_platform_action`，Apply 走 `execute_platform_action`。
4. 已核对 `src/pages/ParserRegistryTab.tsx`、`src/pages/PlatformRegistryTab.tsx`、`src/components/PlaybookVersionEditor.tsx`：TextFSM 新建/Fork 已选择目标 Profile；平台注册表动作编辑器已增加后端过滤的 `PUBLISHED` 解析版本选择器。
5. 已补齐 `GET /api/platform-registry/profiles/{profile_id}/parser-versions`，并让它与动作保存接口共用平台、租户和 Profile 作用域规则。
6. 已补齐同 Profile 内的 TextFSM 版本替换回归测试，并覆盖 H3C 等 `platform_code` 与 `parser_platform` 不同的厂商键。
7. 已生成并更新用户手册：`docs/modules/automation/features/textfsm-playbook/用户手册.md`。

## 交付判断

- 文档交付：完成。
- TextFSM → Release Action → Playbook 的代码链路：已核对并在手册中给出接口级操作。
- 当前 UI 已可完成“新模板/版本发布 → 选择 Profile → Draft Release 选择解析版本 → 发布 Release → Playbook Dry Run/Apply”的闭环；API 保留用于自动化和排查。
- 交付包含前后端实现与回归测试，未把任何真实设备凭据或原始回显写入文档。
