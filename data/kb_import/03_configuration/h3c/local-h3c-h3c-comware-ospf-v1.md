---
schema_version: '2.0'
document_id: local.h3c.h3c_comware.ospf.v1
title: H3C Comware OSPF 邻居与区域配置（本地官网摘要）
vendor: H3C
product_type: network_switch
document_category: configuration
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
feature_domain: routing
feature: ospf
subfeature: ospf
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 75
source_url: https://www.h3c.com/en/d_200806/607561_294551_0.htm
source_urls:
- https://www.h3c.com/en/d_200806/607561_294551_0.htm
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
- OSPF
- ospf
- H3C
- h3c_comware
tags:
- local-pack
- official-reference-candidate
- h3c
- ospf
---

# H3C Comware OSPF 邻居与区域配置（本地官网摘要）

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：H3C
- 产品范围：S5130/S6520X/S6850（精确型号仍需确认）
- CLI/系统：h3c_comware / Comware Comware 7
- 主题：OSPF

## 官网摘要

来源页面用于 H3C OSPF 的候选证据。具体型号、软件版本、板卡能力和命令参数必须在目标设备的版本化命令参考中复核。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    system-view
    ospf 1
    area 0.0.0.0
    network 192.0.2.0 0.0.0.255

## 验证命令

    display ospf peer
    display ip routing-table protocol ospf

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://www.h3c.com/en/d_200806/607561_294551_0.htm
