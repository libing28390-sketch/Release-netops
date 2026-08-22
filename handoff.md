# Nexora NetOps Copilot 交接说明

- 日期：2026-08-22
- 任务范围：Copilot Trace 入口去重、回答文本选择与复制稳定性修复
- 当前状态：代码修改已完成，前端测试、类型检查和生产构建均已通过；本次未执行 commit 或 push。

## 已完成内容

### Trace 调试入口

- 删除页面顶部重复的全局“调试 Trace”入口。
- 保留每条 AI 回答下方的“调试 Trace”，打开当前回答对应的调试信息。
- Trace Inspector 保持居中弹窗展示，便于查看处理过程。

### 回答文本选择与复制

- 记录有效文本选区，并限制选区恢复在对应的 Copilot 回答内。
- 在 document 捕获阶段同步恢复选区，兼容右键菜单触发时浏览器先清除选区的情况。
- 增加 0ms fallback，仅用于适配嵌入式浏览器事件时序。
- 文本拖动选择期间暂停自动滚动，避免流式回答刷新时选区被打断。
- 用户主动滚离底部后不再强制贴底；发送新问题时恢复自动贴底。
- 流式输出阶段使用稳定的纯文本节点，回答完成后再切换为 Markdown 渲染，减少选区因频繁重渲染而丢失。
- 增加选区工具函数及对应测试。

## 关键文件

- `src/pages/ai/Copilot/AssistantTab.tsx`：选区捕获/恢复、自动滚动策略、流式回答渲染。
- `src/pages/ai/Copilot/CopilotHeader.tsx`：移除顶部重复 Trace 入口。
- `src/pages/ai/Copilot/CopilotInspectorDrawer.tsx`：Trace 居中 Inspector。
- `src/pages/ai/Copilot/CopilotComposer.tsx`：保留并验证输入区交互。
- `src/pages/ai/Copilot/keypaths.test.tsx`：页面关键交互回归测试。
- `src/pages/ai/Copilot/selectionUtils.ts`：选区判断、克隆和恢复工具。
- `src/pages/ai/Copilot/selectionUtils.test.ts`：选区工具单元测试。

## 验证结果

执行了以下检查：

~~~text
npm run test:frontend -- --run src/pages/ai/Copilot/selectionUtils.test.ts src/pages/ai/Copilot/keypaths.test.tsx src/pages/ai/Copilot/progress.test.ts
~~~

- Vitest：3 个测试文件、7 个测试全部通过。
- `npm run lint`：通过，TypeScript 类型检查无错误。
- `npm run build`：通过，Vite 生产构建成功；仅保留既有的大 chunk 提示。
- 浏览器验证：鼠标拖动选中文本后使用 Ctrl+C，可正常复制并粘贴选中文本。
- 内置浏览器 CUA 工具无法完整验证原生右键菜单：该工具会在 contextmenu 事件后清除选区；但同步捕获恢复和 fallback 恢复逻辑已通过运行时日志确认生效。接入真实浏览器后需再验证原生“复制”菜单。

## 部署与接手步骤

### 本地开发

Vite 开发服务通常会自动热更新；刷新 `/ai/copilot` 后验证最新页面即可。本次是前端交互修复，不需要修改 `.env`。

### Docker 环境

~~~text
docker compose up -d --build --force-recreate netops nginx
~~~

### 建议回归路径

1. 打开 `/ai/copilot`，等待一条 AI 回答完成。
2. 用鼠标拖动选中回答中的部分文本，使用 Ctrl+C 并粘贴验证内容完整。
3. 在选中文本上右键，确认真实浏览器原生菜单中可以使用“复制”。
4. 让 AI 生成较长的流式回答，并在生成过程中尝试选择文本，确认不会被自动滚动打断。
5. 滚动离开底部后继续生成内容，确认页面不会强制跳回底部。
6. 点击某条回答下方的“调试 Trace”，确认打开的是该回答的 Trace，且页面顶部不再出现重复入口。

## 当前注意事项

- 工作区内还存在其他用户已有修改，本次 handoff 不对这些修改进行整理、回滚或提交。
- `dist/index.html` 已恢复到构建前版本，避免生产构建产生的资源哈希变更混入本次工作区。
- 本次未执行 commit/push，后续由项目负责人确认后统一提交。
