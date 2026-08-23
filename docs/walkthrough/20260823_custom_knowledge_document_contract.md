# 自定义知识文档格式契约与导入解析

## 本次变更

- 明确推荐格式：UTF-8 Markdown + YAML/JSON Front Matter。
- 明确必填元数据：`schema_version`、`document_id`、`title`、`vendor`、`product_type`、`document_category`、`source_type`、`official_only`、`status`。
- 增加 JSON/YAML 的 `nexora-knowledge-document` envelope：`format` + `schema_version` + `metadata` mapping + string `content`。
- 服务端在 Metadata Preview 前识别 envelope；普通 JSON/YAML 仍按结构化正文处理，不猜测型号或权限。
- 前端知识库页面提供 Markdown 模板、JSON 模板和格式说明下载。
- 导出 ZIP 的 `manifest.import_contract` 现在声明文档契约版本、必填字段和 JSON/YAML envelope 规则。

## 解析顺序

扩展名识别 → 文件/语法校验 → Front Matter/envelope 解析 → Metadata Preview → 明确确认 → 内容清洗与安全检查 → 切片 → Embedding → PostgreSQL 入库。

## 安全边界

导入文件不得携带租户、ACL、权限、身份、密码、Token、API Key、私钥或服务端 `content`/`body` 字段。自定义文档使用 `official_only: false` 和 `status: draft`，官方材料必须经过官方来源审核流程。

## 验证命令

```powershell
.venv\Scripts\python.exe -m pytest -q backend/tests/ai/test_ing006_document_parser_adapters.py backend/tests/ai/test_ing021_metadata_confirmation.py backend/tests/ai/test_knowledge_export_service.py
npm run test:frontend -- --run
node .\node_modules\typescript\bin\tsc --noEmit --pretty false
```
