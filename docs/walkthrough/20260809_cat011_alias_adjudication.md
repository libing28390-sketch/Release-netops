# CAT-011 Alias Adjudication Walkthrough

## 流程

1. 两个租户内不同产品共用同一个 exact alias 时，服务建立确定性 conflict group，并返回两个候选。
2. 候选响应标记 `requires_clarification` 和 `manual_review_required`，不会自动选择第一条。
3. 审核员通过 `approve` 选择一条记录；竞争记录转为 rejected，exact/canonical 才能唯一解析。
4. `reject` 让解析结果保持 UNKNOWN；`reset` 将冲突恢复为 pending_review。

## 安全边界

候选服务始终按 tenant 过滤；prefix/trigram 永远是候选而非设备驱动授权。审核备注和身份字段拒绝 Authorization、token、secret 等敏感内容。

## 验证

专项 5 项、CAT-009..011 回归 17 项、CAT/DB/RAG 回归 101 项、V1 baseline 10/10 均通过；无生产 DDL。
