# EVAL-020 安全门禁 walkthrough

本轮按 `16-development-master-checklist.md` 的原始要求执行依赖、Secret、权限、日志和错误响应检查。

## 结果摘要

| 检查 | 结果 |
| --- | --- |
| Python/npm 依赖 | pip check 与 npm lock-only PASS |
| Secret | validator fail-closed PASS；415 个 AI/前端源文件扫描 0 个生产字面量 |
| 权限 | AI API 96/96 路由拥有 `require_ai_permission`，100% |
| 日志 | AI runtime 97 个文件静态检查 0 个原始敏感值输出 |
| 错误响应 | 稳定 code/message/request_id/details；0 个 AI 原始异常回显 |
| PostgreSQL/V1 | 10/10 baseline PASS；事务 rollback；SQLite 禁止 |
| 质量 | 4 个 EVAL wrapper、64 个安全回归、lint、build、py_compile、diff PASS |

## 本轮修复

- 模型路由和 Redis 限流日志不再插入异常原文，仅记录稳定异常类型。
- 知识目录和安全事件接口不再把 `ValueError` 原文作为 HTTP detail，改为稳定错误码和通用消息。
- 测试 Secret 治理说明改为 PostgreSQL-only 验收口径。

## 边界

探针不访问外部 Provider、不执行设备写命令、不写生产数据库；只通过 PostgreSQL 临时事务完成 V1 基线验证。非 AI 历史 API 的全仓库安全重构不属于 EVAL-020 的隐式范围。
