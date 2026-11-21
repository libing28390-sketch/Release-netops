# EVAL-008 Golden Answer 与引用标注

## 目标

建立人工评测的可重复标注流程：每条 Golden Answer 必须同时记录适用厂商、产品、OS、软件训练/版本关系和逐条引用；冻结后不可原地改写。

## 工作流

1. 主标注人从冻结 Query ID 起草答案和适用范围。
2. 引用标注人验证官方 Gold 文档、source version、locator、claim ID 和 official 标记。
3. 独立 Reviewer 检查厂商/产品/OS/版本、答案结论和引用边界。
4. 有分歧进入 adjudication，裁决后生成新冻结修订集。

本批冻结 `nexora-kb-eval-golden-v1-20260817`，12 条覆盖 Huawei/Cisco × VLAN/Interface/OSPF/SSH/NTP/Route，每条由不同 annotator/reviewer 复核并有一个官方 fixture 引用。Clarify/no-match 的规则要求不产生 citation，候选文档只能作为独立候选字段。

## 验证

`scripts/knowledge_engine_v2_eval_golden_annotation_check.py` 校验父 Query、适用版本、Gold 归属、官方引用、双人复核、冻结状态和敏感信息，并生成 manifest。

这是离线人工标注 fixture：数据库为 `none`，SQLite 为 `not_used`，不访问外网。任何从数据库读取 Query 的后续评测只使用 PostgreSQL。

## 结果

12 条 annotations、12 条 citations、12 个厂商/意图组合全部 frozen，专项测试 1 passed。
