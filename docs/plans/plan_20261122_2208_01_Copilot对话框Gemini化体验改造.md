# Copilot 对话框 Gemini 化体验改造实施计划

- 创建时间：2026-11-22 22:08
- 目标目录：`D:\netops\netsops-main`

## 1. 任务目标

将 `http://192.168.56.1:5400/ai/copilot` 改造为接近 Google Gemini 的极简沉浸式对话体验：去掉页面上冗余的调试/诊断信息与双层视觉噪音，优化为居中大胶囊输入框、极简顶栏、去噪消息流与智能滚动，同时完整保障基于 PostgreSQL `ai_conversations` / `ai_messages` 的多轮会话记忆功能。

## 2. 现状与问题

1. **视觉与空间拥挤**：顶栏同时展示模型健康标签、`内网事实优先` 徽章等，消息底部常驻 `耗时 0秒`、`案例`、`调试 Trace`、`未发生外部调用 · 模型 Token：输入 0 / 输出 0` 等工程调试信息。
2. **输入框层级冗余**：输入框上方额外浮动 `选择诊断范围` 按钮，未采用 Gemini 风格的极简圆角大胶囊；未支持输入 `/` 触发行内斜杠命令浮层。
3. **默认首屏与阅读流**：AI 消息外框/调试条过重；缺少用户向上翻看历史时暂停自动滚底并显示「回到底部」按钮的流畅体验。

## 3. 影响范围与拟修改文件

- `src/pages/ai/Copilot/CopilotHeader.tsx`：极简化顶栏（保留会话标题、模型名称与清空/新建入口，去掉多余状态噪音）。
- `src/pages/ai/Copilot/CopilotEmptyState.tsx`：Gemini 风格居中文案问候（`你好，...`）+ 轻巧的横向快捷建议胶囊芯片。
- `src/pages/ai/Copilot/CopilotComposer.tsx`：升级为 Gemini 风格圆角大胶囊（`rounded-[28px]` + 柔光阴影），将诊断范围按钮整合进 `+` 菜单（不再在输入框上方多占一行），支持输入 `/` 直接弹出斜杠快捷指令菜单。
- `src/pages/ai/Copilot/AssistantTab.tsx`：去除消息流中常驻的「耗时 / 案例 / 调试 Trace / Token 遥测行 / 选择诊断范围」视觉噪音，保留极简操作栏（复制、好评、差评、编辑重发）与「回到底部」智能滚动；完整保留 `conversation_id` 持久化与多轮记忆链路。

## 4. 实施步骤

1. 改造 `CopilotHeader.tsx` 与 `CopilotEmptyState.tsx` 为 Gemini 极简风格。
2. 改造 `CopilotComposer.tsx` 为悬浮圆角大胶囊，整合 `+` 菜单与 `/` 行内斜杠命令浮层。
3. 精简 `AssistantTab.tsx` 消息渲染区的调试/诊断/遥测噪音，优化居中阅读宽度（`max-w-3xl`）与智能滚动。
4. 运行前端 `npm run lint`、`npx vitest run src/pages/ai/Copilot` 与 `npm run build` 验证。

## 5. 验证计划

- `npm run lint`（`tsc --noEmit`）0 错误。
- `npx vitest run src/pages/ai/Copilot` 全部通过。
- `npm run build` 构建成功。
- 浏览器访问 `http://192.168.56.1:5400/ai/copilot` 实际走查视觉效果与多轮记忆。

## 6. 风险与回滚思路

仅修改 `src/pages/ai/Copilot/` 下 4 个前端展示组件，不改动后端接口与数据库表结构；如有需要可通过 `git checkout -- src/pages/ai/Copilot/` 一键回滚。
