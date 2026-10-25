# Nexora 工单管理流程规范编制走查

## 完成摘要

形成《Nexora 工单管理流程规范》V1.0，作为产品与流程建设基线，明确新增流程不自动改变现行权限或代表已上线。主文档共 16 节，覆盖三类工单、职责、优先级与风险、审批、实施验证、回退、关闭、作业授权、SLA、通知、UI、审计、当前能力差距和建设验收。

## 实际修改文件

- `docs/modules/tickets/Nexora工单管理流程规范.md`：新增规范。
- `docs/modules/tickets/README.md`：添加规范入口。
- `.agents/skills/netops-itsm-design/references/nexora-workflows.md`：添加规范引用，后续设计可复用。
- 对应计划与本走查文档。

## 关键说明

- 根据现有变更后端核对初审、终审管理员要求、申请人与实施阶段绑定、MFA 和审批快照；独立实施人、标准／紧急授权等标为建设规则。
- 区分监控事件恢复与故障工单确认关闭，不能把已有事件投影当作完整 ITSM 故障闭环。
- SLA 定义计时口径、责任和版本，不填入未经确认的时限承诺；明确工单 SLA 与网络探测 SLA 的差别。
- 多次运行的关联不代表授权可以重复消费；重试和周期运行仍受实际授权规则约束。

## 验证命令与结果

- Python 文档结构检查：三份文档的本地链接、Markdown 表格列数、代码块完整性及尾随空白全部通过。
- `git diff --check -- docs/modules/tickets/README.md .agents/skills/netops-itsm-design/references/nexora-workflows.md`：通过，仅有 Git 行尾转换提示。
- `python -X utf8 C:\Users\NINGMEI\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents/skills/netops-itsm-design`：通过。
- 人工规则复核：现行能力、建设规则及未配置时限明确区分；规范没有声称新流程已上线，也未要求绕过现行审批。

## 未执行验证及原因

仅编制规范和增加文档入口，没有修改业务代码、数据库或运行配置；不运行无关前后端测试或构建。

## 剩余风险与后续建议

组织责任组、服务目录、时限承诺、保留期限和授权策略需在功能建设时配置。实施应以当前真实 API 和权限契约为基础，不得仅凭本文修改状态或直接补签授权。
