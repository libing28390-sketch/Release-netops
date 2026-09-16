---
schema_version: '2.0'
document_id: local.ruijie.ruijie_rgos.ospf.verification.v1
title: Ruijie RGOS OSPF 核验与排障（本地官网摘要）
vendor: Ruijie
product_type: network_switch
document_category: troubleshooting
source_type: official_local
official_only: true
status: active
product_family: Ruijie RGOS switch platforms
product_series: RG-S6220 and RGOS switches
product_model: RG-S6220 series scope
os_family: RGOS
os_generation: RGOS 10/11
software_train: RGOS
software_release: RGOS 10.x/11.x
cli_platform: ruijie_rgos
feature_domain: routing
feature: ospf
subfeature: ospf_verification_and_troubleshooting
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 85
source_url: https://www.ruijie.com.cn/fw/wt/32518/
source_urls:
- https://www.ruijie.com.cn/fw/wt/32518/
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
- Ruijie
- ruijie_rgos
tags:
- local-pack
- official-reference-candidate
- ruijie
- ospf
---

# Ruijie RGOS OSPF 核验与排障（本地官网摘要）

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：Ruijie
- 产品范围：RG-S6220 and RGOS switches（精确型号仍需确认）
- CLI/系统：ruijie_rgos / RGOS RGOS 10/11
- 主题：OSPF

## 官网摘要

按接口状态、邻居状态、区域参数和路由表顺序排查；邻居建立不代表目标前缀一定已进入路由表。 常见异常：邻居停留在非 Full 状态、区域/网络宣告不一致、MTU 或认证参数不匹配。 来源页面用于候选证据定位，精确命令和输出字段仍需按型号与软件版本复核。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    show ip ospf neighbor
    show ip ospf interface

## 验证命令

    show ip ospf neighbor
    show ip route ospf

## 核验重点与异常线索

- 按接口状态、邻居状态、区域参数和路由表顺序排查；邻居建立不代表目标前缀一定已进入路由表。
- 常见异常：邻居停留在非 Full 状态、区域/网络宣告不一致、MTU 或认证参数不匹配。

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://www.ruijie.com.cn/fw/wt/32518/
