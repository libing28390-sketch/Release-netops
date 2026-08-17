# EVAL-004 版本状态覆盖

## 目标

覆盖指定版本、未指定版本、冲突版本和未知版本四类版本状态，并将未知版本作为独立的可审计 fixture，而不是把普通 no_match 误标为未知版本。

## 覆盖矩阵

- 指定版本：复用 EVAL-001 的 12 条 `version_exact`，期望 exact、answer、有引用。
- 未指定版本：复用 EVAL-001 的 12 条 `exact`，请求没有 release，期望 unspecified、answer、有引用。
- 冲突版本：复用 EVAL-001 的 12 条 `version_conflict`，期望 conflict、no_match、Gold 为空。
- 未知版本：新增 12 条 `EVAL-V004-U001`～`EVAL-V004-U012`，覆盖 Huawei/Cisco × 六类意图；请求版本不在 supported_versions，期望 unknown、no_match、Gold 为空。

## 验证

`scripts/knowledge_engine_v2_eval_version_coverage_check.py` 校验父数据集映射、版本关系、结果标签、引用规则、未知版本不重叠和厂商/意图矩阵，并输出机器可读 manifest。

这是离线评测 fixture，不连接数据库、不访问外网；数据库为 `none`，SQLite 为 `not_used`。任何持久化评测继续只使用 PostgreSQL。

## 结果

Validator PASS：四类各 12 条，共 48 条版本状态样本；12 条未知版本覆盖矩阵完整，专项测试 1 passed。
