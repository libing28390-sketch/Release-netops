# Nexora NetOps Copilot 交接说明

- 日期：2026-08-22
- 任务范围：Copilot Trace 入口去重、回答文本选择与复制稳定性修复、后端 ping/tracert 编码崩溃修复、流式渲染性能优化
- 当前状态：代码修改已完成，前端测试、类型检查和生产构建均已通过；本次未执行 commit 或 push。

## 2026-08-22 第二轮修复

### 后端 UnicodeDecodeError（选中文本时控制台大量报错）

- 根因：`connectivity_service` / `inspection_service` / `outbound_probe_service` 中 4 处
  `subprocess.run(..., capture_output=True, text=True)` 未指定编码。中文 Windows 的
  `ping`/`tracert` 输出 GBK（0xd5 为 GBK 首字节），后端 Python 处于 UTF-8 模式时
  读取线程解码崩溃，探测输出丢失。
- 修复：新增 `backend/core/subprocess_utils.py`（`run_console_command` +
  `decode_console_output`，按字节捕获后依次尝试 UTF-8/GBK 解码，最终 replace 兜底），
  4 处调用点全部切换到该 helper。
- 验证：venv 内真实执行 `_server_ping('127.0.0.1')`，中文输出正确解码，
  丢包率与 RTT 解析正常，无任何 UnicodeDecodeError。

### 选中/复制延迟（前端性能）

- 根因 1：`selectionUtils.hasTextSelection` 用 `selection.toString().trim()` 判断选区，
  为 O(n) 序列化。拖动选中时每次 `selectionchange` 触发；流式输出时每个 token 的
  滚动 effect 也触发。长回答下持续整段序列化导致卡顿。已改为 `!selection.isCollapsed`（O(1)）。
- 根因 2：每个 SSE token 触发一次 `setSessions`，整个会话树（侧栏+全部消息+输入框）
  每 token 重渲染一次。已改为 token 缓冲 + requestAnimationFrame 按帧合并提交
  （后台标签页降级为 100ms setTimeout），流结束/出错时同步 flush，内容不丢失。
- 新增 `src/pages/ai/Copilot/streamRender.test.tsx`：渲染完整 AssistantTab，
  验证批量合并后回答内容完整（含流结束同帧到达的尾部 token）。

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

- `backend/core/subprocess_utils.py`：subprocess 输出容错解码 helper（新增）。
- `backend/services/connectivity_service.py`、`backend/services/inspection_service.py`、`backend/services/outbound_probe_service.py`：ping/tracert 调用点切换到新 helper。
- `src/pages/ai/Copilot/AssistantTab.tsx`：选区捕获/恢复、自动滚动策略、流式回答渲染、token 按帧合并。
- `src/pages/ai/Copilot/selectionUtils.ts`：选区判断、克隆和恢复工具（hasTextSelection 已 O(1) 化）。
- `src/pages/ai/Copilot/streamRender.test.tsx`：流式 token 批量渲染回归测试（新增）。
- `src/pages/ai/Copilot/CopilotHeader.tsx`：移除顶部重复 Trace 入口。
- `src/pages/ai/Copilot/CopilotInspectorDrawer.tsx`：Trace 居中 Inspector。
- `src/pages/ai/Copilot/CopilotComposer.tsx`：保留并验证输入区交互。
- `src/pages/ai/Copilot/keypaths.test.tsx`：页面关键交互回归测试。
- `src/pages/ai/Copilot/selectionUtils.test.ts`：选区工具单元测试。

## 验证结果

执行了以下检查：

~~~text
npm run test:frontend -- --run src/pages/ai/Copilot/
npm run lint
npm run build
~~~

- Vitest：4 个测试文件、9 个测试全部通过（含新增 streamRender 2 个用例）。
- `npm run lint`：通过，TypeScript 类型检查无错误。
- `npm run build`：通过，Vite 生产构建成功；仅保留既有的大 chunk 提示。
- 后端：4 个改动文件语法检查通过；venv 导入冒烟通过；真实 ping 执行验证 GBK 解码与结果解析正常。
- `dist/index.html` 已恢复到构建前版本，避免资源哈希变更混入工作区。

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
