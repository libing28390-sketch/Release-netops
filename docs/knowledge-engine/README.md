# AI 知识库文档说明

本目录是单一 V1 知识库的配置、契约、评估数据和历史设计记录入口。

现行运行时只认：

- `governance/official-document-source-catalog.yaml`：官方来源清单与采集终态。
- `architecture/CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml` 及扩展：官方 URL 精确白名单。
- `architecture/CAT-002-OFFICIAL-SOURCE-TYPES.yaml`：来源类型定义。
- `catalog/`：产品/平台知识目录。
- `eval/`：V1 固定问题集、评估数据和报告。

目录内文件名或正文中仍出现 V2、shadow、rollout 的内容是迁移前设计和审计证据，不是第二套运行时，也不得作为新开发入口。最终数据契约见 `docs/knowledge-base-v1-data-contract.md`；退役表和回滚方式见仓库根目录 `handoff.md`。
