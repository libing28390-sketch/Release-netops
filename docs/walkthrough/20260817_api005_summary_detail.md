# 2026-08-17 API-005 summary/detail boundary

## 验证目标

确认列表不会把正文、Chunk、日志、Trace、错误对象或内部存储引用带给前端；确认详情接口仍能按权限加载需要的正文与 Chunk。

## 结果

API-005 契约测试 4/4、API/CAT/KUI 回归 17/17 通过。PostgreSQL 临时事务探针验证了来源、来源版本、刷新观察和文档列表的摘要投影，以及独立文档详情的正文/Chunk 加载；事务已回滚。TypeScript lint、Vite build、Python compile 和 diff check 全部通过。
