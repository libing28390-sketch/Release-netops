# Chunking V2 落地记录

## 本轮完成

- 新增独立的 `backend/ai/chunking` 结构化切片引擎。
- 支持标题路径继承、代码围栏、CLI、命令回显、表格、Warning/Note、排障块识别。
- 支持 `standalone`、`parent`、`child` 三种切片角色。
- 使用 Token 估算预算，不再把字符数当作 Token。
- 为切片生成稳定内容哈希、标题路径、来源行号、知识类型和 embedding_content。
- 新文档入库默认写入 `chunking_version = v2`。
- 新增 m0111，采用可回滚的增量字段和索引，不重写既有文档。
- 旧检索路径兼容旧表结构，并跳过 V2 Parent 上下文块。

## 尚未切换

- 当前仍使用现有 JSON embedding 存储；真实 pgvector 和向量索引属于下一阶段。
- 尚未启用全量旧文档重切片。
- 尚未切换 BM25/FTS、Reranker、Query Rewrite 和 Parent 扩展策略。
- 尚未把 PDF/DOCX 等格式解析器接入 AST；当前入口仍接收 Markdown/plain text。

## 验证

- AI 与数据库相关测试：31 passed。
- 全量后端测试：944 passed，75 项平台注册测试因环境缺少 PostgreSQL 在 fixture 初始化阶段报错。
- 新增边界覆盖：标题上下文、超长代码围栏、排障 Parent–Child、迁移幂等、旧检索兼容。
