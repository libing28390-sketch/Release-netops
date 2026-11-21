# 实施计划 - 修复 Windows 客户端 removeChild 节点未找到异常

## 1. 任务目标
解决 Windows 客户端（以及浏览器环境）启动或渲染过程中，因浏览器自动翻译插件/Webview 翻译引擎、扩展或 DOM 异步清理争用导致的报错：
`Uncaught NotFoundError: Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.`

## 2. 现状与根因分析
1. **浏览器/Webview 自动翻译引擎 DOM 篡改**：在 Windows 桌面客户端（Webview2 / Chrome / Edge）或中文系统环境下，当 HTML 未明确禁止翻译或 `lang` 标明 `en` 时，Edge/Chrome 会自动对界面文本节点进行翻译并用 `<font>` 等新节点包裹/替换。
2. **React DOM 移除逻辑失效**：React 在组件挂载/卸载/状态切换（如启动时的 Auth 校验、主题切换、加载遮罩层移除）时，会调用原生的 `node.removeChild(child)` 或 `node.insertBefore`。当 DOM 文本节点已被翻译引擎篡改后，`child.parentNode` 不再指向原本的 `node`，从而引发 DOMException `NotFoundError` 抛出，导致 React 根节点崩塌白屏或触发 ErrorBoundary。
3. **缺少 DOM 节点操作防御兜底**：前端未拦截 Node 原生 `removeChild` / `insertBefore` 的异父节点异常。

## 3. 拟修改文件
- `index.html`：补充 `<html lang="zh-CN" translate="no">`，添加 `google/notranslate` Meta 标签，防止 Webview / Edge 自动翻译破坏 DOM 结构。
- `src/main.tsx`：在 React 入口初始化前对 `Node.prototype.removeChild` 和 `Node.prototype.insertBefore` 进行防御性 Monkey-Patch 容错处理。
- `src/utils/clipboard.ts`：将 `document.body.removeChild` 改为防御性清理（检查 `parentNode` 或使用 `.remove()`）。

## 4. 实施步骤
1. 修改 `index.html`：增加 `translate="no"` 属性和防翻译 meta 标签。
2. 修改 `src/main.tsx`：在最前端注入 `removeChild` 与 `insertBefore` 的安全包装函数，当 `child.parentNode !== this` 时输出 `console.warn` 并安全返回，防止崩溃。
3. 修改 `src/utils/clipboard.ts`：规范化 DOM 临时文本框清理逻辑。

## 5. 验证计划
1. 执行 TypeScript / Vite 构建校验：`npm run build` 或 `npx tsc --noEmit`。
2. 启动/模拟前端渲染，验证拦截兜底逻辑正常生效且无类型报错。
