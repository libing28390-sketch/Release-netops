# Nexora 自定义知识文档导入格式

## 推荐格式

优先使用 UTF-8 编码的 `.md` 文件。文件第一个字符必须是 `---`，Front Matter 结束后再写 Markdown 正文：

```markdown
---
schema_version: "2.0"
document_id: "custom.vendor.feature.v1"
title: "文档标题"
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

# 文档标题

## 适用范围
## 前置条件
## 配置步骤
## 验证命令
## 回滚/注意事项
## 来源与版本
```

必填元数据：`schema_version`、`document_id`、`title`、`vendor`、`product_type`、`document_category`、`source_type`、`official_only`、`status`。

推荐补充：`product_model`、`os_family`、`software_release`、`cli_platform`、`feature`、`source_uri`、`source_version`。

## JSON/YAML 自定义导出

JSON/YAML 必须使用以下 envelope，而不是把正文和元数据混在任意字段中：

```json
{
  "format": "nexora-knowledge-document",
  "schema_version": "2.0",
  "metadata": { "document_id": "custom.example.v1", "title": "标题", "vendor": "Cisco", "product_type": "network_switch", "document_category": "configuration", "source_type": "user_document", "official_only": false, "status": "draft" },
  "content": "# 标题\n\n正文"
}
```

普通 JSON/YAML（没有 `format`、`metadata`、`content` envelope）仍按结构化正文导入，不会自动猜测厂商或型号。

## 约束

- UTF-8；单文件不超过 20 MB；禁止控制字符。
- `document_id` 应稳定且唯一；修改同一文档时保留 ID 并产生新版本。
- `official_only: true` 只能用于已审核的官方来源；自定义文档使用 `false`。
- 不允许写入 `tenant_id`、ACL、权限、用户身份、密码、Token、API Key、私钥等服务端字段。
- 命令和配置放在 fenced code block 中，并标明适用厂商、平台和版本。
- 导入流程为：扩展名识别 → 文件/语法校验 → Front Matter 或 envelope 解析 → 元数据预览 → 人工确认 → 清洗/安全扫描 → 切片 → Embedding → 入库。
- 解析或安全检查失败时，该文件拒绝入库或进入隔离状态；不会把原始 JSON/YAML 任意字段当作事实。

可下载模板：`nexora-knowledge-document-template.md`、`nexora-knowledge-document-template.json`。
