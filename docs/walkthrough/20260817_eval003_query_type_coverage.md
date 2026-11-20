# EVAL-003 Query 类型覆盖

## 目标

验证固定数据集中的七类 Query 边界：Exact、Alias、Prefix、Ambiguous、Typo、Wrong Vendor、Product Conflict。该任务把“有案例”提升为“结果边界可执行”：正向案例必须有引用，歧义必须澄清，错误厂商和产品冲突必须拒答。

## 规则

- Exact、Alias、Prefix、Typo：每类 12 条，结果为 `answer`，必须有 Gold fixture 和 citation。
- Ambiguous：12 条，厂商和产品身份为空，结果为 `clarify`，至少保留两个候选 Gold fixture，不猜厂商。
- Wrong Vendor：12 条，查询同时出现目标厂商和另一厂商语法，结果为 `no_match`，Gold 为空。
- Product Conflict：12 条，查询包含目标厂商系列与另一厂商型号，结果为 `no_match`，Gold 为空。

## 验证

`scripts/knowledge_engine_v2_eval_query_type_coverage_check.py` 读取 EVAL-001 冻结集和 EVAL-003 类型契约，检查计数、结果标签、引用、厂商/产品冲突词和敏感信息，并生成机器可读 manifest。

本任务是离线评测规则，不连接数据库、不访问外网；数据库为 `none`，SQLite 为 `not_used`。需要数据库的后续评测统一使用 PostgreSQL。

## 结果

Validator PASS：七类各 12 条；正向 4 类均为 answer，Ambiguous 全部 clarify，Wrong Vendor/Product Conflict 全部 no_match；专项测试 1 passed。
