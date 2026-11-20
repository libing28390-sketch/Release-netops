# KUI-016 RAG Evaluation / 回归结果

## 页面入口

知识库管理页顶部切换到 `RAG Evaluation / 回归`。首次打开显示固定 PostgreSQL V1 基线的用例数量和“未运行”状态；点击“运行回归”后，服务端在临时事务中执行并回滚。

## 页面验证点

1. 指标卡显示 Retrieval Accuracy、Citation Accuracy、Citation Recall、Wrong Vendor、Version Conflict。
2. 门禁显示每个指标的实际值、阈值和 PASS/FAIL。
3. 延迟显示 Average/P50/P95/Max；用例表支持窄屏横向滚动。
4. 页面不展示 SQL、debug plan、文档 ID、Chunk 正文或凭据。
5. PostgreSQL 不可用时只显示稳定错误，不改变知识库数据。

## 已验证

- PostgreSQL KUI-016 probe：PASS，10/10 固定用例通过，事务回滚和安全投影通过。
- 前端组件测试：2 passed；全量前端：17 files / 92 tests passed。
