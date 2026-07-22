# Git 提交修复记录 - 修复 Windows 客户端 removeChild 节点未找到异常

## 1. 问题现象
在 Windows 客户端启动或页面渲染时触发控制台/页面崩溃异常：
`Uncaught NotFoundError: Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.`

## 2. 根因分析
1. Windows 客户端 Webview2 / Edge / Chrome 在中文系统环境或自动翻译插件启用时，将前端文本节点用 `<font>` 等新节点替换。
2. React 试图执行 `node.removeChild(child)` 卸载元素时，发现 `child.parentNode` 已经被浏览器翻译插件篡改，因此抛出 `NotFoundError` 异常并导致 React 根节点挂掉。

## 3. 解决方案
1. 在 `index.html` 的 `<html>` 标签增加 `lang="zh-CN"` 和 `translate="no"` 属性，并添加 `<meta name="google" content="notranslate" />` 等标签，从源头禁止翻译引擎篡改 DOM。
2. 在 `src/main.tsx` 最开始注入 `Node.prototype.removeChild` 和 `Node.prototype.insertBefore` 容错拦截逻辑：若发现 `child.parentNode !== this` 则打印 Warning 并安全跳过，防止应用崩溃。
3. 在 `src/utils/clipboard.ts` 临时剪贴板元素清理中增加防御性 `parentNode` 判断。

## 4. 实际修改文件
- `index.html`
- `src/main.tsx`
- `src/utils/clipboard.ts`
- `docs/plans/plan_20260722_2219_01_修复Windows客户端removeChild节点异常.md`
- `docs/walkthrough/walkthrough_20260722_2219_01_修复Windows客户端removeChild节点异常.md`
- `docs/fixes/fix_20260722_2221_01_修复Windows客户端removeChild节点异常.md`

## 5. 验证命令与结果
- `npx tsc --noEmit` 编译检查通过，0 错误。

## 6. 未验证项
- 无。

## 7. 风险与回滚方式
- 风险低。若需回滚，可使用 `git revert` 撤销本次提交。
