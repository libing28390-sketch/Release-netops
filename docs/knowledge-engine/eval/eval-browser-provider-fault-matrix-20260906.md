# 浏览器 Provider 故障与恢复矩阵现场观测（2026-09-06）

本记录是当前工作区的真实登录 Chrome 浏览器链路观测，不是外部厂商生产 SLA 证明，也不是人工发布审批。

- 页面：已登录的本地 Nexora Copilot，`http://192.168.56.1:5400/ai/copilot`
- 观测方式：Chrome UI → Assistant SSE → LLM Gateway → OpenAI-compatible Provider adapter
- 故障注入：本机隔离的 HTTP 故障桩，仅监听 `127.0.0.1`；没有访问外部 Provider、真实设备或 CLI
- 观测身份：`reviewer_type=automated_observation`，`observed_by=Codex`
- 人工签署：`PENDING_HUMAN_REVIEW`；本记录不冒充用户或发布/安全负责人的签名
- 数据边界：没有保存原始问题、完整模型回答、凭据、API key、设备地址、租户数据或 Provider 响应体

## 1. 矩阵结果

| 用例 | 浏览器时间（本地） | 故障条件 | 页面终态 | 外部调用标记 | 网关/适配器证据 | 结果 |
|---|---|---|---|---:|---|---|
| `FAULT-429-01` | 13:41 | 隔离桩返回 HTTP 429 | 本地回退；明确“未执行任何设备操作” | 是 | 同一请求收到 3 次 HTTP 429，重试后稳定返回 `AI_PROVIDER_CIRCUIT_OPEN` | PASS |
| `FAULT-CONNECT-408-01` | 13:43 | 隔离桩返回 HTTP 408，模拟 Provider 连接超时合约 | 本地回退；明确“未执行任何设备操作” | 是 | 3 次 HTTP 408；OpenAI-compatible adapter 将 408 映射为 `AI_PROVIDER_TIMEOUT`，重试达到阈值后最终稳定码为 `AI_PROVIDER_CIRCUIT_OPEN` | PASS |
| `FAULT-READ-TIMEOUT-01` | 13:44 | 隔离桩延迟 5 秒；Provider timeout 临时设置为 1 秒 | 本地回退；明确“未执行任何设备操作” | 是 | 客户端读取超时后重试，浏览器耗时约 7 秒，最终稳定码为 `AI_PROVIDER_CIRCUIT_OPEN`；没有收到成功响应 | PASS |
| `FAULT-CIRCUIT-OPEN-01` | 13:46 | 紧接着故障请求再次发起 | 本地回退；页面明确“未发生外部调用” | 否 | 后台只有 `AI_PROVIDER_CIRCUIT_OPEN`，没有新的故障桩 HTTP 请求 | PASS |
| `FAULT-RECOVERY-01` | 13:49 | 隔离桩恢复合法意图 JSON 和流式普通回答 | Provider 生成；页面显示实际临时模型及 Provider 回答 | 是 | 浏览器收到 Provider 生成内容，实际 Token `3/4`；成功端点返回 HTTP 200，熔断状态恢复 | PASS |

### 关于“连接超时”的边界

`FAULT-CONNECT-408-01` 是通过本地 Provider 桩返回 HTTP 408 触发的连接超时合约，属于真实浏览器到网关到适配器的完整链路；它不是人为声称内核层 `httpx.ConnectTimeout` 已发生。当前单元测试另行覆盖了 `httpx.TimeoutException` 到 `AI_PROVIDER_TIMEOUT` 的映射。这样记录可以区分 HTTP 合约超时、客户端读取超时和熔断拒绝，避免把不同故障类型混写。

## 2. 安全与降级断言

- 所有故障回答都没有进入设备连接、CLI 或变更执行路径。
- Provider 已实际被调用的故障请求，页面现在显示“已通过安全网关调用外部模型”；此前意图解析失败分支固定显示“未发生外部调用”的展示缺陷已修复。
- 熔断已经开放的请求没有再次访问 Provider，页面显示“未发生外部调用”，与后台日志一致。
- 恢复请求在意图 JSON 合法、普通回答使用 SSE 后显示 `provider_generated`；非法 Provider 输出仍被结构化校验拦截并转为安全回退，没有被误当作成功回答。
- 故障桩只在本机回环地址监听，未携带生产凭据、设备标识或真实租户数据。

## 3. 与四厂商浏览器 UAT 的关系

[四厂商浏览器 UAT 脱敏矩阵](eval-browser-uat-live-20260906.md) 已记录 Huawei、Cisco、H3C、锐捷各 5 个案例，共 20 个终态观察；其中 18 个为本地知识命中、2 个为明确 no-match 后经安全网关生成的通用参考，均未执行 CLI。该 20 案例的 `签署` 字段仍保持 `待签署`，本记录也不能把自动化观测升级为人工签署。

## 4. 可复核实现与测试

本轮修复把意图解析所使用的网关路由元数据限制为有界字段，并只在 Provider adapter 调用即将开始时将 `external_egress` 置为 `true`；Provider 选择、策略准备或熔断拒绝不会被误报为外发。相关回归覆盖了意图解析失败、SSE 本地回退和网关韧性路径。

- `.venv\Scripts\python.exe -m pytest backend/tests/ai/test_intent_parser_structured.py backend/tests/ai/test_api006_sse_contract.py backend/tests/ai/test_llm_gateway_resilience.py -q`
- 结果：`39 passed in 22.49s`
- 全部动作：未 push、未部署、未连接设备、未执行 CLI、未写入生产环境
- 收尾状态：临时 Provider `codex-fault-lab-20260906` 与模型已禁用，临时用户模型偏好已移除，安全策略 Provider 白名单已恢复为 `deepseek`，本机故障桩已停止；原有会话和消息 provenance 未删除。

## 5. 结论

Provider resilience 的本地隔离浏览器故障矩阵已完成并可复核；真实外部 Provider 的故障注入、四厂商 UAT 的人工逐案例签署、真实 BGE/Docling/Langfuse 运行态验收和生产发布审批仍然是独立门槛。发布结论继续保持 `HOLD — NOT A RELEASE CANDIDATE`。
