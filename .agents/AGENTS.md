# NetOps Workspace Rules

## 1. 计划与执行记录文档归档规范
*   **实施计划 (Implementation Plan)**：以后针对任务生成的任何实施计划，必须保存在工作区的 `docs/plans/` 目录下（若目录不存在则自动创建）。文件名必须根据具体任务的英文名称进行命名，格式为 `plan_[task_name_in_snake_case].md`（例如：`docs/plans/plan_multi_vendor_diagnose.md`）。
*   **执行结果与验证报告 (Walkthrough / Verification Report)**：针对任务生成的执行结果、验证报告及走查记录，必须保存在工作区的 `docs/` 目录下。文件名必须根据具体任务的英文名称进行命名，格式为 `walkthrough_[task_name_in_snake_case].md`（例如：`docs/walkthrough_multi_vendor_diagnose.md`）。
*   **例外情况**：除了上述归档规范，严禁向版本控制中提交个人私有的 markdown 笔记或文章，避免污染公有仓库。
