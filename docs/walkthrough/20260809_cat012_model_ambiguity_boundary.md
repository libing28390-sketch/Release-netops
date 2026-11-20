# CAT-012 Model Ambiguity Boundary Walkthrough

## 典型结果

- `CE68` 命中多个同系列型号：允许读取 CE6800 系列能力，必须追问具体 SKU。
- `C9300` 命中多个 C9300 SKU：不选择 `cisco_ios` 或任何驱动，不生成写命令。
- 跨厂商或 UNKNOWN：只允许通用网络知识，必须追问 vendor/family/series/model。
- 已有一个完整审核型号与完整平台上下文：可使用 model scope，但仍不授予写权限。

## 验证

专项 5 项、CAT/DB/RAG 回归 106 项、V1 baseline 10/10、编译/YAML/秘钥扫描/diff/lint/build 全部通过；无生产 DDL。
