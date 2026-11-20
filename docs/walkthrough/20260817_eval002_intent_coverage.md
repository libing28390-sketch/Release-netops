# EVAL-002 厂商与网络意图覆盖

## 目标

在 EVAL-001 的冻结 Query 集之上，明确验证 Huawei 与 Cisco 的六类首批网络运维意图：VLAN、Interface、OSPF、SSH、NTP、Route。覆盖不是只检查厂商字段，而是为每个厂商/意图组合绑定产品、平台、OS、版本、Gold fixture 和厂商特有 CLI 语义。

## 覆盖结果

- 12 个唯一 Track：Huawei/Cisco × 6 个意图。
- 每个 Track 3 条厂商特有 CLI 示例，共 36 条。
- 每个 Track 在 EVAL-001 中有 9 条显式厂商案例，覆盖 exact、alias、prefix、typo、wrong_vendor、product_conflict、version_exact、version_conflict、no_match。
- Huawei 绑定 `huawei_vrp / CloudEngine CE6800 / CE6885-48YS8CQ / VRP V300`。
- Cisco 绑定 `cisco_iosxe / Catalyst C9300 / C9300-48P / IOS XE 17`。
- 每个 Track 的 exact 案例必须引用对应 `fixture-{vendor}-{intent}` Gold 文档。

## 验证

`scripts/knowledge_engine_v2_eval_intent_coverage_check.py` 读取两个冻结 YAML，校验 Track 矩阵、父数据集案例数、平台/产品/版本一致性、Gold 映射、CLI 语义和敏感信息。报告写入 `eval-intent-coverage-v1.manifest.json`。

这是离线评测契约，不是持久化测试：数据库为 `none`，SQLite 为 `not_used`，不访问外网。任何后续需要数据库的评测仍必须连接 PostgreSQL。

## 结果

Validator PASS：12 tracks、36 examples、每个 Track 9 条父数据集案例、无凭据或租户数据。EVAL-001 的案例 ID 与语义保持冻结。
