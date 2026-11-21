# CHK-P0-12 执行记录

## 目标

完成网络知识结构化分块与 Embedding Contract 的 CHK-001 至 CHK-012，保留 V1 `ai_document` / `ai_document_chunk` 读写兼容，不提前启用 DB-010 的后续规范表。

## 已落地能力

- ChunkingEngine 输出标题、段落、CLI、输出、表格、警告、前提、示例结构类型。
- 配置边界在构造时校验；命令组按非缩进行分界，参数/续行保持原子；无明确记录边界的命令输出保持原子并标记超大原因。
- Chunk 明确记录 role、section path、page、token count、content hash、parent、邻接 Chunk ID；邻接关系双向对称且不依赖 ordinal 推断。
- 结构校验拒绝空块、重复内容哈希、非法 role/structure、悬空 parent、非法邻接和未闭合代码围栏。
- 文档和 Chunk 持久化 parser/document/index version、chunker version、embedding model/version/dimensions/mode/contract。
- `ExternalEmbeddingProvider` 必须先经过 AI Security Gateway；外发前执行分类、最小化、令牌化、DLP，并只记录哈希审计证据。
- `embed_documents_batch` 提供批量、有限重试、幂等缓存和可配置限速；失败时在事务前终止，不产生半成品文档/Chunk。
- m0137 仅增加兼容投影列，未替换 DB-010 后续规范图模型，旧字段和旧 API 保留。

## 验证命令

```powershell
$env:PYTHONPATH = 'backend'
.venv\Scripts\pytest.exe backend/tests/ai/test_chk_p0_chunking_contract.py backend/tests/ai/test_chk_p0_embedding_contract.py backend/tests/ai/test_chk_p0_ingestion_contract.py -q -p no:cacheprovider
.venv\Scripts\pytest.exe backend/tests/database/test_m0137_chunk_index_contract_projection.py -q -p no:cacheprovider
.venv\Scripts\pytest.exe backend/tests/ai -q -p no:cacheprovider
.venv\Scripts\pytest.exe backend/tests/database -q -p no:cacheprovider
```

## 回滚

停止 V2 分块/Embedding 写入即可继续读取原有 V1 字段；m0137 的新增列保留，避免删除已写入的审计和版本证据。若需要关闭外部 Embedding，设置 `AI_EMBEDDING_MODE=disabled` 或启用 AI kill switch，系统会 fail-closed。
