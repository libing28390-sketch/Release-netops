# ITSM 工单设计技能走查

## 完成摘要

新增项目级 `netops-itsm-design`，将工单分类、职责、审批与身份验证、执行授权、自动化闭环、工单 SLA 和简洁 UI 作为可复用设计指导。登记项目路由，保留默认自动选择策略。

## 实际修改文件

- `.agents/skills/netops-itsm-design/SKILL.md`
- `.agents/skills/netops-itsm-design/agents/openai.yaml`
- `.agents/skills/netops-itsm-design/references/nexora-workflows.md`
- `.agents/AGENTS.md`：仅新增一条技能路由。
- 对应计划与本走查文档。

## 关键实现

- PeopleCert 与 ITIL 关系通过官方收购公告核对；参考公开 ITSM 实践划分，不复制付费教材，不声称官方 skill 或认证。
- 以已查看的工单、监控事件和定时作业源码作为定位入口，要求使用时重新核对实际行为。
- 将未来 ITSM 建议与已实现状态分开，禁止通过简化 UI 跳过现有审批和执行约束。
- 元数据提供中文名称、说明和包含技能名称的默认提示；引用文件记录当前源码定位及官方资料链接。

## 验证命令与结果

- `python -X utf8 C:\Users\NINGMEI\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents/skills/netops-itsm-design`：退出码 0，Skill is valid。
- Python/PyYAML 检查 UI YAML、38 字符说明、默认提示中的技能名、自动选择默认值、技能内部引用及唯一路由登记：全部通过。
- `git diff --check -- .agents/AGENTS.md`：通过；路由 diff 仅新增一条。

## 未执行验证及原因

仅新增项目指令和元数据，未修改业务代码，因此未运行前后端业务回归或构建。未进行新会话技能目录刷新验证，不能把静态校验描述成运行时已加载证明。

## 剩余风险与后续建议

技能指导不替代后端授权，也不证明 ITIL 认证。后续实施具体工单功能时按对应专业 skill 和项目门禁执行；技能目录作为内部协作材料，不纳入公有发布树。
