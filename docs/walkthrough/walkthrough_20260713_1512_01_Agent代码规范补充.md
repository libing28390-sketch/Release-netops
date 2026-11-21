# Agent 代码规范补充 Walkthrough

## 完成摘要

- 已检查 `.agents/` 目录：原有规则覆盖文档归档、数据库选型、skills 路由、Agent 协作和通用质量安全约束。
- 原规则缺少体系化代码规范，因此已在 `.agents/AGENTS.md` 新增“代码规范与实现标准”章节。
- 新增规范覆盖通用实现原则、后端、前端、数据库、网络设备适配、测试质量门禁和文档交付。

## 实际修改文件

- `.agents/AGENTS.md`
- `docs/plans/plan_Agent代码规范补充.md`
- `docs/walkthrough/walkthrough_Agent代码规范补充.md`

## 关键实现说明

- 通用原则强调根因优先、最小变更、分层清晰、显式契约、可回滚和可读命名。
- 后端规范明确 Router/Service 分层、Pydantic 契约、异常结构、日志脱敏和异步阻塞边界。
- 前端规范明确 React/TypeScript 分层、类型同步、状态覆盖、设计系统一致性和表单输入体验。
- 数据库规范强调 PostgreSQL 语义、批量事务原子性、迁移幂等和避免 SQLite 专属生产逻辑。
- 网络规范明确最小权限策略、多厂商适配边界、分页/超时/提示符处理和真实样本脱敏。

## 验证命令与结果

- `Select-String -Path .agents/AGENTS.md -Pattern "## 6\\. 代码规范|6\\.1|6\\.2|6\\.3|6\\.4|6\\.5|6\\.6|6\\.7" -Encoding UTF8`
- 结果：已确认新增章节 `## 6. 代码规范与实现标准` 及 `6.1` 至 `6.7` 小节存在。

## 未执行验证及原因

- 未运行 pytest 或 `npm run lint`；本次只修改 Agent 规则和 Markdown 文档，不涉及运行时代码。

## 剩余风险与后续建议

- 后续如果团队有更细的 Python/TypeScript formatter、lint 或 commit 规范，可继续补充到本章节或拆分为 `.agents/standards/` 子文档。
