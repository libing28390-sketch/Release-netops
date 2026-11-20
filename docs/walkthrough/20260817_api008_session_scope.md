# 2026-08-17 API-008 会话与证据隔离

## 验证目标

验证 Copilot 的会话、消息、任务、Agent trace、工具调用、证据和诊断记录不能被其他租户或用户读取、修改或关联。

## 实现与验证

m0146 仅增加租户与 purpose-bound opaque user scope 列及索引，并为旧记录提供可重复回填。服务层在 conversation、task、feedback、Agent cancel/trace、diagnostic case/handoff/run 路径使用认证上下文过滤；trace 只返回有界元数据。PostgreSQL 临时 schema 探针验证 migration 幂等、跨用户拒绝、工具/证据隔离和事务回滚。

AI 回归 234/234、前端 21 files / 100 tests、lint/build、V1 PostgreSQL baseline 10/10 全部通过。未执行生产 migration 或写入生产数据。
