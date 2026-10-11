# RBAC 权限整改实施记录

## 目标与结论

依据 [RBAC 审核整改意见书](walkthrough_20261011_1330_01_RBAC审核整改意见.md)，把账号简化为管理员/普通用户，同时在服务端为高风险网络变更建立一致的主体、资源范围、审批内容、凭据权限和撤权校验。

本次修改强化了 RBAC 执行控制，但“是否满足完整标准”仍需区分模型实现与组织策略：角色层级、职责分离和租户/资源范围按项目业务语义实现；不能据此宣称通过 INCITS 359 的逐条认证评估。运行前还需对旧数据迁移和无法映射的任务做人工复核。

## 主要整改

### 1. 统一主体和资源授权语义

- 在 `backend/core/rbac.py` 集中资源/动作目录和默认拒绝语义；限制型资源范围的空集合按拒绝处理。
- 用户入口收敛为管理员与普通用户；普通用户兼容映射到变更申请者能力，管理端资源范围仍由服务端判定。
- 用户切换账号检查目标账号启用状态；非全局管理员不能切换到其他租户账号，避免借切换接口获取跨租户身份。
- 对租户缺失或不匹配的设备执行请求失败关闭；全局管理员例外保持显式。

### 2. 把审批绑定到不可变操作内容

- 新增 PostgreSQL 迁移 `m0281_rbac_execution_authorization.py`，为作业/脚本 owner 归属和执行授权保存可校验状态，并为配置审批 MFA 失败限制、TOTP 步骤消费建立持久化表。
- 迁移会将历史非管理员账号收敛为普通 Viewer / Change Requester，只授予本租户的工单申请范围；租户缺失时不授予资源范围。旧角色、资源 profile 和 scope 列表先快照到 `legacy_user_rbac_assignments` 供人工追溯。
- 运行时对 Viewer 与旧执行/管理员 profile 的组合失败关闭；旧 profile 不能单独恢复命令执行、发布或跨租户能力。
- 配置审批通知从服务端规范化 manifest 生成，并对命令、密钥字段脱敏；申请人自由填写说明与实际操作内容分开呈现。
- 审批 manifest 过大时拒绝请求；一次性 TOTP 步骤不能重放，失败计数按审批人共享并锁定。
- 无法通过精确用户名映射到旧任务所有者的记录不猜测租户、不自动授权：任务禁用并要求重新授权。

### 3. 限制变更工单、自动化作业和凭据使用

- 将动作权限、目标设备租户/范围、操作者与凭据角色校验用于即时 CLI、parsed-command、平台动作和已发布脚本执行路径。
- `enable_password` 仅在显式允许的管理员凭据角色下传递；租户管理员不能绕过全局管理员的跨租户边界。
- 配置变更工单执行继续绑定批准快照、窗口和实施者职责；执行回包及错误先脱敏，执行历史输出通过保护存储。
- 定时作业的规范化操作 manifest、owner、tenant、scope 和授权状态在 runner 执行时重新验证。普通租户用户的 `scope=all` 仍解析成其获准设备集合，不能升级为全局设备采集。
- Playbook 和 Alert Rule 的执行/发布授权在运行阶段重新检查；旧执行授权不因页面隐藏按钮或审批人仍在线而自动成立。

### 4. 前端权限呈现

- 用户管理界面显示管理员/普通用户的简化模型；资源范围与变更权限仍由服务端策略控制。
- 作业、告警规则、脚本和访问中心页面呈现与后端契约一致的授权/审批状态，不作为安全边界。

## 重要文件范围

- RBAC 与用户：`backend/core/rbac.py`、`backend/api/users.py`、`backend/api/access_scopes.py`、`backend/services/access_scope_service.py`。
- 执行链：`backend/api/automation.py`、`backend/api/devices.py`、`backend/api/change_orders/`、`backend/api/playbooks/`、`backend/api/scheduled_jobs.py`、`backend/services/config_approval_service.py`、`backend/services/platform_registry_service.py`、`backend/services/scheduler_service.py`。
- 存储与审计：`backend/database/migrations/m0281_rbac_execution_authorization.py`、`backend/services/audit_service.py`、`backend/services/operational_data_service.py`。
- 前端：`src/hooks/useAuth.ts`、`src/pages/UsersTab.tsx`、`src/pages/ScheduledJobs/index.tsx`、`src/pages/AlertRulesTab.tsx` 及相关授权页面。
- 回归：`backend/tests/security/test_rbac_execution_authorization.py`、`backend/tests/scheduled_jobs/test_nsot_scope_execution.py`。

## 验证

### 已完成

| 检查 | 结果 |
| --- | --- |
| RBAC、安全及计划作业针对性 PostgreSQL 测试 | 32 passed，153.70 秒；使用独立临时 PostgreSQL 测试源库并清理 |
| 扩展安全/平台/Playbook/计划作业/资产导入回归 | 首轮 133 passed、5 failed；失败均是测试夹具仍使用旧 `Operator` 类型或 tenantless 普通用户身份。更新夹具后，包含失败用例及新增迁移回归的 3 个文件复跑 16 passed |
| `npm run lint` | 通过，TypeScript 检查退出码 0 |
| Vite 独立生产构建 | 通过，4,320 modules transformed；输出位于临时 `.codex-build-validation-rbac-20261011/` |
| `python scripts/validate_postgresql_only.py` | 通过，0 violations |
| 修改后端文件 `py_compile` | 通过 |
| `git diff --check` | 通过；Git 仅提示部分工作区文件存在 LF/CRLF 转换提示 |
| 全量前端首轮结果 | 478 passed、6 failed（124 files）；5 项为已改为默认 10 条后的旧 20 条分页断言，另 1 项 Copilot 流式渲染在全量并行运行时超过 5 秒 |
| 前端针对性复跑 | Monitoring Reports、NSOT 列表和知识导入 3 个测试文件 11 passed；Copilot 流式测试单文件 7 passed |
| 全量前端复跑 | 124 files、484 passed，全部通过 |
| CI 失败后的定向 PostgreSQL 回归 | 129 passed；使用独立临时 PostgreSQL 源库，覆盖 catalog/knowledge、拓扑计划任务、NSOT 预览及 SNMP 测试夹具 |
| SQLite 残留清理 | UI/API 评估契约、gold-400 evaluator 校验、测试 mock、README 中的 SQLite 文案和 SQLite 假测试路径已移除；运行时代码要求 PostgreSQL `DATABASE_URL`，没有 `sqlite3` 驱动调用 |

### 尚未完成

- 对 `3eda175e` 的 GitHub Actions 后端全量门禁失败：61 failed、3089 passed、1 skipped。失败来自旧 `Operator` 测试主体和 tenantless 用户/设备/计划任务夹具与 RBAC tenant/snapshot 契约不匹配，以及一条 SNMP 诊断夹具缺少稳定用户 ID；不是 PostgreSQL 或 SQLite 运行时故障。`Knowledge Engine Promptfoo Gate` 对同一 SHA 成功。
- 已按失败证据修复受影响夹具，并以独立 PostgreSQL 源库运行 129 项定向回归通过；尚未在当前修复状态下完成后端全量 `pytest backend/tests -q`，也尚未产生第二次推送对应的 Actions 结果。
- 本地 `pytest -x` 曾在 168 passed 后发现 gold-400 evaluator 仍强制旧 `source_policy.sqlite=not_used`；清除 checker 中该字段后，`backend/tests/ai/test_eval_gold_400_check.py` 5 passed。未将被该首个失败中断的全量本地运行记作全量通过。

## 部署与发布注意事项

- 迁移面向 PostgreSQL；上线前应先备份并确认旧任务 owner 映射。迁移无法确认 owner 的记录会禁用并进入 `reauthorization_required`，需要管理员人工处理。
- 必须核验租户/范围策略配置与已有用户的业务映射，再允许其提交生产变更。角色名简化不应理解为普通用户自动获得执行权。
- `.github/workflows/release.yml` 对 `main` push 会在门禁通过后同步到独立公开 Release 仓库，并使用 force push 更新该仓库 `main`。用户已授权本次整改推送和 Actions 验收，因此按该授权继续；同步只会发生在门禁通过后。
- 当前 `main` 与 `origin/main` 均为首次 RBAC 提交 `3eda175e`；Actions 已报告后端门禁失败。后续修复、文档及 fix record 尚待暂存、提交和推送。

## 剩余工作

1. 在当前修复状态运行后端全量 PostgreSQL pytest、受影响前端测试及 PostgreSQL-only 检查。
2. 建立本轮 fix record，更新 plan/walkthrough，审核暂存文件仅含本次公开源代码、测试和正式文档。
3. 推送至 `main`，等待对应 Actions 全部成功，并核验 Release 仓库同步到同一发布 SHA；若失败则按日志继续修复与重推。
