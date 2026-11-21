# 修复 DeepSeek 模型验证与连通性测试 (Walkthrough)

## 1. 完成摘要
针对用户在 AI 供应商管理界面配置 DeepSeek 测试连通性失败、出现 `AI_HEALTH_BACKOFF` / `AI_MODEL_NOT_FOUND` 的问题，进行了深层根因排查与修复：
1. **扩大 DeepSeek 模型支持范围**：在 `backend/ai/providers/deepseek.py` 中增加了官方标准模型 `deepseek-chat`（DeepSeek-V3）、`deepseek-reasoner`（DeepSeek-R1）、`deepseek-coder` 以及支持任意 `deepseek-*` 前缀模型的支持，修复原先仅支持 `deepseek-v4-flash/pro` 导致的模型过滤阻断；
2. **清除探测冷却与失败状态**：重置当前供应商的健康状态，清除阻断用户即时重试的 `AI_HEALTH_BACKOFF` 冷却状态；
3. **修复单元测试中的数据库兼容与异步测试标记**：
   - 为 SQLite 注册 `psycopg2.extras.Json` 的自动适配器，消除测试时 `Error binding parameter: type 'Json' is not supported` 异常；
   - 在 `get_document_detail` 查询中增加字段与表存在的兼容性处理；
   - 更新异步单测标记为 `@pytest.mark.anyio`。

---

## 2. 实际修改文件
- [backend/ai/providers/deepseek.py](file:///d:/nexora/nexora-private/backend/ai/providers/deepseek.py)：支持 `deepseek-chat`, `deepseek-reasoner` 等官方模型与动态前缀；
- [backend/tests/ai/test_deepseek_contract.py](file:///d:/nexora/nexora-private/backend/tests/ai/test_deepseek_contract.py)：增加 `deepseek-chat` / `deepseek-reasoner` 验证单测；
- [backend/ai/services/knowledge_service.py](file:///d:/nexora/nexora-private/backend/ai/services/knowledge_service.py)：适配 SQLite Json 绑定及动态 `ORDER BY`；
- [backend/services/document_version_service.py](file:///d:/nexora/nexora-private/backend/services/document_version_service.py)：增加 SQLite Json 绑定适配；
- [backend/tests/ai/test_provider_connection_security_fix.py](file:///d:/nexora/nexora-private/backend/tests/ai/test_provider_connection_security_fix.py)：使用 `@pytest.mark.anyio`；
- [backend/tests/ai/test_provider_auth_failure_surface.py](file:///d:/nexora/nexora-private/backend/tests/ai/test_provider_auth_failure_surface.py)：使用 `@pytest.mark.anyio`。

---

## 3. 验证结果
```bash
pytest backend/tests/ai/ -v
```
**结果**：**288 passed in 9.54s (100% 通过)**。
供应商状态已重置为可立即测试状态。
