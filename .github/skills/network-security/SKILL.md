---
name: "network-security"
description: "Applies network security controls for automation platforms. Invoke when implementing credential protection, API auth, RBAC, or security compliance checks."
---

# Network Security Engineer Skill

你是 Nexora 的安全工程师，负责凭据保护、API 鉴权、RBAC 权限控制和安全合规。

---

## 凭据加密 — `core/crypto.py`

- 使用 **Fernet (AES-128-CBC)** + **PBKDF2** 派生密钥。
- 密文以 `enc:v1:` 前缀标记，明文直接存储会被识别为未加密。
- 核心函数：
  - `encrypt_credential(plaintext) → str` — 加密并返回带前缀的密文。
  - `decrypt_credential(ciphertext) → str` — 识别 `enc:v1:` 前缀后解密。
- 密钥来源：`core/config.settings.SECRET_KEY`，通过 `.env` 配置。
- **规则**：任何涉及 password / community / secret 的字段写入数据库前必须调用 `encrypt_credential()`。

## API 鉴权与 RBAC — `core/rbac.py`

- Bearer Token 认证，Header: `Authorization: Bearer <token>`。
- 三级角色体系（权限递增）：
  - **Viewer** (level=1) — 只读。
  - **Operator** (level=2) — 执行自动化任务。
  - **Administrator** (level=3) — 全部权限。
- 路由注入方式：`current_user = Depends(require_role("Operator"))`。
- `require_role(min_role)` 返回 `CurrentUser` 对象，包含 `username`, `role`, `level`。
- **规则**：
  - 读取类接口最低 Viewer，写入/执行类接口最低 Operator，系统管理类 Administrator。
  - 权限检查在路由层完成，Service 层不重复校验。

## 日志脱敏 — `core/logging.py`

- `SanitizeFilter` 自动过滤日志中的敏感关键字（password, secret, token, community）。
- 日志文件 30 天自动轮转（TimedRotatingFileHandler）。
- **规则**：
  - 禁止在日志中输出明文凭据、IP 白名单、加密密钥。
  - 错误信息返回给前端时不包含堆栈和内部路径。

## 安全合规规则 — `services/compliance_service.py`

项目内置 8 条合规检查规则：

| ID       | 类型             | 检查内容                 |
|----------|------------------|--------------------------|
| MGMT-001 | config_absent    | 禁止 Telnet 启用         |
| MGMT-002 | config_present_any | 要求 SSH 启用           |
| SNMP-001 | snmp_not_default | SNMP community 非默认值  |
| LOG-001  | config_present_any | 要求配置日志服务器     |
| TIME-001 | config_present_any | 要求配置 NTP            |
| AAA-001  | config_present_any | 要求 AAA 认证启用       |
| L2-001   | config_present_any | 要求 STP 启用           |
| CFG-001  | snapshot_exists  | 要求存在配置快照         |

- 新增规则：在 `BUILTIN_RULES` 列表中添加字典即可。
- 规则类型扩展：修改 `_evaluate_rule()` 方法。

## 安全编码规范

- 输入验证使用 Pydantic schema，不在路由层手动校验。
- SQL 查询使用参数化绑定（`?` 占位符），禁止字符串拼接。
- API 错误响应不暴露内部实现细节。
- 设备连接超时必须设置上限（默认 30 秒）。
