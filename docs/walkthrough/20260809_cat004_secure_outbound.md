# CAT-004 Secure Outbound Walkthrough

## 验证范围

本 walkthrough 使用 `httpx.MockTransport` 和固定公共测试地址解析器，覆盖成功抓取、同主机后代路径重定向、跨主机/降级/路径/query/编码逃逸拒绝、DNS 私网/元数据拒绝、Content-Type/Content-Length/stream 上限、4xx 不重试、5xx 有界重试、active/valid gate、Source Version hash 和 audit。

## 结果

- CAT-004 focused: 14 passed。
- CAT-003 + CAT-004 + m0116: 20 passed。
- CAT/DB/migration compatibility: 54 passed, 1 skipped（SQLite-only boundary）。
- compileall、secret scan、`npm run lint`、`npm run build`、`git diff --check` 均通过。

## 运行时路径

1. API `POST /api/knowledge-v2/sources/{source_id}/fetch` 经过 `knowledge_source.create` RBAC。
2. `collect_source` 读取 tenant-scoped active/valid/enabled Source Registry，记录 `fetch_started`。
3. `safe_fetch` 在每次连接尝试前 DNS gate，发送无环境代理的 HTTPS 请求；每个 Location 都重新验证。
4. GET 只将正文短暂保存在内存，`record_source_version` 写入 SHA-256/大小/解析器/来源 URL/HTTP 元数据；API 永不返回正文。
5. 失败写入稳定 `fetch_failed` 审计，成功由 Source Version 写入 `fetch_completed`。

## 回滚演练

禁用或隔离来源行即可停止后续抓取，不删除版本 hash 或 V1 数据；没有生产 DDL 需要回滚。
