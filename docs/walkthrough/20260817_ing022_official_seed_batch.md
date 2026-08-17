# ING-022 官方 Seed URL 小规模批量采集

## 交付内容

- 新增 POST /api/knowledge-v2/ingestion/official-seed-batch（canonical alias: /api/v2/kb/ingestion/official-seed-batch）。
- 请求使用严格的 OfficialUrlImportRequest 列表，最多 20 个 URL；未知字段拒绝。
- 服务端先完成整批 CAT-001 URL、厂商/产品/版本/条款预检，预检全部通过后才执行第一笔网络请求。
- 同一租户、同一官方 Host 使用并发安全的固定间隔限速器，客户端速率被限制在 1..30/min。
- 每条 URL 委托现有单 URL importer，因此 Source Registry、CAT-004 safe outbound、Import Job、内容哈希和审计边界保持唯一。
- 批量响应仅返回 batch、job、source/version ID 和稳定错误码，不返回正文、响应头或异常文本。

## 失败与重试

- 一条 URL 在预检阶段失败：整批在网络前拒绝，不产生部分采集。
- 网络/Source Registry 运行时失败：作为该条目的 SEED_IMPORT_FAILED 或既有安全错误摘要返回，其他条目继续。
- 已存在的 URL 使用既有 URL/内容幂等路径，不绕过 Source Registry。
- 每条导入仍处于现有 Import Job 的 fetched continuation，后续解析与发布由后续 ING 阶段负责。

## 验证

- backend/tests/catalog/test_ing022_official_seed_batch.py：5 passed；
- backend/tests/ai：267 passed；
- backend/tests/catalog：192 passed；
- py_compile、TypeScript lint、前端 104 项、生产 build 均通过；
- 既有 build 的 large-chunk warning 保持不变。

## 数据库、安全和回滚

- 不新增 DDL，不改变 V1 或 PostgreSQL source/version 表；
- tenant_id 只取认证主体，批量请求不能指定其他租户；
- 没有网络 transport/resolver/client_factory 的公开注入面；
- 删除/禁用该新增路由即可回滚，已有单 URL 和不可变 Source Version 不受影响。

## 已知限制

限速器是进程内状态；多 worker 生产部署需要单 worker 路由或后续接入共享控制平面。当前任务只允许小规模、受审阅 Seed URL 批量采集，不是开放式爬虫。
