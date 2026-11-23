# Walkthrough：Copilot 会话导出（Markdown 与 JSON）

- 对应计划：[plan_20261123_0950_01_Copilot会话导出Markdown与JSON.md](file:///D:/netops/netsops-main/docs/plans/plan_20261123_0950_01_Copilot会话导出Markdown与JSON.md)
- 目标仓库：`D:\netops\netsops-main`

## 1. 完成摘要
在 Copilot 顶部栏右上角新增轻量 **「导出」** 下拉菜单，支持将当前会话一键导出为：
- **Markdown (`.md`)**：保留会话标题、导出时间、当前模型、每轮问答正文、Token 统计（输入/输出/缓存）及参考来源链接。
- **JSON (`.json`)**：输出规范化结构数据（`schema_version`、`exported_at`、`conversation`、`messages` 含 `tokens` 与 `sources`）。
- 文件名自动清洗非法字符并附带时间戳（`Nexora_<标题>_YYYYMMDD_HHMM.md/.json`）；当前会话无消息时按钮自动置灰禁用。

## 2. 实际修改文件
- 新增：[exportUtils.ts](file:///D:/netops/netsops-main/src/pages/ai/Copilot/exportUtils.ts)
- 新增：[exportUtils.test.ts](file:///D:/netops/netsops-main/src/pages/ai/Copilot/exportUtils.test.ts)
- 修改：[CopilotHeader.tsx](file:///D:/netops/netsops-main/src/pages/ai/Copilot/CopilotHeader.tsx)
- 修改：[AssistantTab.tsx](file:///D:/netops/netsops-main/src/pages/ai/Copilot/AssistantTab.tsx)

## 3. 验证命令与结果
- `npm run lint`、`npx vitest run src/pages/ai/Copilot`、`npm run build`：见最终回复。

## 4. 剩余风险
- 纯前端本地导出，无后端依赖；刷新页面即可生效。
