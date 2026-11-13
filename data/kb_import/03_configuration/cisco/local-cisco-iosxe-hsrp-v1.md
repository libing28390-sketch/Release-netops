---
schema_version: '2.0'
document_id: local.cisco.iosxe.hsrp.v1
title: Cisco IOS-XE HSRP 虚拟网关配置摘要
vendor: Cisco
product_type: network_switch
document_category: configuration
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
feature_domain: reliability
feature: hsrp
subfeature: virtual_gateway
risk_level: medium
verification_level: official_reference_source_checked
rag_priority: 75
source_url: https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ntw-servs/b-network-services/m_fhp-hsrp-0.html
source_urls:
- https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ntw-servs/b-network-services/m_fhp-hsrp-0.html
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
- HSRP
- hsrp
- Cisco
- cisco_iosxe
tags:
- local-pack
- official-reference-candidate
- cisco
- hsrp
---

# Cisco IOS-XE HSRP 虚拟网关配置摘要

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：Cisco
- 产品范围：Catalyst 3850/Catalyst 9300（精确型号仍需确认）
- CLI/系统：cisco_iosxe / IOS-XE IOS-XE 17
- 主题：HSRP

## 官网摘要

HSRP 优先级、抢占和跟踪参数会影响主备切换；接口地址、组号和软件版本 需按实际拓扑核对，实施前必须有变更审批与回滚方案。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    interface Vlan10
    ip address 192.0.2.2 255.255.255.0
    standby 10 ip 192.0.2.1
    standby 10 priority 110
    standby 10 preempt

## 验证命令

    show standby brief
    show standby Vlan10

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ntw-servs/b-network-services/m_fhp-hsrp-0.html
