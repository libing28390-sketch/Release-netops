# NetOps Skills 中文说明

本文档对当前仓库可用 Skills 的定位与用法做中文整理，便于快速选择合适技能。

## 使用原则

- 先按任务类型选技能，再落到具体实现。
- 网络自动化相关任务，优先考虑多厂商兼容与结构化输出。
- 前后端改动遵循分层设计与最小改动原则。
- 优先输出可追踪、可测试、可回滚的实现。

## Skills 总览

### 1) automation-engineer

- 文件位置: .github/skills/automation-engineer/SKILL.md
- 核心定位: 多厂商网络自动化流程与作业执行体系。
- 适用场景:
  - 批量设备发现与巡检
  - 配置备份与差异检测
  - 合规扫描与并行任务执行
- 关键约束:
  - 优先 SSH 自动化
  - 使用 Netmiko/Scrapli 等库
  - CLI 输出必须转换为结构化 JSON
  - 失败要返回结构化错误，任务要可追踪

### 2) backend-architect

- 文件位置: .github/skills/backend-architect/SKILL.md
- 核心定位: FastAPI 后端架构、API 设计与可靠性。
- 适用场景:
  - 新增/重构后端 API
  - 设计服务层与数据模型
  - 后台任务与并发性能优化
- 关键约束:
  - 分层职责清晰（api/services/repositories/models/schemas/drivers）
  - REST 风格与统一响应格式
  - 错误处理、日志、安全要标准化
  - 代码可读、模块化、避免重复逻辑

### 3) frontend-design

- 文件位置: .github/skills/frontend-design/SKILL.md
- 核心定位: 高设计质量、可生产的前端界面实现。
- 适用场景:
  - 页面改版、组件视觉升级
  - 落地页、看板、交互界面开发
- 关键约束:
  - 必须有明确视觉方向（非模板化审美）
  - 强调字体、色彩、空间、动效一致性
  - 避免千篇一律的 AI 风格设计

### 4) network-expert

- 文件位置: .github/skills/network-expert/SKILL.md
- 核心定位: Nexora 全栈网络运维能力（后端 + 自动化 + 前端看板）。
- 适用场景:
  - 设备管理、监控、备份、合规、IPAM、告警报表的一体化功能
  - 网络运维平台端到端能力建设
- 关键约束:
  - 多厂商支持与并发执行
  - 返回结构化数据与清晰 API
  - 前端强调 NOC 可视化与可复用组件

### 5) network-security

- 文件位置: .github/skills/network-security/SKILL.md
- 核心定位: 网络自动化平台安全控制与合规检查。
- 适用场景:
  - 凭据保护与加密
  - API 认证与 RBAC
  - 安全基线检查与合规报告
- 关键约束:
  - 禁止明文密码
  - 环境变量与加密存储敏感信息
  - 安全检查结果可审计

### 6) observability-engineer

- 文件位置: .github/skills/observability-engineer/SKILL.md
- 核心定位: 监控、日志、告警与可观测性看板。
- 适用场景:
  - 设备健康、作业状态、API 延迟、系统错误可视化
  - 告警与可靠性可见性建设
- 关键约束:
  - 结构化日志
  - 指标体系完整
  - 方案可扩展（Prometheus/Grafana/Alertmanager）

### 7) snmp-telemetry

- 文件位置: .github/skills/snmp-telemetry/SKILL.md
- 核心定位: SNMP 轮询与时序遥测采集。
- 适用场景:
  - 接口流量、错误率、CPU、内存、温度、在线时长采集
  - SNMPv2/v3 指标管道建设
- 关键约束:
  - 轮询频率合理，避免过度采集
  - 指标按时序方式存储
  - 输出统一为结构化 JSON

### 8) textfsm-parser

- 文件位置: .github/skills/textfsm-parser/SKILL.md
- 核心定位: 将多厂商 CLI 输出解析为结构化数据。
- 适用场景:
  - show 命令解析
  - 设备巡检字段抽取
  - 无模板时新增 TextFSM 模板
- 关键约束:
  - 不返回原始 CLI 文本作为最终结果
  - 优先复用 ntc-templates
  - 多厂商模板策略一致

### 9) topology-engineer

- 文件位置: .github/skills/topology-engineer/SKILL.md
- 核心定位: 拓扑发现与交互可视化。
- 适用场景:
  - LLDP/CDP 邻接发现
  - 链路映射与拓扑图展示
- 关键约束:
  - 输出结构化拓扑数据（设备/接口/链路）
  - 前端支持节点状态、链路状态、悬浮信息

### 10) web-artifacts-builder

- 文件位置: .github/skills/web-artifacts-builder/SKILL.md
- 核心定位: 复杂前端 Artifact 的工程化构建与打包。
- 适用场景:
  - 需要状态管理、路由、组件体系的复杂交互产物
  - React + Tailwind + shadcn/ui 的单文件 artifact 输出
- 关键约束:
  - 按初始化脚本与打包脚本流程执行
  - 避免模板化审美与同质化 UI

### 11) webapp-testing

- 文件位置: .github/skills/webapp-testing/SKILL.md
- 核心定位: 本地 Web 应用自动化测试与调试（Playwright）。
- 适用场景:
  - 页面交互回归
  - DOM 选择器探测
  - 截图、日志采集
- 关键约束:
  - 先看脚本帮助再调用
  - 动态页面先等待 networkidle 再做 DOM 探测
  - 脚本里要正确管理浏览器生命周期

### 12) agent-customization（外部技能）

- 文件位置: copilot-skill:/agent-customization/SKILL.md
- 核心定位: Agent 自定义配置文件的创建、修复与调试。
- 适用场景:
  - 维护 instructions/prompt/agent/skills 规则体系
  - 排查自定义配置不生效的问题
- 说明:
  - 该技能来自外部 skill 源，不在当前仓库本地文件树内。

## 规则补充

仓库还包含项目级规则文件:

- .github/rules/project.md

该规则强调 Nexora 功能域（设备管理、配置备份、SNMP、IPAM、拓扑、作业、告警）以及在生成代码时优先使用可用 Skills。

## 任务与技能快速映射

- 设备自动化/批量作业: automation-engineer
- FastAPI 架构/API 合同: backend-architect
- 运维平台端到端功能: network-expert
- 安全/RBAC/凭据保护: network-security
- 监控指标与告警可视化: observability-engineer
- SNMP 指标采集: snmp-telemetry
- CLI 文本解析: textfsm-parser
- 拓扑发现与图谱: topology-engineer
- 高质量前端视觉与交互: frontend-design
- 复杂前端 artifact 交付: web-artifacts-builder
- 前端自动化测试: webapp-testing
- Agent 规则体系治理: agent-customization
