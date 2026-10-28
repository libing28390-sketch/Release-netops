---
schema_version: '2.0'
document_id: local.cisco.cisco_iosxe.lacp.verification.v1
title: Cisco IOS-XE 链路聚合 核验与排障（本地官网摘要）
vendor: Cisco
product_type: network_switch
document_category: troubleshooting
source_type: official_local
official_only: true
status: active
product_family: Cisco IOS-XE campus and data-center switches
product_series: Catalyst 3850/Catalyst 9300
product_model: C3850/C9300 series scope
os_family: IOS-XE
os_generation: IOS-XE 17
software_train: 17.x
software_release: IOS-XE 17.x
cli_platform: cisco_iosxe
feature_domain: switching
feature: lacp
subfeature: lacp_verification_and_troubleshooting
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 85
source_url: https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/etherchannels.html
source_urls:
- https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/etherchannels.html
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
- 链路聚合
- lacp
- Cisco
- cisco_iosxe
tags:
- local-pack
- official-reference-candidate
- cisco
- lacp
---

# Cisco IOS-XE 链路聚合 核验与排障（本地官网摘要）

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：Cisco
- 产品范围：Catalyst 3850/Catalyst 9300（精确型号仍需确认）
- CLI/系统：cisco_iosxe / IOS-XE IOS-XE 17
- 主题：链路聚合

## 官网摘要

同时核对聚合成员、协商状态、速率/双工和对端配置；单成员 Up 不代表整个聚合链路健康。 常见异常：成员未入组、聚合模式不一致、成员参数不一致或对端只形成单边聚合。 来源页面用于候选证据定位，精确命令和输出字段仍需按型号与软件版本复核。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    show etherchannel summary
    show interfaces port-channel 10

## 验证命令

    show etherchannel summary
    show lacp neighbor

## 核验重点与异常线索

- 同时核对聚合成员、协商状态、速率/双工和对端配置；单成员 Up 不代表整个聚合链路健康。
- 常见异常：成员未入组、聚合模式不一致、成员参数不一致或对端只形成单边聚合。

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/etherchannels.html
