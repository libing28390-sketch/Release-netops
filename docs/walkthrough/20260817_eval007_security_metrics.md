# EVAL-007 安全评测指标

## 目标

定义秘密泄漏、Prompt Injection、越权和外发策略四类安全指标，并用无生产副作用的合成 fixture 验证检测和 fail-closed 判定。

## 指标

- Secret Leakage Rate：匹配 secret-shaped marker 的 fixture / secret fixture 总数；报告只输出 rate，不输出匹配值。
- Prompt Injection Block Rate：高置信度注入尝试中被阻断的比例；无注入样本时为 1。
- Authorization Violation Rate：未授权但实际执行的动作 / 未授权尝试。
- Outbound Policy Compliance Rate：允许请求必须已发送、目的地允许且已脱敏；拒绝请求必须未发送。

## Fixture 与验证

`eval-security-cases-v1.yaml` 包含 9 条合成案例：2 条秘密检测、2 条注入、2 条越权和 3 条外发。秘密测试使用拆分的 fixture-only token parts，不是真实密钥。校验器按 class 分组调用 `security_evaluation_metrics.py`，并禁止输出原始 prompt、secret、authorization 或 URL。

本任务是离线安全指标契约：数据库为 `none`，SQLite 为 `not_used`，不访问外网。数据库版安全样本如果后续接入，统一使用 PostgreSQL。

## 结果

检测 smoke PASS；Prompt Injection Block Rate 为 1.0，授权违规样例率为 0.5，外发合规率为 0.666667；专项测试 1 passed。Secret Leakage Rate 的 0.5 是故意注入的合成正例，用于确认检测器工作，发布门禁阈值由后续任务设为 0。
