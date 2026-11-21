# RBAC 门禁测试夹具与 PostgreSQL-only 清理

## 问题

首次推送的 RBAC 执行授权整改提交 `3eda175e` 触发 GitHub Actions 后端全量门禁失败：61 failed、3089 passed、1 skipped。失败集中在 catalog/knowledge 测试仍使用无租户 `Operator` 身份、跨租户用户仅在内存对象上设置租户、SNMP 诊断用户缺少稳定 ID，以及 NSOT 计划任务测试没有按当前授权快照契约建档。`Knowledge Engine Promptfoo Gate` 对该提交成功。

同时，评估页面/API 契约、README 和 MIB 导入测试仍展示或暗示 SQLite 使用，与项目 PostgreSQL-only 运行约束不一致。

## 修改

- 测试用户工厂支持把 `tenant_id` 写入 PostgreSQL `users` 行；受影响的 catalog/knowledge 服务测试改用明确的租户管理员身份，Viewer 拒绝用例保留 Viewer 身份。
- SNMP API 测试主体补充稳定用户 ID；NSOT 计划任务与设备夹具补齐 tenant、owner 和授权 manifest；预览任务补齐租户。
- PostgreSQL-only 收敛：启动配置明确要求 PostgreSQL，schema migration plan 拒绝非 PostgreSQL 模式；移除向量能力检查中的 SQLite 游标分支。
- 移除 gold-400 evaluator、知识评估 API 契约中的无用 SQLite source-policy 字段和 UI 提示，更新对应 TypeScript 类型、fixture、README 与 Vite watcher 注释；MIB 导入测试改用 PostgreSQL 测试键。`.sqlite` 文件后缀仍保留在非 MIB 文件过滤名单中，它只是拒绝导入非 MIB 文件，不代表数据库支持。
- 记录 CI 根因、测试状态、Release 工作流授权和后续门禁验收要求。

## 验证

- 独立临时 PostgreSQL 定向后端回归：129 passed。
- 知识评估前端相关测试：2 files、5 passed。
- `npm run lint`：通过。
- `scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过。
- 本地后端全量 `pytest -x` 在 168 passed 后定位到 evaluator 仍要求 SQLite 标记；删除该残留契约后，`backend/tests/ai/test_eval_gold_400_check.py` 为 5 passed。全量本地套件被该首个失败中断，不能记作全量通过。
- 当前修复提交对应的 GitHub Actions 尚未触发，须以推送后的全量工作流结果为最终门禁。

## 回滚

如需撤销本次夹具和 SQLite 展示清理，在对应提交上使用 `git revert <commit_sha>`，再重新运行 PostgreSQL-only 检查和 CI。此次修复不包含 RBAC schema migration；不要为回滚测试夹具而直接回退已应用的数据库 schema。
