# TextFSM 注册表开发闭环 Walkthrough

## 用户可见变化

- `/automation/textfsm-registry` 支持新建租户模板、编辑 DRAFT、保存草稿和乐观锁冲突保护。
- Sandbox 运行编辑器当前内容，页面显示结构化记录、字段、记录数、字段覆盖/契约摘要和耗时；默认新建模板可直接用最小回显完成一次解析。
- SYSTEM 模板显示只读标识和 Fork 入口；不可原地保存或持久化测试结果。
- 样例支持名称、期望记录 JSON、加密列表和删除；模板列表支持搜索、来源/状态筛选和分页。
- 生命周期页面支持提交、审批、发布、废弃、回滚，并展示源码/字段 Diff、影响计数和审计历史。

## 后端实现

- `backend/database/migrations/m0096_parser_registry_lifecycle.py`：模板版本审计表和索引。
- `backend/services/parser_template_service.py`：分页、草稿更新、Sandbox、样例删除、影响分析、审计和生命周期操作。
- `backend/api/parser_templates.py`：新增 PUT、Sandbox、样例删除、impact/audit、deprecate/rollback 路由。
- `backend/core/rbac.py`：补充 `textfsm.deprecate` 与 Release Manager 映射。

## 前端实现

- `src/pages/ParserRegistryTab.tsx`：注册表工作台完整交互、权限感知控件和结构化结果展示。
- `src/components/AppMainContent.tsx`：把当前登录用户传入注册表页面。

## 验证记录

- `pytest --confcutdir=backend/tests/platform_registry backend/tests/platform_registry -q`：88 passed。
- TextFSM parser：9 passed；迁移：5 passed；控制表上传：19 passed；拓扑/Playbook 兼容：4 passed。
- `python -m compileall -q backend`、`npm run lint`、`npm run build`、`git diff --check` 通过。
- 登录态浏览器复核了 121 个模板列表、SYSTEM 只读、Fork 入口、新建状态和未保存最小模板 Sandbox（1 条结构化记录、字段 `field`、耗时可见）。

## 边界

真实厂商设备回显、在线识别、真实 Playbook Apply/审批及 PostgreSQL fresh/upgrade 仍需在对应环境补充证据；本次没有伪造这些结果。
