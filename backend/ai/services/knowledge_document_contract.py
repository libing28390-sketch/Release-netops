"""Explicit contract for operator-authored knowledge documents.

The ingestion API still accepts legacy body-only text files, but this contract
defines the deterministic format for documents created outside Nexora.  The
same metadata keys are used by Markdown Front Matter and by the optional JSON
/ YAML document envelope.
"""

from __future__ import annotations

from typing import Final


DOCUMENT_CONTRACT_NAME: Final = "nexora-knowledge-document"
DOCUMENT_CONTRACT_VERSION: Final = "2.0"
SUPPORTED_METADATA_SCHEMA_VERSIONS: Final = ("1.0", "1.1", "2.0")

REQUIRED_METADATA_FIELDS: Final = (
    "schema_version",
    "document_id",
    "title",
    "vendor",
    "product_type",
    "document_category",
    "source_type",
    "official_only",
    "status",
)

# These fields are server-owned and must never be supplied by a portable
# document.  They are deliberately listed for the UI/docs contract as well
# as for future schema validation.
FORBIDDEN_METADATA_FIELDS: Final = (
    "tenant_id",
    "workspace_id",
    "user_id",
    "created_by",
    "updated_by",
    "acl",
    "acl_json",
    "permissions",
    "roles",
    "authorization",
    "api_key",
    "password",
    "secret",
    "token",
    "private_key",
    "content",
    "body",
)

RECOMMENDED_BODY_SECTIONS: Final = (
    "适用范围",
    "前置条件",
    "配置步骤",
    "验证命令",
    "回滚/注意事项",
    "来源与版本",
)


def markdown_template() -> str:
    """Return a safe, operator-editable Markdown template."""

    return """---
schema_version: \"2.0\"
document_id: \"custom.huawei.s5735.vlan.v1\"
title: \"华为 S5735 VLAN 基础配置\"
vendor: \"Huawei\"
product_type: \"network_switch\"
document_category: \"configuration\"
source_type: \"user_document\"
official_only: false
status: \"draft\"
product_family: \"campus_switch\"
product_series: \"S5735\"
product_model: \"CloudEngine S5735-S24P4XE-V2\"
os_family: \"VRP\"
os_generation: \"V600\"
software_train: \"V600R023\"
software_release: \"V600R023C10\"
cli_platform: \"huawei_vrp_v600\"
feature_domain: \"switching\"
feature: \"vlan\"
subfeature: \"access_port\"
risk_level: \"low\"
verification_level: \"operator_reviewed\"
rag_priority: 80
source_uri: \"https://example.invalid/replace-with-source\"
source_version: \"replace-me\"
tags:
  - \"campus\"
  - \"vlan\"
keywords:
  - \"VLAN\"
  - \"access port\"
---

# 华为 S5735 VLAN 基础配置

## 适用范围

说明适用的设备型号、软件版本、CLI 平台和园区网/数据中心场景。

## 前置条件

- 说明执行前需要确认的接口、VLAN 或权限条件。
- 不要填写真实密码、密钥、SNMP community 或 Token。

## 配置步骤

```text
system-view
vlan batch 10
interface GigabitEthernet 0/0/1
 port link-type access
 port default vlan 10
```

## 验证命令

```text
display vlan 10
display current-configuration interface GigabitEthernet 0/0/1
```

## 回滚/注意事项

说明回滚命令、风险和不能跨厂商复用的语法。

## 来源与版本

填写可公开访问的来源 URL、文档版本和核验日期；内部文档可填写内部文档编号，不要填写租户、ACL 或身份字段。
"""


def json_template() -> str:
    """Return the equivalent JSON document-envelope template."""

    return """{
  \"format\": \"nexora-knowledge-document\",
  \"schema_version\": \"2.0\",
  \"metadata\": {
    \"document_id\": \"custom.huawei.s5735.vlan.v1\",
    \"title\": \"华为 S5735 VLAN 基础配置\",
    \"vendor\": \"Huawei\",
    \"product_type\": \"network_switch\",
    \"document_category\": \"configuration\",
    \"source_type\": \"user_document\",
    \"official_only\": false,
    \"status\": \"draft\",
    \"product_model\": \"CloudEngine S5735-S24P4XE-V2\",
    \"os_family\": \"VRP\",
    \"cli_platform\": \"huawei_vrp_v600\",
    \"feature_domain\": \"switching\",
    \"feature\": \"vlan\",
    \"risk_level\": \"low\",
    \"verification_level\": \"operator_reviewed\",
    \"rag_priority\": 80
  },
  \"content\": \"# 华为 S5735 VLAN 基础配置\\n\\n## 适用范围\\n\\n填写设备型号和版本。\\n\\n## 配置步骤\\n\\n```text\\nsystem-view\\nvlan batch 10\\n```\"
}
"""


__all__ = [
    "DOCUMENT_CONTRACT_NAME",
    "DOCUMENT_CONTRACT_VERSION",
    "FORBIDDEN_METADATA_FIELDS",
    "RECOMMENDED_BODY_SECTIONS",
    "REQUIRED_METADATA_FIELDS",
    "SUPPORTED_METADATA_SCHEMA_VERSIONS",
    "json_template",
    "markdown_template",
]
