# 2026-08-17 API-009 任务执行保护

## 验证目标

验证 Copilot 任务支持取消、超时、步骤上限、工具调用上限，并且多个 worker 或 stale worker 不能重复 claim 或覆盖终态。

## 实现与验证

m0147 为 `ai_tasks` 增加执行计数、执行 token、版本号和时间字段。服务层以 PostgreSQL 条件 UPDATE 实现 claim、budget consume、cancel/reconcile、complete/fail；状态只能沿契约允许的路径变化，取消在与超时竞态时优先。临时 PostgreSQL schema 探针覆盖 queued/running timeout、幂等取消、单次完成/失败、跨用户拒绝和双次 migration。

AI 回归 234/234、TypeScript lint、Vite build 和 Python compile 全部通过。未执行生产 migration 或写入生产数据。
