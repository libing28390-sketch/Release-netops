# Knowledge Engine 官方文档清单构建 walkthrough

## 目标

按照官方来源清单、CAT-001 精确主机/路径白名单和 CAT-002 文档类型契约，使用
PostgreSQL 生产配置完成 48 个来源的逐项终态闭环，以及可采集来源的注册、抓取、清洗、
分块、向量化和 V1 投影。

## 本轮结果

| 厂商 | active/valid | discovery-only | blocked |
| --- | ---: | ---: | ---: |
| Huawei | 2 | 1 | 8 |
| H3C | 9 | 1 | 0 |
| Ruijie | 8 | 6 | 0 |
| Cisco | 8 | 4 | 1 |
| 合计 | 27 | 12 | 9 |

受控阻塞项：

- Huawei 4 个来源被官网 robots 策略拒绝自动采集，已在 PG 中停用，未绕过策略。
- Huawei 3 个来源的 robots 文件不可用，已停用并等待站点恢复或厂商复核。
- Huawei 静态/动态路由来源只抓到 3800 字节通用页面壳，且没有 V1/V2 文档，已停用。
- Cisco Catalyst 9300 IOS XE 17.18 完整 PDF 在安全采集客户端下超时，已停用，等待替代官方 HTML 页面或厂商访问复核。
- 清单中已无 `candidate_*` 状态；所有 48 个来源均有可审计终态。

## 数据库验收

- 最新迁移：`188 knowledge_v2_troubleshooting_source_kind`。
- PG 官方来源：27 个 active/valid、9 个 disabled/valid；12 个 discovery-only 未注册。
- 27 个 active 来源全部具有 Source Version 和 V1 文档，其中 26 个具有 V2 文档。
- PG 当前文档：268 篇；分块：2611 个。
- 官方 active V1：114 篇、2139 个分块。
- 官方分块向量：2139/2139 有向量，维度统一为 1536，embedding model/mode/contract 各自只有一个值。
- 官方 active 分块重复 `content_hash`：0 组。
- V2 文档版本已生成并保持 `draft`，V1 投影为 `active`，符合当前灰度生命周期边界。

## 代码与契约调整

- CAT-001 增量白名单加入 H3C、锐捷、Huawei、Cisco 的精确文档路径，并补充 Cisco 17.18 路径。
- CAT-002 增加 `troubleshooting_guide` 类型及字段、解析和分类规则。
- PG/SQLite 迁移支持 `troubleshooting_guide` 来源类型。
- 官方导入保留产品、平台、OS、版本和文档类别元数据；排障文档映射到 `troubleshooting`。
- 分块阶段增加同文档精确重复内容去重；采集管线区分 robots 拒绝与 robots 不可用。
- 增加可审计的清单构建脚本，默认 dry-run，正式写入必须显式 `--apply`、审核人和条款状态。

## 验证命令

```text
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests/database/test_m0116_knowledge_v2_source_registry.py backend/tests/database/test_m0188_knowledge_v2_troubleshooting_source_kind.py backend/tests/ai/test_chunking_v2.py backend/tests/ai/test_ingestion_pipeline_state_machine.py backend/tests/catalog/test_cat002_official_source_types.py backend/tests/catalog/test_cat019_allowlist_extensions.py backend/tests/catalog/test_cat020_troubleshooting_source_type.py backend/tests/catalog/test_ing002_official_url_import.py backend/tests/catalog/test_ing023_collection_ops.py -q -p no:cacheprovider
42 passed in 114.07s

.venv\Scripts\python.exe -m pytest backend/tests/catalog/test_cat002_official_source_types.py backend/tests/catalog/test_cat019_allowlist_extensions.py -q -p no:cacheprovider
7 passed

.venv\Scripts\python.exe -m pytest backend/tests/catalog/test_cat019_allowlist_extensions.py backend/tests/catalog/test_cat002_official_source_types.py backend/tests/catalog/test_cat020_troubleshooting_source_type.py -q -p no:cacheprovider
10 passed in 31.00s

.venv\Scripts\python.exe -m compileall -q backend/ai backend/services backend/database/migrations/m0116_knowledge_v2_source_registry.py backend/database/migrations/m0188_knowledge_v2_troubleshooting_source_kind.py scripts/knowledge_engine_v2_build_official_catalog.py
```

全量 `pytest backend/tests` 已启动，但在长时间运行中出现多项失败/错误且未等到完整汇总，随后按用户要求停止；本轮验收以针对性测试和 PG 只读完整性查询为准。

## 后续

1. 对 Huawei blocked 来源完成人工浏览器/条款复核，获得允许的自动采集方式后再启用。
2. 为 Cisco 17.18 配置指南选择可访问的官方 HTML 章节或完成 PDF 访问复核，再重新启用该来源。
3. 通过知识库生命周期审批将 V2 `draft` 版本推进到目标发布状态，并执行正式召回评测集。
