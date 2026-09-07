# Astra 与 Luna 任务分工验证记录

## 完成摘要
项目主模型设为 gpt-6-astra / medium；子 Agent 默认为 gpt-5.6-luna / high，同时最多两个。后端、前端和验证角色 high，复杂执行角色 max；所有角色采用 low verbosity。全局配置未修改，项目原有 web_search=live 保留。

## 实际文件
- `.codex/config.toml`
- `.codex/agents/backend-worker.toml`
- `.codex/agents/frontend-worker.toml`
- `.codex/agents/complex-worker.toml`
- `.codex/agents/verification-worker.toml`
- 根目录 `AGENTS.md`
- `.agents/roles/coordinator.md`
- `.agents/skills/netops-quality-gate/SKILL.md`
- `.agents/skills/netops-release/SKILL.md`
- 对应 plan 与本 walkthrough。

## 行为与边界
主 Agent 下发目标、证据、文件范围和验收要求；执行者只返回简短结果。两轮同类失败或需要改变核心设计时升级到主 Agent。执行者不递归分派，协调者统一维护文档与公共验证。

质量与发布 skills 改为按实际影响选择验证，局部 workflow 修改不自动运行全部后端测试。正式候选发布、共享鉴权/数据库/测试基础设施变更仍需完整验证；PostgreSQL-only 约束保留。

## 验证
- 本机 `codex-cli 0.145.0` 对应官方 tag 的 config.schema.json 已确认支持 agents 默认模型、推理强度和并发字段。
- Python tomllib 解析项目配置及四个角色成功，必需字段齐全，模型和推理值符合预期。
- `codex debug prompt-input` 退出码 0；仅输出检查布尔值，确认实际提示词包含根级项目入口、backend_worker、complex_worker、Luna 和 max。未将完整提示词写入日志或文档。
- skill-creator `quick_validate.py` 对质量与发布 skill 均返回 `Skill is valid!`。
- `git diff --check` 通过（现有 LF/CRLF 提示不属于 whitespace 错误）。
- 本次无应用代码变更，未跑业务全量测试或构建，未启动收费模型基准测试；当前打开的桌面任务是否重新加载默认值仍取决于宿主，新任务应核对实际子 Agent 模型记录。

## 保存与发布
根目录 AGENTS.md 当前被已有 Markdown ignore 规则忽略，作为本地入口保留；未修改 ignore 规则。`.codex/agents` 当前未提交，发布 workflow 已清理整个 `.codex/` 和 `.agents/`。若以后将根 AGENTS.md 纳入私有 Git，必须先在两条公开发布路径中明确排除，防止内部协作内容公开。

## 风险与回滚
模型与推理覆盖可能被桌面当前任务的显式设置覆盖；配置加载通过不代表 token 节省已经测量。后续用真实任务对比成本、耗时和返工率。回滚只恢复本次模型/指令 diff；原项目配置为 web_search=live、model_verbosity=high。已有 handoff 发布修复与用户文件均保留。本次未 commit、push 或部署。
