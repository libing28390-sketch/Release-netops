# 2026-09-11 代码安全审查与修复

本次以代码审查和本地回归测试检查认证、授权、AI 模板、终端凭据交换、MFA、初始化账号及密码变更。已直接修改确认的问题，未操作运行中的业务数据库、设备或外部通知渠道，未部署。

## 已修复的问题

| 风险 | 问题及影响 | 修复位置与行为 |
| --- | --- | --- |
| 严重 | 多个旧 HTTP 路由遗漏认证/授权，包括设备删除、配置备份、审计查询、告警及全局变量管理。 | `backend/core/api_security.py`、`backend/main.py`：增加应用级默认保护，沿用已有明确权限依赖；遗漏声明时默认读 Viewer、写 Operator、删除 Administrator。登录、健康探针及独立能力令牌回调使用精确路由白名单。 |
| 严重 | AI 权限依赖在无有效会话时回退为管理员，未登录调用者可进入 AI 管理接口。 | `backend/ai/security/permissions.py`：无有效会话返回 401，保留已登录用户的角色权限检查。 |
| 严重 | 数据库提示词交给普通 Jinja2 Template 渲染，可访问 Python 对象内部属性；与上述越权结合构成服务器代码执行路径。 | `backend/ai/prompts/renderer.py`：使用 SandboxedEnvironment，阻止对象内部属性访问，保留正常变量和循环渲染。 |
| 严重 | 终端接口接受调用方指定的程序路径，并将用户名、密码、主机拼接到 `shell=True` 的命令中；普通只读账号也能请求终端凭据令牌。 | `backend/api/system.py`：移除后端进程启动，使用现有工作站 Terminal Agent；增加执行角色、资源范围和目标资产访问检查。 |
| 严重 | 工作站 Agent 默认允许任意后端和浏览器来源，接受任意可执行文件路径，且默认关闭 TLS 校验。 | `scripts/terminal_agent.py`：默认限制本地平台来源，远程来源需显式配置；校验浏览器与后端来源一致、程序名匹配终端类型；默认校验证书，拒绝 SSH 选项形式的用户名及非法连接参数。 |
| 高 | 会话使用创建时保存的角色、用户名，并接受已停用或删除用户的遗留会话。 | `backend/api/users.py`：会话关联当前有效用户，使用实时角色和身份；个人资料及初始化向导改密时撤销其他会话。 |
| 高 | 普通用户修改个人资料时可自授变更审批组、修改身份名称；审计操作者可由请求伪造。 | `backend/api/users.py`：身份、组织组、变更审批组仅管理员可修改；审计身份和通知配置授权使用实际登录主体。 |
| 高 | 旧 PAM 请求/审批接口缺少权限声明，并信任请求中的申请人、审批人；通知已读状态也信任传入的用户 ID。 | `backend/api/pam.py`、`backend/api/notifications.py`：声明 PAM 操作权限、从会话取身份、禁止自审批、限制个人列表及通知状态归属。 |
| 高 | 角色配置或资源范围查询失败时回退为宽泛权限，未知角色配置也可能获得旧角色权限。 | `backend/core/rbac.py`：查询失败及未知配置均拒绝授权。 |
| 高 | 已启用 MFA 的用户仍可通过 setup 读取密钥，并通过 enable 覆盖密钥；二次认证临时票据可无限猜测。 | `backend/api/users.py`：禁止读取或覆盖已启用的密钥；条件更新防止并发覆盖；每张票据最多验证 5 次，并检查账号状态。 |
| 高 | 本地终端一次性令牌的读取与消费没有互斥，并发请求可能重复取得设备密码。 | `backend/api/system.py`：同一事务内 `SELECT ... FOR UPDATE`，串行化兑换；增加令牌随机长度。 |
| 高 | 初始化创建 `admin/admin`，异常密码可能被自动重置为弱口令，删除或重命名管理员后可能被重新创建。 | `backend/database/schema.py`、`backend/main.py`：仅空用户表允许通过显式强密码初始化；已有账号不自动重置或重建。数据库重置先验证配置，再进行备份或清空操作。 |

## 兼容性变化

- 全新安装或数据库重置必须配置 `INITIAL_ADMIN_PASSWORD`：至少 12 字符，包含大小写字母、数字及特殊字符，UTF-8 不超过 72 字节。缺失或不合格时初始化失败，不使用默认口令。
- 该配置不会更改已有账号密码。旧部署若仍使用原来的默认口令，需要管理员通过改密流程更换。
- 本地终端统一使用现有工作站 Terminal Agent，后端不会运行浏览器传来的程序路径。Agent 未安装或未运行时，需要先启动 Agent。
- Agent 默认仅信任 localhost/127.0.0.1 的 5010 端口。其他平台地址必须在工作站 Agent 环境中配置 `NEXORA_AGENT_ALLOWED_ORIGINS`。TLS 校验默认开启；旧 Agent 二进制文件未重打包，需要重建或使用已更新的 Python 脚本。
- 无有效会话的 AI 请求返回 401；脚本调用需要携带有效登录令牌。
- 关闭并重新绑定 MFA 需要走原有的密码验证流程。
- `.env.example`、`DEPLOY.md` 和 Windows 数据库重置提示已同步更新。

## 验证

新增 `backend/tests/security/test_audit_regressions.py`，覆盖匿名拒绝、角色权限、模板逃逸、会话降权/停用/删除/过期、改密撤销、自授审批权限、审计伪造、数据库异常拒绝、MFA 密钥保护与猜测上限、终端执行和资源范围、并发兑换、强密码初始化及数据库重置的提前校验。

新增 `backend/tests/security/test_terminal_agent_boundaries.py`，覆盖 Agent 默认来源拒绝、浏览器/后端来源不一致、可执行路径限制、TLS 默认校验、SSH 参数注入与密码参数隔离。现有 Web Agent 用例显式配置测试可信来源。

新增 `backend/tests/security/test_api_access_boundary.py`，覆盖实际应用的旧路由匿名拒绝、按方法兜底权限、已有只读 POST 权限、自服务兼容、精确白名单、管理员快捷依赖、通知归属及旧 PAM 审批身份保护。

测试通过临时运行器 `.codex-tmp/security_audit_run.py` 执行：先使用现有 PostgreSQL 测试工具创建空的 `nexora_pytest_security_audit_*` 数据库，将其作为子进程的 DATABASE_URL，再由共享测试夹具创建隔离模板和单用例数据库，结束后删除本轮创建的数据库。没有将业务数据库作为 pytest 初始化目标。

已完成的验证：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 核心安全及 Agent 回归 | `.venv/Scripts/python.exe .codex-tmp/security_audit_run.py backend/tests/security backend/tests/pam/test_web_agent_runtime.py backend/tests/pam/test_terminal_agent_autostart.py -q` | 39 passed（当时路由边界测试尚未新增） |
| 实际应用路由保护及 WebSocket 兼容 | `.venv/Scripts/python.exe .codex-tmp/security_audit_run.py backend/tests/security/test_api_access_boundary.py -q` | 22 passed，包含最后追加的稳定用户 ID 自审批拦截与 WebSocket 握手测试 |
| 路由挂接完整性 | 展开当前 FastAPI 应用的有效路由与依赖树 | 826 条 API HTTP 路由均挂接默认保护；精确白名单仍适用于公开入口 |
| TypeScript | `npm run lint` | 通过 |
| PostgreSQL 专用策略 | `.venv/Scripts/python.exe scripts/validate_postgresql_only.py` | 0 violation，PASS |
| Python 语法 | 对 20 个修改/新增 Python 文件执行 `ast.parse` | 通过 |
| 补丁格式 | `git diff --check` | 通过 |

最终全量后端回归：2035 passed、3 failed、26 subtests passed，耗时 29:56。失败仍为下列 3 项凭据测试；它们已在原始提交 `4250d83f` 的独立检出上复现，属于既有测试夹具连接复用问题，不是本轮安全修复引入。新增的安全与路由边界测试均通过。

其中三项凭据测试已通过独立的原始提交检出 `4250d83f` 复现：相同测试文件在原始代码上也是 **3 failed、14 passed**，均涉及测试夹具复用已经归还到池中的连接。这些文件不在本次凭据业务逻辑修改范围内：

- `test_bound_roles_read_from_vault_not_stale_asset_cache`
- `test_credential_update_is_seen_by_normal_role_without_changing_admin`
- `test_bound_device_cannot_use_independent_rotation_endpoint`

另一项旧 AI HTTP 用例原先断言匿名管理访问应当返回 200；本地 `backend/tests/test_ai_platform.py` 已改为先验证 401，再用真实测试管理员会话验证原有响应契约。该历史根目录测试文件被现有 `.gitignore` 忽略；新增安全测试均放在可跟踪的 `backend/tests/security/` 下。

按快速收尾要求，停止扩展审查并冻结修复。两组专项共 61 项通过；最终全量结果已记录为 2035 passed、3 项既有夹具失败。后续不扩展本轮修复范围。

## 范围与限制

本次为上述高风险代码路径的审查与修复，不代表全仓库不存在其他漏洞。未进行线上渗透、第三方依赖 CVE 全量核验、真实设备操作、工作站 Agent 实际启动或 Windows 安装包重打包。已建立的 SSH/WebSocket 长连接是否在账号降权后立即断开，不在本次 HTTP 会话校验修复的覆盖范围内。

原有 `.github/workflows/release.yml` 修改和 `.tmp/` 内容未纳入本次修复。
