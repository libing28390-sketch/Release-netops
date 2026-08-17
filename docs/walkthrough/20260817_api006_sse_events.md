# 2026-08-17 API-006 versioned SSE events

## 验证目标

确认 Copilot 流式回答的六类事件具有同一版本封套，引用可独立增量消费，错误与安全拦截仍以安全事件结束。

## 结果

后端 SSE/RAG 回归 11/11、前端解析测试 1/1 通过。`nxa.sse.v1` 已覆盖 meta、progress、token、citation、done、error；前端 Copilot 保持既有回调兼容并追加引用事件消费。编译、lint、build 和 diff check 通过。
