# TextFSM 注册表开发闭环收口计划

## 目标

完成 `docs/plan/20260802_自定义平台_TextFSM_Playbook权限开放任务清单.md` 中本轮 TextFSM 注册表页面复核发现的阻断项：在线编辑、当前内容 Sandbox、结构化结果、样例管理、受控发布、影响分析、审计、权限感知 UI、筛选分页和可复现门禁。

## 范围与约束

- 保持 SYSTEM 模板只读；租户模板按 tenant scope 访问。
- Sandbox 使用短生命周期受限进程；不读取文件路径或网络资源。
- 草稿更新使用 `lock_version` 乐观锁；已发布版本只能生成新草稿。
- 样例输出只通过现有加密链路持久化；本地浏览器复核不写入真实样例或发布数据。
- 不伪造真实厂商设备、生产审批或 fresh/upgrade PostgreSQL 证据。

## 实施步骤

1. 新增模板生命周期审计迁移，并把迁移接入 PostgreSQL/隔离测试夹具。
2. 扩展 parser template service/API：分页筛选、草稿更新、编辑内容 Sandbox、样例删除、影响分析、审计、废弃和回滚。
3. 增加 `deprecate` 资源动作及 Release Manager 权限映射。
4. 重写注册表页面交互：新建、草稿编辑、字段契约、结构化结果、差异、样例、生命周期、影响分析、审计、筛选分页和权限控制。
5. 为默认新建模板和关键服务行为添加回归测试；修复受影响的拓扑/Playbook/控制表测试兼容性。
6. 运行编译、隔离平台测试、相关回归、TypeScript 检查、生产构建和浏览器关键交互复核。
7. 更新任务清单、walkthrough 和本次修复记录，随后提交并推送。

## 验收标准

- 隔离平台注册套件通过；TextFSM parser、迁移、控制表、拓扑/Playbook 兼容测试有明确结果。
- `compileall`、`npm run lint`、`npm run build`、`git diff --check` 通过。
- 登录态页面可进入新建状态；未保存最小模板可 Sandbox 并显示结构化记录/字段/耗时；SYSTEM 页面显示只读与 Fork；筛选、分页、影响分析和审计可见。
- 清单不把真实厂商或外部数据库证据误标为完成。
