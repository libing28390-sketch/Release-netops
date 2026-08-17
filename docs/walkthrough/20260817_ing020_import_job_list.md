# ING-020 Import Job 列表与重试验证记录

## 原始任务

第 7 节“统一采集与导入流水线”的 `ING-020`：实现导入任务列表、过滤、分页、阶段进度和错误重试。

## 落地范围

- `GET /api/v2/kb/ingestion/jobs` 增加服务端状态、阶段、任务类型、关键词过滤和有界分页。
- 列表接口返回摘要行和 `total/page/page_size/total_pages`，不返回错误正文、审计历史、租户 ID 或 Worker fence 信息。
- 知识库管理页面增加 Import Job 列表，展示状态、阶段、进度条、计数、更新时间和失败错误码。
- 错误详情按需请求，失败/等待重试任务提供显式重试按钮；服务端仍执行租户和权限校验。
- 空数据、筛选无结果、加载失败、分页和重试中状态均有明确反馈。

## 验证命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\pytest.exe backend/tests/ai/test_ingestion_job_list_pagination.py backend/tests/ai/test_ingestion_job_control_surface.py backend/tests/ai/test_ingestion_pipeline_state_machine.py -q -p no:cacheprovider
npm.cmd run test:frontend -- --run src/pages/ai/Knowledge/IngestionJobsPanel.test.tsx
npm.cmd run test:frontend -- --run
npm.cmd run lint
npm.cmd run build
```

## 结果

- 后端聚焦回归：17 passed。
- 前端 ING-020：3 passed；全量前端：22 files / 104 tests passed。
- TypeScript lint：PASS。
- Vite production build：PASS；仅保留既有大 bundle warning，无构建错误。
- PostgreSQL/V1 数据路径未改动，无新增 migration。

## 已知限制

当前 Import Pipeline 控制面仍使用既有内存兼容仓储，DB-011 的物理 PostgreSQL Import Job 表迁移仍是独立任务；本任务在 API 边界实现有界分页，避免向浏览器返回全量错误/审计数据。
