---
schema_version: '2.0'
document_id: local.huawei.vrp.interface_status_ce6885.v1
title: Huawei CE6885 接口状态与上联核验摘要
vendor: Huawei
product_type: network_switch
document_category: cli_output
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
feature_domain: operations
feature: interface
subfeature: ce6885_status_and_uplink
risk_level: low
verification_level: official_reference_source_checked
rag_priority: 85
source_url: https://info.support.huawei.com/info-finder/search-center/en/enterprise/wlan/ce6885-48ys8cq-pid-257795345/commands
source_urls:
- https://info.support.huawei.com/info-finder/search-center/en/enterprise/wlan/ce6885-48ys8cq-pid-257795345/commands
- https://info.support.huawei.com/enterprise/en/doc/EDOC1100333403/cdd85713/basic-interface-configuration-commands
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
- 接口状态
- interface
- Huawei
- huawei_vrp
tags:
- local-pack
- official-reference-candidate
- huawei
- interface
---

# Huawei CE6885 接口状态与上联核验摘要

> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，不等同于生产发布或已完成人工 Gold 审核。

## 适用范围

- 厂商：Huawei
- 产品范围：CE6800/CE12800/S5700/S6700（精确型号仍需确认）
- CLI/系统：huawei_vrp / VRP VRP8
- 主题：接口状态

## 官网摘要

Huawei 官方命令中心将 CE6885-48YS8CQ 作为具体产品范围；本候选用于接口状态、 上联接口和 IP 接口摘要的检索定位。命令参数、板卡接口名称和软件版本仍需在目标设备 的对应版本命令参考中逐项确认。

本文只保留用于检索和人工复核的命令关键词，不复制官网全文；命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。

## 配置或命令摘要

    display interface brief
    display interface <uplink-interface>
    display ip interface brief

## 验证命令

    display interface brief
    display interface <uplink-interface>
    display ip interface brief

## 回滚/注意事项

- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。
- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。
- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。

## 来源与版本

- 核验日期：2026-09-05
- 来源类型：public_official_page
- https://info.support.huawei.com/info-finder/search-center/en/enterprise/wlan/ce6885-48ys8cq-pid-257795345/commands
- https://info.support.huawei.com/enterprise/en/doc/EDOC1100333403/cdd85713/basic-interface-configuration-commands
