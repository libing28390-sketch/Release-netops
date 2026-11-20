# 子 Agent 默认模型策略完成记录

## 完成摘要

全局默认 `gpt-6-luna` / `max` 已经存在；四个角色配置中的显式覆盖现已统一为 Luna 6 max。

## 实际修改文件

- `.codex/agents/backend-worker.toml`
- `.codex/agents/complex-worker.toml`
- `.codex/agents/frontend-worker.toml`
- `.codex/agents/verification-worker.toml`
- `AGENTS.md`

`.codex/config.toml` 未修改：其 `default_subagent_model` 与 `default_subagent_reasoning_effort` 原本已分别为 `gpt-6-luna` 和 `max`。

## 关键实现

所有角色文件均设置 `model = "gpt-6-luna"`、`model_reasoning_effort = "max"`。`AGENTS.md` 也改为要求所有子 Agent 使用该模型与推理强度，且直接指定模型时采用相同设置。主 Agent 模型、并发上限及角色职责未修改。

`.codex/agents/` 与根目录 `AGENTS.md` 均受仓库 `.gitignore` 忽略；修改已保存在当前本机工作区配置/指令中，不会作为公有发布文件提交。全局默认仍由已跟踪的 `.codex/config.toml` 提供。

## 验证命令与结果

使用 Python 标准库 `tomllib` 解析 `.codex/config.toml` 和四个 `.codex/agents/*.toml` 文件，并断言全局默认与所有角色模型值为 `gpt-6-luna` / `max`：通过。
未运行业务测试、lint 或 build；本项仅涉及配置。

## 风险与回滚

当前配置和运行时均需支持 `gpt-6-luna`。如果特定宿主不支持该模型，创建子 Agent 时会明确报模型不可用；回滚时可恢复四个角色文件中原来的模型名与推理强度。
