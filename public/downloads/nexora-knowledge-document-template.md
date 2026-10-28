---
schema_version: "2.0"
document_id: "custom.huawei.s5735.vlan.v1"
title: "华为 S5735 VLAN 基础配置"
vendor: "Huawei"
product_type: "network_switch"
document_category: "configuration"
source_type: "user_document"
official_only: false
status: "draft"
product_model: "CloudEngine S5735-S24P4XE-V2"
os_family: "VRP"
cli_platform: "huawei_vrp_v600"
feature_domain: "switching"
feature: "vlan"
risk_level: "low"
verification_level: "operator_reviewed"
rag_priority: 80
---

# 华为 S5735 VLAN 基础配置

## 适用范围

填写设备型号、软件版本、CLI 平台和园区网/数据中心适用范围。

## 前置条件

填写执行前需要确认的接口、VLAN 和权限条件。不要填写真实凭据、Token、租户或 ACL 信息。

## 配置步骤

```text
system-view
vlan batch 10
```

## 验证命令

```text
display vlan 10
```

## 回滚/注意事项

填写回滚命令和风险。
