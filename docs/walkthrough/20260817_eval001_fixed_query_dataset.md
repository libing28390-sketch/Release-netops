# EVAL-001 固定 Query 数据集

## 目标

EVAL-001 建立首批可复现的固定评测输入，作为后续 EVAL-002～EVAL-009 的共同数据源。数据集已经冻结为 120 条，案例 ID 为 `EVAL-Q001`～`EVAL-Q120`，不依赖真实生产文档、外部网络或数据库。

## 覆盖矩阵

- 厂商：Huawei、Cisco。
- 意图：VLAN、Interface、OSPF、SSH、NTP、Route。
- 每种意图 20 条：每个厂商 9 条显式厂商案例，另有 2 条缺失厂商的歧义案例。
- Query 类型：exact、alias、prefix、ambiguous、typo、wrong_vendor、product_conflict、version_exact、version_conflict、no_match；每种类型 12 条。
- 结果标签：answer、clarify、no_match，并带版本关系和稳定的 fixture 文档 ID。

## 验证

使用 `scripts/knowledge_engine_v2_eval_dataset_check.py` 解析 YAML、校验 ID 唯一性、标签约束、覆盖计数及敏感信息，并生成 SHA-256 manifest。专项测试只加载该离线 fixture。

本任务是数据集契约，不是持久化验收：数据库为 `none`，SQLite 为 `not_used`。凡是需要数据库的后续评测或回归测试，统一使用 PostgreSQL 测试连接，不以 SQLite 结果作为通过依据。

## 结果

验证结果为 PASS：120 条、10 种 Query 类型各 12 条、6 种意图各 20 条、无敏感信息。后续评测只能追加新数据集版本，不能修改本版本既有案例含义。
