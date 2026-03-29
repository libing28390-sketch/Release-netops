---
applyTo: "**"
---

# NetOps 仓库 Copilot 规则

## 目标

- 在不破坏现有行为的前提下，完成最小必要改动。
- 优先修复根因，不做表面性补丁。
- 保持前后端接口一致、可测试、可回滚。

## 语言与沟通

- 默认使用中文回复。
- 说明结论时先给结果，再给关键步骤。
- 引用文件位置时提供可定位的路径与行号。

## 通用工程规则

- 不改动与当前任务无关的文件。
- 不重命名公共 API，除非需求明确要求。
- 保持现有代码风格，不做大规模无关格式化。
- 变更应尽量小且集中，避免引入额外复杂度。

## 前端规则（React + TypeScript + Vite）

- 新增逻辑优先复用现有组件与页面模式。
- 保持类型完整，避免使用 any。
- 与后端交互时，优先复用已有类型定义与请求模式。
- 涉及 UI 调整时，确保桌面与移动端可用。

## 后端规则（FastAPI + Python）

- API 路由、服务层、模型层职责清晰分离。
- 数据结构变化需同步 schemas 与接口返回。
- 记录关键日志，但避免输出敏感信息。
- 与网络设备交互相关改动需考虑异常与超时处理。

## 网络自动化相关规则

- 多厂商差异通过 driver 或 parser 层封装，不在路由层硬编码。
- 命令执行、备份、合规检查流程应具备失败可追踪性。
- 解析类逻辑优先保持结构化输出（便于前端展示和审计）。

## 测试与校验

- Python 改动后至少执行相关 pytest。
- 前端改动后至少执行类型检查或构建检查。
- 无法执行测试时，需在结果中明确说明原因与风险。

## 安全与凭据

- 禁止提交密钥、密码、令牌等敏感信息。
- 涉及认证与权限时，优先遵循最小权限原则。
- 日志与错误信息中不泄露凭据、IP 白名单细节或内部密钥。

## 技术栈与项目约定

### 后端
- Python 3.10+ / FastAPI / Pydantic / SQLite (`data/netops.db`)
- 混合使用 SQLAlchemy 模型 (`models/models.py`) 和原生 `sqlite3` (`get_db_connection`)
- 配置：`pydantic-settings` + `.env`，单例 `core/config.settings`
- 认证：Bearer Token → `core/rbac.require_role()` 三级角色（Administrator > Operator > Viewer）
- 凭据加密：Fernet/AES + PBKDF2，`enc:v1:` 前缀标记，函数见 `core/crypto.py`
- 日志：`core/logging.setup_logging()`，TimedRotatingFileHandler + `SanitizeFilter` 脱敏
- 驱动：工厂模式 `drivers/factory.py`，netmiko 优先 → scrapli 自动 fallback
- 支持厂商：Cisco IOS/NX-OS/IOS-XE, Huawei VRP, H3C Comware, Arista EOS, Juniper JunOS

### 前端
- React 19 + TypeScript + Vite + TailwindCSS
- 图表：Recharts
- 动画：motion（framer-motion）
- 色彩体系：青色系 `#06b6d4`(主)、`#0891b2`(hover)、`#164e63`(深)、`#ecfeff`(浅底)

### API 响应格式
```json
{ "success": true, "data": {}, "message": "" }
```

### 新增 API 端点的标准流程
1. `schemas/schemas.py` — 定义请求/响应 schema
2. `services/xxx_service.py` — 实现业务逻辑
3. `api/xxx.py` — 创建路由，调用 service，注入 RBAC 依赖
4. `main.py` — 注册 router

## 建议技能选择

- 设备自动化与作业编排：automation-engineer
- 后端 API 与服务设计：backend-architect
- 拓扑、SNMP、TextFSM：topology-engineer / snmp-telemetry / textfsm-parser
- 安全与权限：network-security
- 前端界面与交互：frontend-design

## 提交建议

- 提交信息使用清晰前缀，例如：feat、fix、refactor、docs、chore。
- 单次提交应只包含同一主题的变更。
