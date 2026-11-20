# 知识库导入导出与 Copilot 普通咨询修复

## 变更

- CMDB 资产数量问题改为确定性 `asset_analysis` 路由，不依赖 LLM 意图解析。
- `consultation`、普通问答和闲聊不再展示诊断证据补全卡片；诊断、配置生成和知识检索仍保留结构化摘要。
- 导入预览与写入统一使用服务端解析器；新增 JSON/YAML/CSV/XML/配置文本校验，HTML 先清理正文，DOCX/PDF 继续走二进制边界。
- Nexora ZIP 导出包增加导入契约，导入时校验 `manifest.json`、数量和路径；向量不导出，目标机重新切片和生成 Embedding。
- 修复知识检索无命中时的提前返回：无命中请求现在经过安全网关进入 DeepSeek 通用参考模式，并强制声明“未经过本地/官方核验”；云端只接收厂商、型号、版本等有界查询范围，不发送原始 RAG 内容。
- 修复系统时间和系统提示词触发保守数据分类器误判的问题；普通问候不再因为时间字符串或连字符被升级为受限数据。
- 修复流式 Copilot 状态：本地命中的配置/命令由本地知识证据直接渲染，`external_egress=false`；只有实际调用云端模型才显示“已通过安全网关外发”。

## 验证

```text
.venv\Scripts\python.exe -m pytest -q backend/tests/ai/test_copilot_contract_v2.py backend/tests/ai/test_ing006_document_parser_adapters.py backend/tests/ai/test_ing021_metadata_confirmation.py backend/tests/ai/test_asset_analysis.py
```

预期：相关用例全部通过。完整 PostgreSQL 数据迁移仍使用 `pg_dump`/`pg_restore`；仅知识库迁移使用知识导出 ZIP。

## 运行时验收（2026-08-23）

- 普通问候：浏览器 Copilot 实测“你好”返回正常 DeepSeek 回答，无 `AI_SECURITY_CLASSIFICATION_DENIED`。
- 本地命中：华为 S5700 OSPF 返回 `huawei_vrp` 知识库配置骨架，并展示本地来源。
- 本地未命中：Juniper EX4300 BGP 进入 DeepSeek 通用参考，回答明确标注未本地/官方核验，并给出版本假设、配置示例和验证命令。
- PostgreSQL 知识库当前 239 篇激活文档、约 1,054 个切片；页面导出实测成功导出 239 篇、约 1.2 MB ZIP，包含 Markdown 与 `manifest.json`，导入时重新切片和生成向量。
