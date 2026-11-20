# OpenAPI 一期计划修订与文档验证记录

> 时间：2026-10-13（Asia/Shanghai）
> 对应计划：[OpenAPI 一期实施计划 v1.2](D:/netops/netsops-main/docs/plans/plan_20261013_0757_01_OpenAPI一期落地.md)
> 状态：文档修订完成；未实施业务代码、迁移、部署或压测

## 1. 完成摘要

根据用户“更新下我们的计划”的授权，将原下载附件 v1.1 的目标架构与仓库只读评估结果整理为可用于后续实施的 v1.2 主计划。原下载附件保留不变。

本次建立 P0a/P0b 独立交付门槛：P0a 为单条资产能力、凭证与管理员存量接入；P0b 为可靠批量同步与共存压测。P0a 验收通过不代表 P0 全部完成，未开放接口不进入相应公开 Schema。

## 2. 实际修改文件

- 新增：D:/netops/netsops-main/docs/plans/plan_20261013_0757_01_OpenAPI一期落地.md
- 新增：D:/netops/netsops-main/docs/walkthrough/walkthrough_20261013_0757_01_OpenAPI一期落地.md

未修改 backend、src、数据库迁移、Compose、Nginx 或原下载附件。工作区原有 .agents/skills/netops-grafana-dashboards/SKILL.md、.codex/config.toml、handoff.md 等未提交变更及构建产物均未触碰；未提交、推送或部署。

## 3. 关键修订

1. **真实仓库适配**：采用 physical_assets 与现有 tenant/site；保留 TEXT 内部主键；资产和站点都设计公开 UUID；Python 3.11、Pydantic v2 与编号迁移取代示例假设。
2. **存量接入**：把管理员预对账、确认候选、创建/纠错外部映射纳入 P0a，不用普通 Upsert 试探旧库存。
3. **身份约束**：P0 保留现有全局唯一约束，明确重叠管理 IP 不作为已支持能力；解除约束单独做跨发现/拓扑/连接链路评估。
4. **范围授权**：机器 Principal 接入全局默认拒绝检查；不创建另一套 scope 表；明确无站点资产与设备/资产租户不一致记录的处理。
5. **版本与并发**：将 assets/devices 路由、发现/导入等全部相关写入口纳入 row_version；Upsert 更新要求同一版本的 expected_version；补充 428/422/412 与 Batch 逐条拒绝用例。
6. **状态与多厂商**：公开生命周期不写入内部可达性 status；明确退役停止协调与可靠恢复；复用 vendor/platform 规范化与三厂商门禁。
7. **P0a 可靠副作用**：单条退役/IP 变更的持久化意图、崩溃与重启恢复属于 P0a，不能等待 P0b Worker。
8. **P0b 可靠性**：Job、Item、派发意图与接收幂等同事务；queued/running 补投、消息丢失、租约、稳定执行幂等与结果统计均有验收；执行幂等保留期不沿用短 HTTP TTL。
9. **告警隔离**：规划独立 asset_celery_app:app、OPENAPI_ASSET_BROKER_URL 与资产 relay/worker 入口；保留现有告警 app/Broker，使用真实 alert_notify_critical/alert_notify_normal 队列名。
10. **容量与发布**：公开接口两层 2 MiB 限制、资产 Worker 小连接池、全局背压、资源基线和共存阈值；配置限额不当作实际容量或上线证据。

以上均是计划要求，不表示相应功能已实现。

## 4. 评审与验证

### 4.1 评审分工

主 Agent 维护计划与本记录，并统一修订共享文件。两个 Luna 执行者只读评审：资产/权限/版本契约，以及运行时/可靠派发/容量与文档结构。执行者未生成重复计划、未修改文件、未继续创建子 Agent。

已落实的追加评审意见：关联设备租户一致性、生命周期与 status 分离、devices 直接资产写入口、expected_version 类型/错误码、P0a 副作用验收、资产 app 与告警 Broker 隔离、backend/core/config.py 完整路径。

### 4.2 实际验证命令与结果

- git status --short：读取工作树基线，保留已有修改。
- rg --files docs/plans docs/architecture docs/openapi docs/walkthrough -g '*OpenAPI*' -g '*openapi*' -g '*开放*'：检查既有计划；docs/openapi 尚不存在，属于待新增实施产物目录。
- Get-Content -LiteralPath '.agents/skills/netops-quality-gate/SKILL.md'：按文档影响范围选择验证。
- Get-Content -LiteralPath 'docker-compose.yml'、rg -n 'WORKDIR|COPY|PYTHONPATH' Dockerfile、Get-Content -LiteralPath 'backend/celery_app.py'：只读核对 Worker 导入路径、现有队列名称与告警 Broker 绑定。
- git status --short -- 'docs/plans/plan_20261013_0757_01_OpenAPI一期落地.md' 'docs/walkthrough/walkthrough_20261013_0757_01_OpenAPI一期落地.md'：检查本次文档范围；计划文件为新增，未提交。
- PowerShell 内联结构校验：Get-Content -LiteralPath $planFile -Raw -Encoding utf8 读取主计划；使用正则、Contains 与 Test-Path -PathType Leaf 校验标题、章节、表格、围栏、关键词、真实文件路径和最终约束。

第一次执行者结构检查退出码 1：文档中的 backend/core/config.py 完整写法缺失；另有“不能依赖”与检查器期待“不依赖”的匹配差异，语义本身正确。主 Agent 修正文档路径并细化上述约束后，针对新文档状态统一执行最终校验，没有重复运行业务公共测试。

最终内联校验退出码 0，结果如下：

```json
{
  "Passed": true,
  "Lines": 427,
  "Headings": 36,
  "H1": 1,
  "Tables": 9,
  "FenceMarkers": 0,
  "MainSections": 14,
  "KeywordGroups": 6,
  "ExistingFiles": 20,
  "FinalConstraints": 6,
  "Errors": []
}
```

标题层级与单 H1、14 个主章节、9 个表格列数、围栏闭合、6 组关键修订、20 个已存在文件路径、6 个最终约束均通过。拟新增文件/目录不要求当前存在。代码围栏计数为 0，仅表示主计划未使用 fenced 示例。

最终配对校验退出码 0：两个文件存在，plan/walkthrough 后缀相同，记录中的主计划链接正确，记录的 JSON 围栏为 2 个且闭合。git -c core.quotepath=false status --short -- 本次两个文档路径显示它们均为新增未提交文件。

## 5. 未执行验证及原因

- 未运行 pytest、npm lint/build、PostgreSQL-only 策略扫描器：本次只修改 Markdown 计划和记录，没有运行时代码、实际 API 模型、数据库迁移或前端产物变更。
- 未连接线上 PostgreSQL、读取真实 .env、启动/检查运行容器、测量资源或压测：用户本次授权范围为更新计划。
- 未执行迁移、生产部署、发布或真实设备操作。

计划中列出的后续测试与压测为实施验收要求，不在本记录中标记通过。

## 6. 剩余风险与下一步

后续从 S0 开始：补实际数据库与部署事实、孤立站点/设备租户一致性、状态映射、全部资产写入口与容量基线。S1 冻结模型、权限、状态机与全局配额后再编码。

重叠 IP 跨链路支持、可信来源版本的乱序处理、P1/P2 能力未实施；不能依据本次文档校验宣称已具备生产开放 API。

本次回滚只涉及新增文档；原附件与业务状态未改变。后续业务实施按主计划的功能关停、持久化任务恢复及向前修复策略执行。
