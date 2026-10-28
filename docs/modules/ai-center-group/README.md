# AI 中心模块说明

- 模块 ID：`ai-center-group`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：12
- 生产数据库：PostgreSQL

当前导航包括 Provider、模型与路由、健康与 SLA、Prompt、Copilot 对话、Agent 注册表、知识库管理、检索测试、产品目录、变更治理、Token 使用审计和 AI 安全网关。除 Copilot 对话外，导航配置中的这些入口要求 Administrator。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| Provider 供应商 | `/ai/providers` | — | — |
| Model & 路由 | `/ai/models` | — | — |
| 健康与 SLA | `/ai/health` | — | — |
| Prompt 提示词 | `/ai/prompts` | — | — |
| AI Copilot 对话 | `/ai/copilot` | — | — |
| Agent 注册表 | `/ai/agents` | — | — |
| 知识库管理 | `/ai/knowledge` | — | — |
| 检索测试 | `/ai/retrieval-test` | — | — |
| 产品目录 | `/ai/catalog` | — | — |
| AI 变更治理 | `/ai/governance` | — | — |
| Token 统计审计 | `/ai/usage` | — | — |
| AI 安全网关 | `/ai/security` | — | — |

## 相关代码

- 导航与菜单权限：`src/components/AppSidebar/navConfig.ts`
- 路由解析：`src/utils/routeContext.ts`
- 前端页面：`src/pages/ai`
- 后端 API 与服务：`backend/ai/api`、`backend/ai/services`、`backend/api/knowledge_*.py`
