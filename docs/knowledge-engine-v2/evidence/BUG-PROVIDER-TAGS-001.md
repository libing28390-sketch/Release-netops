# Provider 页面内部异常修复证据

## 现象

`GET /api/ai/providers` 返回内部异常，Request ID：`req_2b12119c464f4fc88462`。

## 根因

现有 PostgreSQL `ai_provider.tags_json` 为 m0139 历史默认值 `{}`，而 `AIProviderResponse.tags` 合同要求 `list[str]`。`_row_to_provider` 将对象直接传给 Pydantic，导致 `ValidationError`。

## 修复

- Provider 响应转换器兼容 JSON 字符串、已解码列表和历史对象值；非列表/损坏值 fail-closed 为空列表。
- 新增 m0148 幂等迁移，将已知空对象、空值和 `null` 规范化为 `[]`，不改写有效标签。
- 新增 SQLite 兼容单测和真实 PostgreSQL 临时事务探针。

## 验证

| 命令 | 结果 |
| --- | --- |
| Provider 响应 + m0148 migration focused pytest | 12 passed |
| AI 全套回归 | 259 passed |
| `scripts/knowledge_engine_v2_m0148_pg_probe.py` | PostgreSQL 临时事务 PASS，回滚 PASS |
| 实际 PostgreSQL `run_migrations(..., strict_history=True)` | applied=1；现有 Provider `tags_json=[]` |
| 直接调用 `list_providers(user={"username":"admin"})` | count=1；tags=[[]]；PASS |
| Python compile / diff check | PASS |

## 数据库影响

m0148 已在当前 PostgreSQL 实例应用并记录到 `schema_migrations`；仅将历史无效空对象改为空列表，不删除 Provider、模型或密钥数据。迁移幂等，回滚保留规范化结果，避免恢复故障默认值。

## 安全影响

未改变 API Key 加密、掩码和权限逻辑；验证输出不包含密钥原文。

## 运行恢复

后端进程需重新加载本次代码（重启开发后端/应用服务），然后刷新 `/ai/providers`。迁移已在当前 PostgreSQL 实例完成，重启不会重复修改数据。

## 最终结论

PASS（代码与数据库修复已完成；待服务重启后的浏览器回归确认）。
