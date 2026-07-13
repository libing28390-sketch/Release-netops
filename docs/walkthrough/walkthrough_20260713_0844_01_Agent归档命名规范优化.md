# Agent 归档命名规范优化 Walkthrough

## 完成摘要

- 已将 `.agents/AGENTS.md` 中 plans 与 walkthrough 的归档命名升级为带时间戳和序号的格式。
- 新规范要求计划文件使用 `plan_YYYYMMDD_HHMM_NN_[任务名].md`。
- 新规范要求完成记录使用 `walkthrough_YYYYMMDD_HHMM_NN_[任务名].md`，并与对应计划共享相同后缀。

## 实际修改文件

- `.agents/AGENTS.md`
- `docs/plans/plan_20260713_0844_01_Agent归档命名规范优化.md`
- `docs/walkthrough/walkthrough_20260713_0844_01_Agent归档命名规范优化.md`

## 关键实现说明

- `YYYYMMDD_HHMM` 使用当前工作区时区的创建时间。
- `NN` 是同一分钟内的两位序号，从 `01` 开始递增。
- 同一任务的 plan 和 walkthrough 必须使用相同 `YYYYMMDD_HHMM_NN_[任务名]` 后缀，便于配对查看。
- 历史旧格式文件不强制重命名，避免无关大规模文件变动。

## 验证命令与结果

- `Select-String -Path .agents/AGENTS.md -Pattern "plan_YYYYMMDD_HHMM_NN|walkthrough_YYYYMMDD_HHMM_NN|时间戳与序号规则" -Encoding UTF8`
- 结果：已确认新命名格式、配对要求和时间戳/序号规则写入 `.agents/AGENTS.md`。

## 未执行验证及原因

- 未运行 pytest 或 `npm run lint`；本次只修改 Agent 规则和 Markdown 归档文档，不涉及运行时代码。

## 剩余风险与后续建议

- 目录中会短期同时存在旧格式和新格式文件；如需统一历史视图，可后续单独执行“历史归档重命名整理”任务。
