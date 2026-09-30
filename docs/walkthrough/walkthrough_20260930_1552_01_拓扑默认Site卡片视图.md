# 拓扑默认 Site 卡片视图

## 完成摘要
`/monitor/topology` 首次打开时默认显示 Site 总览卡片。点击卡片仍会筛选并进入所选 Site 的拓扑画布。

## 实际修改文件
- `src/pages/TopologyPage.tsx`
- `docs/plans/plan_20260930_1552_01_拓扑默认Site卡片视图.md`
- `docs/walkthrough/walkthrough_20260930_1552_01_拓扑默认Site卡片视图.md`

## 关键实现说明
将 `canvasView` 的初始值从 `site` 改为 `overview`。现有 Site 卡片、站点选择回调和手动视图切换行为未变。

## 验证命令与结果
- `git diff --check`：通过。
- 检查 `git diff -- src/pages/TopologyPage.tsx`：确认只有初始视图值发生代码改动。

## 未执行验证及原因
- 未运行 lint、构建或测试；本次只改动初始视图状态，且用户没有要求运行测试。

## 剩余风险/后续建议
- 如需浏览器确认，可打开 `/monitor/topology` 验证首次进入显示 Site 卡片，点击 Site 后显示对应拓扑。
