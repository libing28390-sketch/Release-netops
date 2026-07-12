# NetOps Workspace Rules

## 1. 计划与执行记录文档归档规范
*   **实施计划 (Implementation Plan)**：以后针对任务生成的任何实施计划，必须保存在工作区的 `docs/plans/` 目录下（若目录不存在则自动创建）。文件名必须根据具体任务的中文名称进行命名，格式为 `plan_[任务的中文汉字或拼音].md`（例如：`docs/plans/plan_多厂商诊断.md`）。
*   **执行结果与验证报告 (Walkthrough / Verification Report)**：针对任务生成的执行结果、验证报告及走查记录，必须保存在工作区的 `docs/walkthrough/` 目录下（若目录不存在则自动创建）。文件名必须根据具体任务的中文名称进行命名，格式为 `walkthrough_[任务的中文汉字或拼音].md`（例如：`docs/walkthrough/walkthrough_多厂商诊断.md`）。
*   **例外情况**：除了上述归档规范，严禁向版本控制中提交个人私有的 markdown 笔记或文章，避免污染公有仓库。

## 2. 数据库选用规范
*   **PostgreSQL 绑定**：本系统在生产和部署环境一律采用 **PostgreSQL** 作为核心关系数据库。在进行数据库设计、编写 SQL 语句以及事务加锁时，应严格遵循 PostgreSQL 标准与规范（例如使用 `FOR UPDATE` 进行行级锁定，避免采用特定于 SQLite 的独立机制）。

## 3. 项目 Skills 路由

项目级 skills 位于 `.agents/skills/`。任务匹配时优先使用以下最小集合：

- `netops-backend`：FastAPI、Service、鉴权、调度与后端接口。
- `netops-frontend`：React、TypeScript、页面、组件、hooks 与状态管理。
- `netops-network-drivers`：多厂商 SSH、SNMP、CLI 解析、拓扑和诊断。
- `netops-data-migrations`：PostgreSQL 表结构、迁移、索引、事务与回填。
- `netops-quality-gate`：pytest、TypeScript 检查、生产构建与回归验证。
- `netops-release`：Windows、Docker、Ubuntu、Nginx、CI 与发布打包。

跨层功能通常组合业务 skill 与 `netops-quality-gate`；只有实际涉及数据库持久化或发布配置时才追加对应 skill。

## 4. Agent 协作规则

角色说明位于 `.agents/roles/`：

- `coordinator.md`：拆解跨模块任务、分配边界并汇总结论。
- `backend-engineer.md`：后端 API、服务和数据库调用。
- `frontend-engineer.md`：前端页面、交互和 API 合约。
- `network-engineer.md`：设备接入、命令解析与多厂商适配。
- `quality-release-engineer.md`：测试、构建、迁移和发布验证。

仅当任务可以被清晰拆成彼此独立的子任务，或用户明确要求并行/多 Agent 时才启用多个 agents。每个 agent 必须先检查工作树，避免覆盖其他 agent 或用户的未提交修改；共享文件由 coordinator 统一协调。

## 5. 通用质量与安全约束

- 修改前追踪完整调用链，修改后运行与风险相称的最小测试集合。
- 不在日志、响应、测试夹具或文档中写入真实密码、密钥、Token、SNMP community。
- 网络设备配置变更、生产部署、推送和发布必须获得明确授权。
- 不修改与当前任务无关的用户未提交文件。
