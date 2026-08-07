# Plan: Nexora AI Copilot ChatGPT式专业网络运维助手界面重构

## 任务目标
将现有的 AI Copilot 从“RAG 调试控制台”升级重构为 **ChatGPT 极简对话交互 + Nexora 网络运维专业能力** 的下一代 Network Operations Copilot。

---

## 现状与核心痛点
1. **调试信息置顶抢戏**：用户提问后，优先展现 `INTENT: CONFIG_SEARCH`、RAG 向量卡片、响应毫秒数，真正关心的配置命令与解答被挤压在下方。
2. **视觉布局分散无收敛**：聊天区域直接填满大屏，有效文字阅读宽度过宽，多处卡片边框与高饱和紫色强色彩导致视觉噪音。
3. **输入框形态陈旧**：底部类似于传统客服窗口，缺少 ChatGPT 风格的高品质自适应文本框、`/` 快捷指令及 `@` 设备联动能力。

---

## 三层信息架构 (3-Tier Information Architecture)

1. **第一层：极简对话主视图 (Default View)**
   - 展现标准用户气泡（淡灰/微淡暗冷色 `#f4f4f5`，非高饱和紫色）与 AI 回答。
   - 大模型回答直接呈现在页面，去除大块硬边框卡片，突出 Markdown 配置命令。
   - 底部仅保留优雅的 **`📚 已参考 3 个知识库来源`** 轻量 Chip 与点赞/复制/重新生成操作栏。

2. **第二层：知识库来源弹窗 / 浮层 (Source References Popover)**
   - 点击 `📚 已参考 3 个知识库来源` 展开优雅浮层，显示引用的文档名称、章节与相关度。

3. **第三层：高级开发者调试抽屉 (Inspector Drawer)**
   - 点击消息右上角的 **开发者调试 (Inspector)** 图标，从右侧滑出 `360px` 抽屉。
   - 展示 `Intent` (意图)、`Vendor/Platform` (厂商/平台)、`Retriever` (检索命中率)、`Token Usage` (Token 消耗)、`Latency` (耗时) 及完整 Trace。

---

## 核心拟修改与新增文件

### 1. 计划与记录归档 (Workspace Docs)
- `docs/plans/plan_20260807_1303_01_Copilot_ChatGPT重构.md`
- `docs/walkthrough/walkthrough_20260807_1303_01_Copilot_ChatGPT重构.md`

### 2. 前端组件与页面 (Frontend Components)
- `src/pages/ai/Copilot/AssistantTab.tsx`: 组合侧边栏、主对话、右侧调试抽屉与响应式布局
- `src/pages/ai/Copilot/CopilotSidebar.tsx`: [NEW] 左侧 `260px` 历史会话管理（+ 新建对话、今天/昨天分组、搜索会话、Hover 删除、AI 设置入口）
- `src/pages/ai/Copilot/CopilotHeader.tsx`: [NEW] 顶部 `56px` 标题栏、模型选择下拉框、清空当前会话、 Inspector 抽屉开关
- `src/pages/ai/Copilot/CopilotEmptyState.tsx`: [NEW] 极简 Empty State（✦ Nexora AI 欢迎词、4 个运维快捷入口卡片）
- `src/pages/ai/Copilot/CopilotUserMessage.tsx`: [NEW] 淡色高质感用户气泡
- `src/pages/ai/Copilot/CopilotAssistantMessage.tsx`: [NEW] AI 消息流、MarkdownRenderer 嵌入、NetworkConfigBlock 嵌入、知识库 Sources 浮层、操作栏
- `src/pages/ai/Copilot/CopilotComposer.tsx`: [NEW] ChatGPT 风格 24px 圆角自适应输入框，支持 `/` 斜杠命令与 `@` 设备搜索联动
- `src/pages/ai/Copilot/CopilotInspectorDrawer.tsx`: [NEW] 右侧 360px 开发者/管理员 Trace 调试抽屉
- `src/components/MarkdownRenderer.tsx`: [MODIFY] 强化网络厂商 CLI 控制台 (`NetworkConfigBlock`)，提供 `📋 复制配置`、`☆ 保存模板`、`⚡ 创建配置任务`

---

## 实施步骤

### 阶段一：建立三层数据模型与类型 (Types & Data Schema)
- 扩展 `ChatMessage` 类型，包含 `sources`、`intent`、`timing`、`usage`、`status`、`vendor` 等元数据。
- 重构 `localStorage` 会话持久化与状态管理。

### 阶段二：重构 UI 布局架构 (ChatGPT Modern Layout)
- 实现 Left Sidebar (`260px`) + Center Workspace (`max-width: 820px`) + Right Inspector Drawer (`360px`).
- 构建 `CopilotHeader` 与 `CopilotSidebar` 会话检索与按天分组。

### 阶段三：打造 ChatGPT 级 Chat Composer (输入框与快捷交互)
- 24px 圆角、可自动增长文本框、`↑` 发送图标。
- 引入 `/` 斜杠指令菜单 (`/ip`, `/config`, `/troubleshoot`, `/knowledge`)。
- 引入 `@` CMDB 搜索下拉菜单。

### 阶段四：网络命令专属 Block 与 3 级调试抽屉
- 优化 Markdown 代码块，增加 `⚡ 创建配置任务`、`☆ 保存模板` 交互按钮。
- 抽离隐藏深层调试数据至右侧 `CopilotInspectorDrawer` 抽屉。

### 阶段五：回归测试与生产构建
- 验证 TypeScript 编译与 `npm run build`。
- 走查大屏、中屏及响应式体验。

---

## 验证与风险与回滚思路
- **验证计划**：运行 `npm run build` 确保无 TypeScript 类型错误；在 Chrome 运行多轮对话、打字流、快捷指令与抽屉交互测试。
- **风险防护**：原有对话与数据完全兼容，会话平滑升级至 v4 模式。
