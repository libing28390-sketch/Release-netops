# 工作区产品变更提交main与Actions核验

## 目标
将本机已修改和新增的全部产品源代码、测试、迁移与示例配置提交main、推送origin，并确认同一提交的GitHub Actions最终成功。

## 现状与范围
当前main与origin/main同步，基线22f523a4。待发布涉及工单责任人/交互、定时作业与NSOT退役、SNMP ARP/FDB与IPAM定位/展示、公共导出组件。内部.agents/.codex/handoff及历史私人记录、日志、运行时monitoring artifacts、临时构建和已有dist产物保留本机，不进入产品提交。

## 分工及文件
主Agent负责提交清单、保密检查、修复记录、Git提交推送和Actions最终核验。Luna后端验证者只读检查后端相关diff并运行对应focused测试；Luna前端验证者运行lint、完整前端测试及隔离build，只写output日志及隔离构建目录。源代码修复统一由主Agent处理。

## 步骤和验证
1. 检查全部diff、未跟踪源文件、远端分歧、workflow触发与发布树排除规则。
2. 执行本地质量检查并补齐docs/fixes记录；显式暂存产品文件，检查暂存清单与敏感信息。
3. main提交并普通push，不强推、不建分支、不打版本tag。
4. 按新提交SHA追踪所有触发的Actions；若失败定位修正后新提交，再验证最终SHA。CI完整后端门禁作为跨模块完整回归证据。
5. 保存walkthrough和最终Actions链接，报告仍留本地的材料。

## 风险与回滚
main push现有workflow会同步公开发布仓库；遵守当前公开树过滤约束，不扩展部署。失败保留现场并修正；需回滚时以revert提交处理，不覆盖用户工作树。只使用现有授权Git身份，凭据不写日志/文件。
