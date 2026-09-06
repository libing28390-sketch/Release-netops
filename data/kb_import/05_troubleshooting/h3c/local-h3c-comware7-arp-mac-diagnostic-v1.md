---
schema_version: '2.0'
document_id: local.h3c.comware7.arp_mac_diagnostic.v1
title: H3C Comware 7 ARP 与 MAC 表排障摘要
vendor: H3C
product_type: network_switch
document_category: troubleshooting
source_type: official_local
official_only: true
status: active
product_family: H3C Comware switch platforms
product_series: S5130/S6520X/S6850
product_model: S5130/S6520X/S6850 series scope
os_family: Comware
os_generation: Comware 7
software_train: Comware 7
software_release: Comware 7 R66xx/R67xx
cli_platform: h3c_comware
feature_domain: operations
feature: diagnostic
subfeature: arp_mac
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 85
source_url: https://www.h3c.com/en/Support/Resource_Center/EN/Home/Security/00-Public/Reference_Guides/Command_References/H3C_IPS_Comware_7_CR%28R8560_R8660%29/10/202205/1607637_294551_0.htm
source_urls:
- https://www.h3c.com/en/Support/Resource_Center/EN/Home/Security/00-Public/Reference_Guides/Command_References/H3C_IPS_Comware_7_CR%28R8560_R8660%29/10/202205/1607637_294551_0.htm
- https://www.h3c.com/en/d_202602/2752476_294551_0.htm
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
- 排障
- diagnostic
- H3C
- h3c_comware
tags:
- local-pack
- official-reference-candidate
- h3c
- diagnostic
---

# H3C Comware 7 ARP 与 MAC 表排障摘要

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：H3C
- 产品范围：S5130/S6520X/S6850（精确型号仍需确认）
- CLI/系统：h3c_comware / Comware Comware 7
- 主题：排障

## 官网摘要

ARP 与 MAC 输出要结合 VLAN、接口和网关角色判断；文章只提供排障顺序， 不承诺所有 Comware 7 型号都支持完全相同的过滤参数。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    display arp
    display arp all
    display mac-address
    display mac-address vlan 10

## 验证命令

    display arp all
    display mac-address interface GigabitEthernet 1/0/1
    display interface brief

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://www.h3c.com/en/Support/Resource_Center/EN/Home/Security/00-Public/Reference_Guides/Command_References/H3C_IPS_Comware_7_CR%28R8560_R8660%29/10/202205/1607637_294551_0.htm
- https://www.h3c.com/en/d_202602/2752476_294551_0.htm
