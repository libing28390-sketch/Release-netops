---
schema_version: '2.0'
document_id: local.h3c.h3c_comware.bgp.verification.v1
title: H3C Comware BGP 核验与排障（本地官网摘要）
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
feature_domain: routing
feature: bgp
subfeature: bgp_verification_and_troubleshooting
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 85
source_url: https://www.h3c.com/en/d_202410/2284517_294551_0.htm
source_urls:
- https://www.h3c.com/en/d_202410/2284517_294551_0.htm
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
- BGP
- bgp
- H3C
- h3c_comware
tags:
- local-pack
- official-reference-candidate
- h3c
- bgp
---

# H3C Comware BGP 核验与排障（本地官网摘要）

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：H3C
- 产品范围：S5130/S6520X/S6850（精确型号仍需确认）
- CLI/系统：h3c_comware / Comware Comware 7
- 主题：BGP

## 官网摘要

先看会话状态和最近错误，再看地址族激活、策略和路由表；不要把 Established 直接等同于路由已发布。 常见异常：邻居未建立、地址族未激活、策略过滤前缀或下一跳不可达。 来源页面用于候选证据定位，精确命令和输出字段仍需按型号与软件版本复核。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    display bgp peer ipv4
    display bgp routing-table ipv4

## 验证命令

    display bgp peer ipv4
    display ip routing-table protocol bgp

## 核验重点与异常线索

- 先看会话状态和最近错误，再看地址族激活、策略和路由表；不要把 Established 直接等同于路由已发布。
- 常见异常：邻居未建立、地址族未激活、策略过滤前缀或下一跳不可达。

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://www.h3c.com/en/d_202410/2284517_294551_0.htm
