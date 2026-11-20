# ADR-001：Instructor 与内部 Pydantic 结构化输出

状态：Accepted / Deferred（暂缓引入 Instructor）  
日期：2026-09-01  
决策范围：意图解析与其他需要结构化模型输出的 AI 服务

## 背景

Nexora 的意图解析边界使用 `IntentDecision` Pydantic 模型校验模型输出，再投影为现有 Assistant 兼容字典。外部 Provider 请求必须经过 Nexora AI Gateway、安全策略、数据分类、Provider allowlist、超时/重试和审计链路。生产运行时没有直接依赖 Instructor，也没有绕过 Gateway 的 SDK 调用路径。

本次任务需要评估 Instructor 是否可以减少结构化输出适配代码，但不能把“安装了一个 SDK”或离线 Fake Gateway 结果当作真实 Provider 成功率、延迟或 Token 对比。

## 决策

当前继续采用内部 Pydantic 方案，暂不把 Instructor 加入生产依赖或生产调用路径。

保留的隔离边界如下：

- 未来若试验 Instructor，只能作为 Gateway-owned adapter 的内部实现细节；输入为 Gateway 已处理的消息，输出必须重新通过 `IntentDecision` 等 Pydantic 合约校验。
- 适配器不得读取或接收 API key、Provider endpoint、原始凭据、未经脱敏的工具参数，也不得自行创建 HTTP 客户端或重试链路。
- Instructor 版本、许可证、依赖树、Prompt/Schema 兼容性和安全审查必须先形成独立批准记录。
- 任何对比必须使用同一 Provider、同一模型、同一固定数据集、同一 Gateway 策略和同一超时/重试预算，同时记录首轮成功率、schema correction 成功率、意图准确率、端到端延迟、输入/输出 Token 和估算成本。
- 试验失败或指标不达标时，关闭试验开关并回到内部 Pydantic；不得进行不可逆迁移。

## 方案取舍

### 采用内部 Pydantic（当前方案）

优点是依赖少、边界明确、现有测试和兼容投影完整，能直接控制错误处理、字段白名单、澄清策略和 Gateway 观测。缺点是结构化解析、schema correction 和适配逻辑需要由本项目维护。

### 引入 Instructor（仅候选方案）

可能减少一部分模型解析胶水代码，但会增加第三方依赖、版本耦合和适配审查面。若没有批准的实验 Provider 和固定标注集，无法得到可审计的真实收益结论；因此本次不引入。

## 证据与边界

- 隔离边界测试：`backend/tests/ai/test_instructor_isolation.py`。
- 当前隔离结果：包未安装、生产依赖无 Instructor、生产代码无直接 Instructor import、Fake Gateway 只验证 Gateway-owned request 与 Pydantic output 边界。
- 当前真实 Provider 评测：`docs/knowledge-engine/eval/ai-dialog-live-provider-report-20260901.json`。该报告测量的是内部 Pydantic 结构化路径，不是 Instructor 对比结果。
- Instructor 与内部方案的真实 Provider 成功率/延迟/Token 对比仍为未测量状态；没有批准的依赖和独立实验 Provider 时，不声明对比结论。

## 后续引入条件

必须同时满足：

1. 完成安全、许可证和依赖审查，锁定经过批准的 Instructor 版本范围；
2. 提供独立且可回滚的实验 Provider 或本地合规模型，并确认数据分类、留存和区域策略；
3. 实现仅依赖 Gateway 的隔离适配器；
4. 使用固定标注集完成重复实验，并保存成功率、纠正率、准确率、延迟、Token、成本和失败类型；
5. 通过超时、429、重试预算、熔断、日志脱敏、响应不可变性和向内部 Pydantic 回退的回归测试；
6. 由架构/安全/维护者批准后，才允许在 shadow 或 feature flag 路径中试运行。

## 回滚

删除或关闭实验适配器和 feature flag，恢复内部 Pydantic 解析路径；不修改现有 Provider 配置、AI 数据、V1 路由或数据库迁移。由于本 ADR 不引入生产依赖和数据库变更，回滚不需要数据恢复。
