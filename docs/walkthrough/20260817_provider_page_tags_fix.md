# Provider 页面异常修复验证

日志根因是 `ai_provider.tags_json={}` 与响应合同 `tags: list[str]` 不一致。修复后：

1. API 层对历史对象、损坏 JSON 和已解码 PostgreSQL 值安全归一化为空列表。
2. m0148 在 PostgreSQL 中将已知无效空值规范化为 `[]`，并已在当前实例应用。
3. 需要重启正在运行的后端进程加载 `backend/ai/api/providers.py`，然后打开 `/ai/providers` 刷新。

预期：Provider 列表正常显示，不再出现“服务内部异常”；没有 Provider 数据或 API Key 被删除。
