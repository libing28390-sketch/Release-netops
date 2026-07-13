# 机架批量导入导出与功耗修复 Walkthrough

## 完成摘要

- 核对后确认机架页面的功耗/U 位输入、Excel 模板下载、导入、导出功能已经实现。
- 补齐后端批量导入事务性：任意一行失败时回滚本批次已创建的机架，避免半导入。
- 增加回归测试覆盖“第 2 行失败，第 1 行不得残留”的原子性场景。

## 实际修改文件

- `backend/api/racks.py`
- `backend/services/rack_service.py`
- `backend/tests/test_racks_new_fields.py`
- `docs/plans/plan_机架批量导入导出与功耗修复.md`

## 关键实现说明

- `rack_service.create_rack` 新增 `commit` 参数，默认保持原行为；批量导入时传入 `commit=False`。
- `api_batch_create_racks` 使用单个 `BEGIN`/`commit` 包裹全部导入；发生行级错误时执行 `rollback` 并返回具体失败行号。
- 前端现有 `handleDownloadTemplate`、`handleExport`、`handleImport` 已调用 `POST /api/racks/batch`，无需新增界面改动。

## 验证命令与结果

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_ssh_compat_paging.py backend/tests/test_racks_new_fields.py -q`
- 结果：`8 passed in 4.63s`
- `npm run lint`
- 结果：通过，`tsc --noEmit` 退出码 `0`

## 未执行验证及原因

- 未在浏览器手工导入 Excel；当前验证以 API 单元测试和 TypeScript 编译为主。

## 剩余风险与建议

- 建议在本地 UI 用模板文件手工导入一次，确认浏览器文件解析、权限 token 和后端事务错误提示的完整链路。
