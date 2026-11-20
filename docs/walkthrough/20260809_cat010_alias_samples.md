# CAT-010 Alias Samples Walkthrough

## 目标

验证首批网络设备型号别名在没有完整 SKU 时不会误选型号、厂商或驱动。

## 覆盖样本

- Huawei：`CE68`、`CE688`、`CE6885`、`CE6885-48YS8CQ`、`CloudEngine CE6885-48YS8CQ`
- Cisco：`C9300`、`Catalyst93`、`C9300-48P`
- 未知：`C9400-999Z` → `UNKNOWN` 并要求澄清

## 验证结果

所有系列前缀都返回候选集；完整 SKU 仅在激活审核记录后返回唯一结果。专项测试 3 项通过，CAT/DB/RAG 回归 96 项通过，V1 baseline 10/10，前端 lint/build 通过。

## 约束

本任务只添加目录样本和契约测试，无生产 DDL、无驱动授权、无网络写操作。
