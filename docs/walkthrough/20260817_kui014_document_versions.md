# KUI-014 版本管理验证走查

1. 打开知识库管理，选择带 V2 source version history 的文档。
2. 在“版本管理”中点击“比较最新”，确认只显示内容/Metadata 是否变化、行数和变化字段，不显示正文。
3. 对 draft 版本点击“发布”，确认弹窗后状态变为 active/published，当前版本指针更新。
4. 对旧版本点击“替代”，确认 replacement 必须是已发布版本，历史状态为 superseded。
5. 点击“回滚”，确认当前版本被 superseded、目标旧版本重新 published，刷新后指针和历史保持一致。
6. 使用无权限或其他租户会话访问同一文档，接口返回安全的权限/Not Found，不泄露版本或正文。

自动化证据：`backend/tests/catalog/test_kui_014_document_versions.py` 6 passed；`scripts/knowledge_engine_v2_kui014_pg_probe.py` PostgreSQL PASS。
