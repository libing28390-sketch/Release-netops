# 2026-08-17 OBS-003 Trace 与日志脱敏

## 验证目标

确保 Trace 和日志落盘前已经脱敏，raw query 不离开请求作用域；同时不让 Provider 错误、Prompt、配置正文、Token 或私钥进入审计、API 或日志。

## 实现结果

Trace store 的所有文本字段经过 bounded `sanitize_log_text`，raw query 只记录 hash/长度/捕获标志。AI Gateway/Assistant 将异常改为稳定 code/type；统一 `SanitizeFilter` 同时挂载到 root、console 和 rotating file handlers，覆盖 assignment、Bearer 与 PEM private key。

## 兼容修复

在门禁回归中发现 DB-022 的旧 marker 与强类型 payload 不一致、Source Registry refresh API 的直接调用默认值是 FastAPI `Query` sentinel、摘要排序使用不存在的 `observed_at` 字段。保留强类型实现，只增加迁移标记，并将刷新历史改为 `checked_at` 排序、显式投影 `version_signal`。

## 验证

OBS focused 10 passed，AI 238 passed，Database 188 passed/2 documented skips，Catalog 192 passed，lint/build/compile/diff 与 V1 PostgreSQL 10/10 全部通过。
