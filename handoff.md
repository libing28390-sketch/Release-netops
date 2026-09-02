我直说：你这个担心是有依据的。当前 Nexora AI 不能说“垃圾”，但也不能说已经达到成熟生产级 AI 的水平。

比较准确的评价是：

> Nexora 目前是“工程骨架比较扎实，但 AI 质量层明显偏弱；通用能力自研过多，领域能力反而是最值得保留的部分”。

这两件事要分开看。后端跑过两千多个测试，只能证明接口、数据库、权限、迁移、异常路径等工程契约相对稳定，不能证明“模型理解准确”“RAG 检索正确”“回答有用”。

## 当前真实水平

| 能力 | 当前评价 | 依据 |
|---|---|---|
| Provider Gateway | 较好 | 有 Provider 路由、超时、并发、熔断、流式输出和降级 |
| Security Vault / DLP | 较好 | 有敏感信息分类、出站拦截、Token 化和日志脱敏 |
| 多租户与权限 | 较好 | RAG 和工具执行都有租户及 ACL 边界 |
| 高风险操作确认 | 较好 | 工具注册、参数校验、风险等级和确认流程比较完整 |
| 网络领域模型 | 有价值 | 厂商、平台、版本、Feature、CLI、设备和告警模型是 Nexora 的核心资产 |
| 意图识别 | 不成熟 | 真实 DeepSeek 小样本只有 `5/8`，即 62.5% 准确率；样本还太小 |
| 文档解析 | 偏弱 | PDF、DOCX 和复杂官方文档主要依赖自研轻量解析，版面和表格处理能力有限 |
| RAG 检索质量 | 不成熟 | 刚刚出现 VLAN 查询召回 Smart Licensing/SmartAgent 的实际污染 |
| Reranker | 基本没有生产能力 | 有 `BoundedReranker` 接口，但默认实现并不是真正的语义重排模型 |
| AI 可观测性 | 不完整 | 有内部 Trace，但缺少成熟的 Prompt、Token、成本、会话、检索和工具全链路分析 |
| AI 评测体系 | 刚起步 | 有离线脚本和少量真实样本，但生产语料 Top-5 Recall 仍未测量 |
| 多 Provider 验证 | 不完整 | 当前主要验证 DeepSeek，Qwen、Ollama 没有真实运行数据 |
| Agent 编排 | 可用但自研过重 | 工具、计划和确认都有，但长期维护成本高，缺少成熟状态机和持久任务能力 |

所以你感觉“不好用”，不是错觉。最近 Cisco 的案例已经说明：工程测试可以全部通过，但只要知识标签、Chunk 边界、检索排序有问题，用户最终看到的回答仍然会很差。

## 真正的问题不是“全部自研”，而是“自研边界选错了”

有些能力 Nexora 必须自研，因为开源项目不懂网络运维业务：

- Cisco、华为、H3C、锐捷的平台和版本体系。
- `VLAN / Access / Trunk / OSPF / BGP` 等领域分类。
- 网络设备资产、告警、拓扑、ARP、MAC、配置和巡检数据模型。
- 哪些命令是只读、哪些命令危险。
- `shutdown`、配置下发、凭据轮换等确认和审批流程。
- 租户、用户、设备权限。
- Security Vault 与设备凭据保护。
- 变更单、审计、回滚和执行记录。
- 网络设备驱动与真实 CLI 行为。

这些是 Nexora 的产品价值，必须掌握在自己手里。

但下面这些通用能力，确实没必要继续深度自研：

- PDF、DOCX、PPTX、HTML 文档解析。
- Embedding 模型。
- Reranker 模型。
- Prompt 回归测试。
- RAG 评测指标。
- AI 红队和 Prompt Injection 测试。
- LLM Trace 和 Prompt 版本管理。
- 本地大模型推理服务。
- 通用 Agent 状态机。
- 通用结构化输出重试。
- 标准化外部工具协议。

也就是说，合理的目标不是推翻整个 Nexora AI，而是改成：

```text
Nexora 自研
├─ 网络领域模型
├─ 设备、资产、拓扑、告警
├─ 权限与租户
├─ Security Vault
├─ 工具风险和确认
├─ 变更审计
└─ Provider 出站政策

成熟开源组件
├─ Docling：文档解析
├─ FlagEmbedding：Embedding / Reranker
├─ Promptfoo：回归和红队
├─ Ragas：RAG 评测
├─ Langfuse：可观测性
├─ vLLM：本地模型服务
├─ MCP SDK：标准工具协议
└─ PydanticAI：未来 Agent 编排
```

## 哪些自研代码应该保留

以下部分我不建议推翻：

- [LLMGateway](D:/netops/netsops-main/backend/ai/gateway/llm_gateway.py:87) 中的 Nexora 安全策略、租户、并发、熔断和审计边界。
- [IntentDecision](D:/netops/netsops-main/backend/ai/schemas/intent.py:38) 这样的领域结构化契约。
- [ToolRegistry](D:/netops/netsops-main/backend/ai/tools/registry.py:97) 中的网络工具定义和参数模型。
- 高风险命令确认、操作审计和设备权限。
- PostgreSQL 数据权威、知识库 ACL 和租户隔离。
- 厂商、平台、版本、Feature 的 Metadata 体系。
- 本地 IP/MAC/告警/资产确定性查询。

这些代码与 Nexora 业务强绑定，用通用框架替换后往往反而会失去控制。

## 哪些自研代码应该逐步替换

### 1. 自研文档解析器

目前的 [DocumentParserRegistry](D:/netops/netsops-main/backend/services/document_parser_adapters.py:595) 可以保留接口，但 PDF、DOCX 等复杂格式的具体实现应逐步改成 Docling Adapter。

也就是说，保留 Nexora 的“解析器契约”，替换底层解析实现。

### 2. 自研 Reranker

当前的 [BoundedReranker](D:/netops/netsops-main/backend/ai/services/retrieval_contract.py:218) 设计可以保留，因为它已经有超时、候选数量和失败降级边界。

但里面应该接真正的 BGE Reranker，不应该继续依赖规则分数冒充语义重排。

### 3. 自研评测脚本

现有评测代码可以保留为领域指标计算器，但测试执行、模型对比、红队攻击和 CI 报告应该交给 Promptfoo/Ragas。

Nexora 只维护：

- 网络厂商错误率。
- 跨平台污染率。
- Feature 错配率。
- 危险工具误调用率。
- 引用正确率。
- 设备数据泄漏率。

通用评测运行器不需要继续自己维护。

### 4. 自研 Trace

Nexora 应继续决定“哪些字段允许记录”，但 Trace 的存储、检索、会话视图、Prompt 版本、Token、成本和延迟分析可以交给 Langfuse。

现有 [检索 Trace](D:/netops/netsops-main/backend/ai/services/retrieval_trace_store.py:437) 可以改成受控导出层，而不是继续扩展成一整套自研 LLMOps 平台。

### 5. 自研 Agent Loop

暂时不要马上删除，因为高风险确认和网络工具安全已经绑定在里面。

以后可以考虑让 PydanticAI 负责通用 Agent 状态机，但必须满足：

- Provider 调用仍经过 Nexora Gateway。
- 工具仍来自 Nexora Tool Registry。
- 风险等级由 Nexora 判断。
- 确认和审计仍由 Nexora负责。
- PydanticAI 只负责状态推进，不获得设备凭据。

## 不能因为用了开源项目就默认质量会变好

这一点非常重要。

如果直接把 LangChain、Dify、RAGFlow、PydanticAI、Docling、Ragas、Langfuse 一股脑全部塞进来，结果大概率比现在更乱：

- 两套 Gateway。
- 两套重试。
- 两套 RAG。
- 两套 Prompt。
- 两套工具注册。
- 两套数据库状态。
- 两套会话。
- 权限和审计无法统一。
- 依赖升级互相冲突。
- 问题出现时不知道归谁负责。

开源项目应该作为 Nexora 内部接口的实现插件，而不是接管整个平台。

## 我现在对 Nexora AI 的结论

不是“全废”，而是：

- 安全、权限、审计和网络领域层值得保留。
- 通用 AI 基础设施自研过多，应该停止继续扩张。
- 文档解析、Reranker、评测和 Trace 应优先换成成熟开源实现。
- 目前 AI 效果没有足够数据证明已经生产成熟。
- `64 passed`、`2052 passed` 证明的是代码没有明显回归，不证明回答质量好。
- 真实意图准确率 `5/8` 和刚发生的 RAG 污染，说明质量层确实需要系统整改。

## 最稳妥的改造方式

我建议从现在开始冻结新的通用 AI 自研，按下面顺序做“可对比替换”：

1. 建立至少 200～500 条人工审核的 Nexora Gold Dataset。

   必须覆盖 Cisco、华为、H3C、锐捷，以及知识查询、故障排查、告警、资产、配置和高风险操作。

2. 用 Promptfoo 接管自动评测和红队门禁。

   这一步不改生产运行时，风险最低。

3. 让 Docling 与当前解析器并行运行。

   同一份官方文档分别解析，比较章节、命令块、表格、噪声和 Chunk 质量，暂不立即切换。

4. 让 BGE Reranker 以 shadow 模式运行。

   同时记录旧排序和新排序，不影响用户结果；确认 Top-5、跨厂商污染和延迟改善后再启用。

5. 部署 metadata-only Langfuse。

   先观察每个问题到底失败在意图、检索、重排、Provider、工具还是回答阶段。

6. 数据证明开源实现更好后，再删除对应自研实现。

   不能先删除旧实现，再期待新框架自动解决问题。

如果只做第一轮，我建议现在不碰 Agent、不碰 Instructor、不换 Gateway，也不换 PostgreSQL。先做：

```text
Promptfoo 评测基线
        ↓
Docling 双轨解析
        ↓
BGE Reranker Shadow
        ↓
用数据决定是否切换
```

这是成本最低、风险最小，也最能判断“当前 Nexora AI 到底有多差”的办法。经过这轮后，我们就不再靠感觉评价，而是可以明确看到：

- 哪些问题来自文档解析。
- 哪些问题来自 Metadata。
- 哪些问题来自检索。
- 哪些问题来自重排。
- 哪些问题来自模型。
- 哪些自研代码应该保留。
- 哪些自研代码可以直接删除。