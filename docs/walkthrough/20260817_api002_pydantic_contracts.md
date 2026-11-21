# 2026-08-17 API-002 Pydantic contracts

## 验证目标

验证 Provider、Model、Source、Document、Product、Alias、Import、Search 的稳定请求边界均有可测试的 Pydantic 契约，并拒绝未知字段、越界值和敏感字段回显。

## 已验证路径

1. Provider key rotate/invalidate 与 Model access/default 使用显式请求模型。
2. Catalog version bundle 使用嵌套 Product/Alias 模型，不再使用 `list[dict]`。
3. Knowledge Base、Reindex、Directory、Document 与 Search filter 使用 bounded contract。
4. CAT-015、RAG、分页和 API v2 boundary 回归保持通过。

## 结果

焦点契约 4/4、回归 14/14 + 8/8、Python compile 和 diff check 全部通过。PostgreSQL schema 未改变，未执行生产写入。
