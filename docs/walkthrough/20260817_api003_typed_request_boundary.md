# 2026-08-17 API-003 typed request boundary

## 验证目标

确认 AI Copilot、AI Security Gateway、只读诊断和 Knowledge V2 稳定入口不再接受裸 `dict` 请求体。

## 结果

AST 审计没有发现稳定 body 参数使用 `dict`/`Dict[str, Any]`。Security、Copilot、Diagnostics 回归 31/31，API-002/API boundary/CAT-015 回归 11/11，编译与 diff check 通过。诊断合同额外拒绝 `write_operations_enabled=true`，保持只读权限边界。
