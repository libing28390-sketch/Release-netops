# NetOps Workspace Rules

## 1. 计划与执行记录文档归档规范
*   **实施计划 (Implementation Plan)**：以后针对任务生成的任何实施计划，必须保存在工作区的 `docs/plans/` 目录下（若目录不存在则自动创建）。文件名必须根据具体任务的中文名称进行命名，格式为 `plan_[任务的中文汉字或拼音].md`（例如：`docs/plans/plan_多厂商诊断.md`）。
*   **执行结果与验证报告 (Walkthrough / Verification Report)**：针对任务生成的执行结果、验证报告及走查记录，必须保存在工作区的 `docs/walkthrough/` 目录下（若目录不存在则自动创建）。文件名必须根据具体任务的中文名称进行命名，格式为 `walkthrough_[任务的中文汉字或拼音].md`（例如：`docs/walkthrough/walkthrough_多厂商诊断.md`）。
*   **例外情况**：除了上述归档规范，严禁向版本控制中提交个人私有的 markdown 笔记或文章，避免污染公有仓库。

## 2. 数据库选用规范
*   **PostgreSQL 绑定**：本系统在生产和部署环境一律采用 **PostgreSQL** 作为核心关系数据库。在进行数据库设计、编写 SQL 语句以及事务加锁时，应严格遵循 PostgreSQL 标准与规范（例如使用 `FOR UPDATE` 进行行级锁定，避免采用特定于 SQLite 的独立机制）。
