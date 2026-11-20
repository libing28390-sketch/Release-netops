# EVAL-006 质量与来源指标

## 目标

在 EVAL-005 检索指标之上定义 Product、OS、Version Match、Wrong Vendor、Official Source 和 Citation Accuracy，形成可用于发布门禁的质量指标口径。

## 定义

- Product Match / OS Match：每条 Query 的规范化实体字段完全相等率。
- Version Match：版本关系必须一致；exact 还必须 release 精确一致；unspecified/conflict/unknown 不允许预测额外 release。
- Wrong Vendor Rate：预测厂商与期望不符，或在期望厂商为空时擅自猜厂商的比例。
- Official Source Rate：answer 必须至少有一个引用且全部为官方；非 answer 不应产生引用，若产生也必须全部官方。
- Citation Accuracy：answer 的引用必须非空、全部属于 Gold 且至少命中一个；非 answer 必须无引用。

## 验证

`backend/ai/services/evaluation_metrics.py` 新增六项纯函数，`scripts/knowledge_engine_v2_eval_quality_metrics_check.py` 使用正确、澄清和错误厂商样例验证边界。该模块不打开数据库；数据库为 `none`，SQLite 为 `not_used`。持久化调用方如果读取样本，只能使用 PostgreSQL。

## 结果

六项指标 smoke PASS，专项测试 1 passed；EVAL-005 原有五项指标回归保持通过。
