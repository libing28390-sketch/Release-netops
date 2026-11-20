# 拓扑默认 Site 卡片视图

## 完成摘要
`/monitor/topology` 首次打开时默认显示 Site 总览卡片。移除了画布右上角“Site 总览 / 设备拓扑”切换按钮；点击 Site 卡片进入对应拓扑，顶部筛选选择“全部站点”返回卡片总览。

## 实际修改文件
- `src/pages/TopologyPage.tsx`
- `docs/plans/plan_20260930_1552_01_拓扑默认Site卡片视图.md`
- `docs/walkthrough/walkthrough_20260930_1552_01_拓扑默认Site卡片视图.md`
- `docs/fixes/fix_20260930_1653_01_拓扑画布移除视图切换按钮.md`
- 本地生成输出：`dist/index.html` 和 `dist/assets/` 中的新构建文件（未纳入 Git 提交）

## 关键实现说明
保持 `canvasView` 初始为 `overview`，移除画布右上角的双视图控件。点击卡片仍进入站点拓扑；Site 筛选选择“全部站点”时切回卡片总览。发现现有本地 `dist` 页面早于源码更新，因此另行构建到临时目录，再复制生成的页面和资源覆盖本地入口，保留原有 `dist/data`、`dist/downloads`、`dist/templates` 内容。

## 验证命令与结果
- `git diff --check`：通过。
- `node node_modules/vite/bin/vite.js build --outDir .codex-build-validation-topology-site-cards`：通过，Vite 完成 4319 个模块构建。
- `npm run lint`：通过（`tsc --noEmit`）。
- 检查生成的 `TopologyPage` bundle：不再包含“Site 总览”“设备拓扑”切换文案，保留“全部站点”筛选。
- 更新本地 `dist/index.html` 及构建资源，并确认入口引用的资源均存在；原有静态数据目录未清理。

## 未执行验证及原因
- 未运行自动化测试；已运行 TypeScript 检查与生产构建。

## 剩余风险/后续建议
- 页面仍由本地服务或浏览器缓存提供时，重新加载 `/monitor/topology` 以读取更新后的本地构建产物。
