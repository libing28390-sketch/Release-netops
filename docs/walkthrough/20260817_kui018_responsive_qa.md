# KUI-018 Knowledge Admin UI QA

## 走查范围

在知识库管理页分别打开文档、Source Registry、RAG Evaluation 和 Retrieval Trace 视图，按中文/英文、浅色/暗色和 360px 窄屏检查布局。

## 验证点

1. 切换语言后，分页的条数、每页和首尾/前后页按钮使用对应语言；当前页输入不会越界。
2. 切换到暗色主题后，卡片、表格表头、状态徽章、空态、错误态、按钮和分页控件保持可读，不出现白色文字/浅色背景组合。
3. 360px 窄屏下页面本身不产生横向滚动；文档表和评测用例表在自己的滚动容器内横向滚动，操作栏换行。
4. 文档表和评测用例表的表头使用 `sticky top-0`，滚动内容时仍可定位字段。
5. 文档分页默认 20 条、最大 100 条；数据量为 0 时不显示无意义的分页条。

## 自动化证据

- `src/pages/ai/Knowledge/KnowledgeAdminResponsive.test.tsx`：3 passed。
- 全量前端：19 files / 97 tests passed；lint/build PASS。
