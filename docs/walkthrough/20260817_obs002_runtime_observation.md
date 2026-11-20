# 2026-08-17 OBS-002 运行时观测

## 验证目标

让一次 RAG/LLM 请求能回看 reranker、引用校验、耗时、Token、Provider/Model 路由和 AI Security Gateway 结果，并且在流式、Fallback、异常和安全拦截路径保持同一字段合同。

## 实现结果

`retrieval_trace_store` 生成 `nxa.retrieval.runtime.v1` projection。assistant 在检索完成、非流式回答完成或 SSE 结束时补写 runtime；Gateway 在 prepared、success、fallback、provider error 和 security block 路径提供 route metadata。更新采用嵌套合并，因此后续写入不会丢掉先前的检索延迟或 reranker 阶段。

## 安全与兼容性

Provider/Model 只保留有限长度的标识；API Key、请求/响应正文、提示词、headers、检测原文和知识正文均不进入 Trace。安全拦截记录策略结果码后终止外部调用。没有新增 PostgreSQL DDL，也没有改写 V1 表或 V1 基线行为。

## 验证

focused 9 passed，AI 237 passed，KUI 回归 6 passed，前端 lint/build、Python compile、diff check 和 V1 PostgreSQL baseline 均通过。
