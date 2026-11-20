# KUI-015 Source Registry 走查

1. 进入知识库管理，切换到“Source Registry / 刷新”。
2. 使用状态筛选查看来源；列表只显示名称、规范 URL、生命周期和校验状态，不显示正文或内部路径。
3. 选择来源，检查刷新状态卡片、最近检查时间、结果计数和观察历史。
4. 点击“重新校验”验证 Source Registry allowlist/policy；点击“立即刷新”执行受治理的后端 fetch。
5. 在来源未刷新、失败或被替代时确认分别显示未刷新、失败、需关注状态与稳定错误码。
6. 使用其他租户或无权限账号验证列表、状态和观察历史均拒绝/不泄露。

自动化证据：`backend/tests/catalog/test_cat003_source_registry.py` 5 passed；`scripts/knowledge_engine_v2_kui015_pg_probe.py` PostgreSQL PASS。
