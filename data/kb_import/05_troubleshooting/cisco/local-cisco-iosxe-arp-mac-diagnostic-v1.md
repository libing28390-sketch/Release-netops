---
schema_version: '2.0'
document_id: local.cisco.iosxe.arp_mac_diagnostic.v1
title: Cisco IOS-XE ARP 与 MAC 表排障摘要
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
feature_domain: operations
feature: diagnostic
subfeature: arp_mac
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 85
source_url: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_arp/configuration/xe-3s/arp-xe-3s-book.pdf
source_urls:
- https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_arp/configuration/xe-3s/arp-xe-3s-book.pdf
- https://www.cisco.com/c/en/us/support/ios-nx-os-software/ios-xe-17/products-command-reference-list.html
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
- Cisco
- cisco_iosxe
tags:
- local-pack
- official-reference-candidate
- cisco
- diagnostic
---

# Cisco IOS-XE ARP 与 MAC 表排障摘要

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：Cisco
- 产品范围：Catalyst 3850/Catalyst 9300（精确型号仍需确认）
- CLI/系统：cisco_iosxe / IOS-XE IOS-XE 17
- 主题：排障

## 官网摘要

ARP 表用于三层 IP 到 MAC 的解析观察，MAC 表用于二层学习路径观察； 要结合 VLAN、接口状态和设备角色判断，不能将一个表的结果直接当作另一个表的结论。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    show ip arp
    show ip arp <ip-address>
    show mac address-table
    show mac address-table dynamic
    show interfaces status

## 验证命令

    show ip arp
    show mac address-table address <mac-address>
    show interfaces <interface-id> switchport

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_arp/configuration/xe-3s/arp-xe-3s-book.pdf
- https://www.cisco.com/c/en/us/support/ios-nx-os-software/ios-xe-17/products-command-reference-list.html
