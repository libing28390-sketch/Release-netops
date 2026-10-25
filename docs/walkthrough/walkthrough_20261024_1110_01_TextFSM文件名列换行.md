# TextFSM 文件名列换行

## 完成摘要

修复 `/automation/textfsm` 模板表中长文件名覆盖“厂商”列的问题。文件名单元格现在使用表格已有的换行约定，并保留完整文件名提示；没有调整列顺序、分页或页面布局。

## 实际修改文件

- `src/pages/TextFSMTemplatesTab.tsx`

## 关键实现

- 为文件名单元格增加 `nx-data-table-cell--wrap`，覆盖表格单元格默认的 `white-space: nowrap`。
- 使用 `break-words` 让长文件名在本列内换行，并通过 `title` 保留完整值查看方式。
- 不改共享表格 CSS，避免影响其他列表。

## 验证命令与结果

- 浏览器查看 `/automation/textfsm`：文件名换行，厂商列清晰可读；复核截图视口为 1920×873。
- `npm run lint`：通过，`tsc --noEmit` 退出码 0。
- `node .\\node_modules\\vite\\bin\\vite.js build --outDir C:\\Users\\NINGMEI\\AppData\\Local\\Temp\\netsops-textfsm-columns-20261024`：通过，Vite production build 退出码 0；产物写入临时目录。
- `git diff --check -- src/pages/TextFSMTemplatesTab.tsx src/pages/ScriptManagementTab.tsx`：修正审核弹窗文件中的一处行尾空格后通过。

## 未执行验证及原因

- 未运行自动化测试；本次变更只涉及表格单元格样式，已完成浏览器目视检查、TypeScript 检查和生产构建。
- 未在现场设备或生产环境验证；本次不涉及数据或设备行为。

## 剩余风险与回滚

- 特别长的文件名会增加该行高度，这是避免跨列遮挡的预期表现。
- 如需回滚，移除该文件名单元格上的 `nx-data-table-cell--wrap`、`break-words` 和 `title` 即可。
