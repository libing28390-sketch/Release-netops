---
schema_version: '2.0'
document_id: local.huawei.vrp.port_security.v1
title: Huawei VRP 端口安全与安全动态 MAC 摘要
vendor: Huawei
product_type: network_switch
document_category: configuration
source_type: official_local
official_only: true
status: active
product_family: Huawei VRP network switches
product_series: CE6800/CE12800/S5700/S6700
product_model: CE6800/CE12800/S5700/S6700 series scope
os_family: VRP
os_generation: VRP8
software_train: V200/V300
software_release: V200R023/V300R024
cli_platform: huawei_vrp
feature_domain: security
feature: port_security
subfeature: secure_dynamic_mac
risk_level: medium
verification_level: official_reference_source_checked
rag_priority: 75
source_url: https://info.support.huawei.com/hedex/api/pages/EDOC1000053358/YEF0907R/25/resources/en-us_task_0133020498.html
source_urls:
- https://info.support.huawei.com/hedex/api/pages/EDOC1000053358/YEF0907R/25/resources/en-us_task_0133020498.html
source_checked_at: '2026-09-05'
source_version: official page checked 2026-09-05
source_reference_type: public_official_page
source_trust_level: official
content_origin: authored_local_summary
review_status: source_provenance_verified
test_only: true
production_eligible: false
pack_id: nexora-kb-official-local-4vendor-v1
external_network: forbidden
keywords:
- 端口安全
- port_security
- Huawei
- huawei_vrp
tags:
- local-pack
- official-reference-candidate
- huawei
- port_security
---

# Huawei VRP 端口安全与安全动态 MAC 摘要

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：Huawei
- 产品范围：CE6800/CE12800/S5700/S6700（精确型号仍需确认）
- CLI/系统：huawei_vrp / VRP VRP8
- 主题：端口安全

## 官网摘要

官网页面覆盖 port-security enable、最大 MAC 数量和违规动作等命令； 端口类型、版本支持、保护动作含义必须以目标设备的命令参考为准。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    system-view
    interface GigabitEthernet 0/0/1
    port-security enable
    port-security maximum 2
    port-security protect-action restrict
    commit

## 验证命令

    display current-configuration interface GigabitEthernet 0/0/1
    display mac-address interface GigabitEthernet 0/0/1

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://info.support.huawei.com/hedex/api/pages/EDOC1000053358/YEF0907R/25/resources/en-us_task_0133020498.html
