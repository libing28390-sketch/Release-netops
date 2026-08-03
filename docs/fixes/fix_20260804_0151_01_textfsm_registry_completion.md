# TextFSM 注册表页面功能闭环与默认 Sandbox 规则

## 问题现象

- 注册表页面只能展示基础编辑区，未覆盖新建、当前编辑内容测试、结构化结果、样例管理、生命周期回滚/废弃、影响分析、权限感知和分页筛选。
- 新建模板的默认规则使用了当前受限 TextFSM Sandbox 不接受的 `\\s` 形式，首次 Sandbox 返回 `TEMPLATE_NOT_MATCHED`。

## 根因

- API 只有版本创建和旧版本测试路径，缺少 DRAFT 更新、只读 Sandbox、审计/影响分析及生命周期补充接口。
- 前端没有把编辑器状态作为 Sandbox 内容，也没有渲染返回的 records/summary；新建状态和样例元数据未建模。
- 默认示例没有采用仓库已有 Sandbox 回归测试中的最小 TextFSM 规则。

## 解决方案

- 新增 `m0096_parser_registry_lifecycle`，并在服务层为创建、更新、测试、样例、发布、废弃、回滚写入审计事件。
- 增加分页/筛选、乐观锁 DRAFT 更新、编辑内容 Sandbox、SYSTEM/PUBLISHED 只读 Sandbox、样例删除、影响分析和审计 API。
- 完成注册表页面的新建、编辑、结构化结果、字段/源码 Diff、样例、生命周期、权限和列表交互。
- 将默认新建内容改为 `Value FIELD (.*)` 与 `^${FIELD} -> Record`，与 `test_textfsm_sandbox.py` 的已验证规则一致。
- 修复全量测试环境暴露的拓扑调用形状、Playbook 预览依赖标记和 Python 3.13 控制表上传测试事件循环兼容性。

## 验证命令与结果

- 隔离平台注册套件：**88 passed**。
- TextFSM parser：**9 passed**；迁移：**5 passed**；控制表上传：**19 passed**；拓扑/Playbook 兼容：**4 passed**。
- `python -m compileall -q backend`：通过。
- `npm run lint`：通过。
- `npm run build`：通过，仅保留既有 chunk size warning。
- `git diff --check`：通过。
- 登录态页面：SYSTEM 只读和 Fork 可见；新建状态显示保存草稿；最小未保存模板 Sandbox 显示 1 条记录、字段和耗时。

## 未验证项

- 完整共享 `pytest backend/tests -q` 仍受到全局 SQLite/平台 PostgreSQL 夹具相互污染影响，不能作为本轮全绿证据。
- 真实中兴、锐捷、迪普、迈普设备回显、真实 Playbook Apply/审批和 PostgreSQL fresh/upgrade 未在本机伪造或替代。

## 风险与回滚方式

- 迁移新增表只承载审计记录；回滚代码时保留迁移版本并回滚应用提交，避免删除历史审计数据。
- UI 新建和 Sandbox 默认不持久化；只有用户显式保存草稿或上传样例才写入租户数据。
- 若发现发布流程问题，可先关闭 `PLATFORM_REGISTRY_ENABLED`，再回退应用提交并保留数据库审计表。
