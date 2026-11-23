# 实施计划：Copilot 会话导出（Markdown 与 JSON）

- 创建时间：2026-11-23 09:50
- 目标仓库：`D:\netops\netsops-main`

## 1. 任务目标
在 Copilot 会话顶部栏增加轻量、简洁的 **导出** 下拉菜单，支持将当前会话一键导出为 **Markdown (`.md`)** 或 **JSON (`.json`)** 文件。

## 2. 现状与问题
- 当前 Copilot 仅支持单条消息复制，不支持将完整多轮会话导出为本地文件归档或流转。

## 3. 影响范围与拟修改文件
- 新增：`src/pages/ai/Copilot/exportUtils.ts`（纯函数：会话转 Markdown、会话转 JSON、安全文件名生成、触发浏览器下载）。
- 新增：`src/pages/ai/Copilot/exportUtils.test.ts`（单元测试：覆盖 Markdown/JSON 格式化、文件名清洗、空消息/引用/Token 统计）。
- 修改：`src/pages/ai/Copilot/CopilotHeader.tsx`（右上角新增「导出」下拉菜单：导出为 Markdown / 导出为 JSON，当前会话无消息时禁用）。
- 修改：`src/pages/ai/Copilot/AssistantTab.tsx`（向 `CopilotHeader` 传入 `onExportMarkdown`、`onExportJson`、`canExport`）。

## 4. 实施步骤
1. 实现 `exportUtils.ts`，规范导出文件名（`Nexora_<标题>_YYYYMMDD_HHMM.md/.json`），Markdown 保留标题、时间、模型、问答正文、参考来源及 Token 统计，JSON 保留完整结构化元数据与消息数组。
2. 在 `CopilotHeader.tsx` 右侧操作区加入「导出」按钮与下拉菜单（支持点击外部和 `Esc` 关闭）。
3. 在 `AssistantTab.tsx` 接入导出回调。
4. 编写 `exportUtils.test.ts`，运行 `npm run lint`、`npx vitest run src/pages/ai/Copilot` 和 `npm run build`。

## 5. 验证计划
- 单元测试：`npx vitest run src/pages/ai/Copilot`（含新增 `exportUtils.test.ts`）。
- 类型检查与构建：`npm run lint`、`npm run build`。

## 6. 风险与回滚思路
- 纯前端下载功能，不修改后端 API 或数据库，零副作用；如有异常可直接回滚上述 4 个文件。
