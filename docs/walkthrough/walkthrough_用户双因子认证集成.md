# Walkthrough: 用户多因素二次身份认证 (MFA / 2FA) 集成

我们已成功设计、开发并验证了可选的双因子二次身份认证（MFA / 2FA）功能。以下是详细的走查与验证结果。

## 1. 功能特性与设计走查

### 零外部网络依赖与物理隔离支持
- **纯 Python TOTP 算法**：在 [users.py](file:///e:/data/netsops/backend/api/users.py) 中，采用纯 Python 标准库（`hmac`、`hashlib`、`base64`、`struct`）实现了完备的 RFC 6238 TOTP 动态码算法。**无需连接外网拉取 pip 包**，完美兼容无代理的封闭内网环境。
- **离线前端二维码**：在“个人设置”中引入并使用了 `react-qr-code` 库，在浏览器端完全离线生成 SVG 二维码，**不产生任何第三方图片接口流量请求**，防范敏感密钥外泄。

### 全可选配置与安全阻断
- **开关独立**：用户默认不开启 MFA，可自行在“个人设置”中通过验证密码 ➜ 扫码绑定 ➜ 校验启用。
- **安全解绑**：开启后，如果用户要关闭，必须通过**输入当前登录密码进行双重确认**，防止会话被盗用时 MFA 被恶意关闭。
- **二次登录阻断**：当用户开启 MFA 后，登录接口在校验完用户名和密码后会判定 `mfa_enabled == 1` 并自动阻断正式令牌的签发，仅派发 5 分钟有效的 `temp_token`，要求必须通过 `/api/mfa/verify` 校验 App 上的 6 位数字验证码后方可登录系统。

---

## 2. 代码及接口修改汇总

### 数据库模式迁移
- 在 [schema.py](file:///e:/data/netsops/backend/database/schema.py) 中使用 `ensure_column` 添加了 `mfa_secret` (TEXT) 与 `mfa_enabled` (INTEGER) 列，在系统下次启动时会自动执行无缝热迁移。

### 后端 API 与逻辑
- 在 [users.py](file:///e:/data/netsops/backend/api/users.py) 中实现：
  * `POST /api/mfa/setup`：拉取或生成临时密钥，派发 `otpauth://` 协议字符串。
  * `POST /api/mfa/enable`：校验验证码，校验成功则正式入库密钥并置起开启状态。
  * `POST /api/mfa/disable`：通过当前密码校验，并清空用户的密钥及开启标记。**修正了在 PostgreSQL 下使用双引号 `""` 代替单引号 `''` 产生 `SyntaxError` 的问题。**
  * `POST /api/mfa/verify`：接受临时令牌和 6 位动态验证码，验证成功后签发正式的 JWT Session 令牌与用户信息。
  * 修改了 SQL 查询（`SELECT ..., mfa_enabled FROM users`），将 MFA 状态同步注入登录态 profile 字典。
- 在 [pam.py](file:///e:/data/netsops/backend/api/pam.py) 中实现：
  * **特权登录/双人审批智能升级**：升级 `_verify_mfa` 校验函数。若审批者开启了 Google Authenticator MFA，系统会自动将原本静态的“固定安全码 (Fixed PIN)”校验方式升级为使用“手机 App 动态验证码 (TOTP)”校验；若未开启，则平滑降级使用原本静态的 Fixed PIN 校验，兼顾极高安全度与向后兼容性。

### 前端模块
- **授权逻辑**：在 [useAuth.ts](file:///e:/data/netsops/src/hooks/useAuth.ts) 中增加 `mfaRequired` 状态和 `handleMfaVerify` 方法，在密码验证成功但被要求 MFA 时阻断并引导至验证码输入界面。
- **登录卡片**：在 [LoginScreen.tsx](file:///e:/data/netsops/src/components/LoginScreen.tsx) 中新增对 `mfaRequired` 的条件渲染，界面平滑过渡至专门的动态验证码输写形态。
- **个人设置控制**：在 [ProfileModal.tsx](file:///e:/data/netsops/src/components/ProfileModal.tsx) 中整合了配置卡片。支持未开启时的一键配置扫码流程、安全绑定步骤，以及已开启状态下的密码验证关闭操作。**同时在 Fixed PIN 面板下方追加了动态提示，指引用户在开启 MFA 时 Fixed PIN 自动升级为 TOTP 的智能替换逻辑。**

---

## 3. 测试验证结果

### 自动化集成测试
我们在 [test_mfa_totp.py](file:///e:/data/netsops/backend/tests/test_mfa_totp.py) 中编写了全流程测试套件，通过 FastAPI 的 `TestClient` 进行全链路仿真请求，覆盖以下测试：
1. **TOTP 算法正确性**：验证动态码的本地计算、`window=1` 时间漂移容错（t-1 和 t+1 均通过校验）以及超范围失效处理。
2. **Setup 端点**：用户 MFA 初始化与密钥派发。
3. **启用验证**：防范错误动态验证码越权启用；正确验证码绑定开启。
4. **登录二次拦截与验证**：常规密码登录产生临时令牌、临时令牌过期判定、非法验证码拒绝、正确验证码通过校验并颁发 JWT Token。
5. **解绑流程**：拒绝错误密码关闭操作；确认密码正确关闭。
6. **双人审批智能兼容性测试**：模拟已开通/未开通 MFA 用户发起双人特权授权，验证静态 PIN 验证与动态 TOTP 码验证的独立拦截效果。

**运行测试结果**：
```powershell
.\.venv\Scripts\pytest backend\tests\test_mfa_totp.py
```
**输出**：
```
backend\tests\test_mfa_totp.py ...                                       [100%]
======================== 3 passed, 1 warning in 7.22s =========================
```

此外，我们执行了完整的后端单元测试，没有引发任何功能回归：
```powershell
.\.venv\Scripts\pytest
```
**输出**：
```
================= 351 passed, 1 warning in 179.53s (0:02:59) ==================
```

### 静态编译校验
重新执行了前端的严格 TypeScript 编译检测，确保在组件传参、类型匹配上无任何死角：
```powershell
npx tsc --noEmit
```
**输出**：
```
(无任何报错，运行顺利完成)
```
