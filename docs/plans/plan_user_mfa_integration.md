# 实施计划: 用户多因素二次认证 (MFA / 2FA) 集成

本方案旨在为系统用户引入可选的 **MFA（双因子二次认证）** 机制。启用后，用户在常规用户名密码验证成功后，必须输入手机身份验证器（如 Google Authenticator / Microsoft Authenticator）生成的 6 位动态验证码才能成功登录系统。

## 用户审核要点

> [!IMPORTANT]
> **关键设计与依赖说明：**
> 1. **零外部 Python 依赖**：为规避环境中的 SOCKS 代理及库安装问题，我们将使用纯 Python 代码在后端计算和验证标准 RFC 6238 TOTP 动态码，不需要安装任何外部 `pip` 包（如 `pyotp`）。
> 2. **前端离线二维码生成**：我们已成功在前端集成了开源且流行的 `react-qr-code` 依赖包，二维码的生成在浏览器中完全离线完成，无网络访问开销与泄露隐患。
> 3. **全流程可选项配置**：用户默认不开启 MFA，可以自由在“个人设置”中通过密码验证 ➜ 扫码绑定 ➜ 校验启用；已启用的用户也可以随时校验当前密码以关闭 MFA。

---

## 拟定变更内容

### 1. 数据库定义与迁移

#### [MODIFY] [schema.py](file:///e:/data/netsops/backend/database/schema.py)
- 在 `users` 表结构初始化位置使用 `ensure_column` 添加以下两个关键属性列：
  * `mfa_secret`：`TEXT DEFAULT ''` — 用于存放加密/明文的用户 TOTP Base32 密钥。
  * `mfa_enabled`：`INTEGER DEFAULT 0` — 标识用户是否启用了 MFA 二次验证 (0-未启用，1-启用)。

---

### 2. 后端核心服务与 API 开发

#### [MODIFY] [users.py](file:///e:/data/netsops/backend/api/users.py)
- **纯 Python 实现 TOTP 验证算法**：
  编写 RFC 6238 标准的 `verify_totp(secret, code, window=1)` 校验算法，以及 `generate_totp_secret()` 生成 Base32 密钥。
- **登录接口优化**：
  修改 `@router.post("/login")`：如果常规密码匹配成功，但该用户 `mfa_enabled == 1`：
  - 不生成正式会话令牌。
  - 生成一个 5 分钟有效的临时令牌 `temp_token`，存入内存表 `_temp_mfa_tokens` 中。
  - 返回响应 `{ "success": true, "mfa_required": true, "temp_token": temp_token }`。
- **MFA 二次校验接口**：
  新增 `@router.post("/mfa/verify")` 接口（公开）：
  - 验证传入的 `temp_token` 是否合法。
  - 校验动态验证码。如果成功，则销毁 `temp_token`，生成正式会话 Token 并登录。
- **个人设置绑定/解绑接口**：
  - 新增 `POST /api/mfa/setup` (需要鉴权)：生成临时 TOTP 密钥及扫码 URI。
  - 新增 `POST /api/mfa/enable` (需要鉴权)：检验验证码并正式将密钥写入用户数据库中，开启 `mfa_enabled`。
  - 新增 `POST /api/mfa/disable` (需要鉴权)：关闭用户 MFA 状态并清空密钥。

---

### 3. 前端交互页面调整

#### [MODIFY] [useAuth.ts](file:///e:/data/netsops/src/hooks/useAuth.ts)
- 增加 `mfaRequired`、`tempMfaToken` 状态。
- 如果 `/api/login` 接口返回 `mfa_required: true`，则拦截登录态，进入 MFA 码输入阶段。
- 新增 `handleMfaVerify(code)` 提交方法。

#### [MODIFY] [LoginScreen.tsx](file:///e:/data/netsops/src/components/LoginScreen.tsx)
- 新增 `mfaRequired` 属性及 `onMfaSubmit(code)` 回调。
- 当 `mfaRequired` 为 `true` 时，表单区切换为 MFA 6 位验证码输入界面，支持退回普通登录界面。

#### [MODIFY] [ProfileModal.tsx](file:///e:/data/netsops/src/components/ProfileModal.tsx)
- 引入 `react-qr-code` 显示二维码。
- 在“个人资料管理”面板的“固定安全码”下方插入 **MFA 二次身份验证控制卡片**：
  * **已开启状态**：显示“已启用二次认证”，并提供“关闭”按钮（需要确认当前密码）。
  * **未开启状态**：显示“未启用二次认证”，并提供“开启配置”按钮。点击后拉取 setup 接口生成并渲染二维码，展示密钥，提示用户扫码并输入 6 位动态验证码进行验证绑定。

---

## 验证计划

### 自动化与手动测试方案
1. **单元测试验证**：
   - 编写 `backend/tests/test_mfa_totp.py` 自动化测试套件：
     * 验证纯 Python 实现的 TOTP 算法正确性，以及漂移窗口容错能力。
     * 模拟常规账号密码登录、临时令牌获取、MFA 验证通过登录的全链路。
2. **手动集成测试**：
   - 启动系统，在“个人中心”进入配置，确保扫码可以被 Google Authenticator 正常解析并成功开启。
   - 退出登录，输入正确账号密码，确认拦截在 MFA 页面。输入 App 上的 6 位数字，确认可以成功进入系统。
   - 再次进入个人中心，关闭 MFA，测试退出登录后再次登录是否无需二次验证即可进入。
