---
schema_version: '2.0'
document_id: local.huawei.vrp.vxlan_evpn.v1
title: Huawei CE12800 VXLAN/EVPN 网关配置核验摘要
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
feature_domain: overlay
feature: vxlan
subfeature: bgp_evpn
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 75
source_url: https://support.huawei.com/enterprise/en/doc/EDOC1000039339/5e782f6/example-for-configuring-nfvi-distributed-gateways-symmetric-mode
source_urls:
- https://support.huawei.com/enterprise/en/doc/EDOC1000039339/5e782f6/example-for-configuring-nfvi-distributed-gateways-symmetric-mode
- https://support.huawei.com/enterprise/en/doc/EDOC1100334532/a74c6374/vxlan-basics
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
- VXLAN/EVPN
- vxlan
- Huawei
- huawei_vrp
tags:
- local-pack
- official-reference-candidate
- huawei
- vxlan
---

# Huawei CE12800 VXLAN/EVPN 网关配置核验摘要

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：Huawei
- 产品范围：CE6800/CE12800/S5700/S6700（精确型号仍需确认）
- CLI/系统：huawei_vrp / VRP VRP8
- 主题：VXLAN/EVPN

## 官网摘要

官网示例明确涉及 CE12800/CE16800 A 系列卡，但该来源是分布式网关示例； 不得据此把“集中式网关”当成已验证事实，集中式/分布式模式和软件版本需要逐项核对。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    system-view
    bridge-domain 10
    vxlan vni 5010
    interface Nve1
    source 1.1.1.1
    bgp 65000
    l2vpn-family evpn
    peer 192.0.2.2 as-number 65001
    peer 192.0.2.2 enable

## 验证命令

    display vxlan tunnel
    display bgp evpn peer

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://support.huawei.com/enterprise/en/doc/EDOC1000039339/5e782f6/example-for-configuring-nfvi-distributed-gateways-symmetric-mode
- https://support.huawei.com/enterprise/en/doc/EDOC1100334532/a74c6374/vxlan-basics
