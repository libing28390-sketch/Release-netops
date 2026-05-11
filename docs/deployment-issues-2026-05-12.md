# 部署与开发问题排查报告
**日期：** 2026-05-12
**环境：** 开发机 Windows / 测试环境 192.168.56.1:4300
**版本：** Nexora NetOps v0.1.1
**状态：** 🟡 部分修复，明天继续（MFA 一次性消费问题遗留）

---

## 问题汇总

今天围绕 `/access` 特权账号授权链路做了一轮排错修复。包括版本回退、前端编译报错（JSX 结构错误）、特权账号终端登录裸奔、MFA 验证码状态泄漏等。最后一个问题——MFA 动态码仍然可以被二次消费——已定位根因，尚未修复，留作明天。

---

## 一、版本回退到 `202605111734`

### 背景
今日上午在 `ff5a4e2` / `af1a41c` 两个新提交（定时作业 IP 校验、巡检错误上报改进）上发现不稳定，决定回退到昨晚的稳定版 `1ef869c (202605111734)` 再继续做 PAM 相关修复。

### 处理
- `git reset --hard 1ef869c`
- HEAD 回到 `1ef869c 202605111734`

---

## 二、`InterfaceMonitoringTab.tsx` 构建报错 `Unterminated regular expression`

### 现象
执行 `npm run build`：
```
D:/tools/netops/src/pages/InterfaceMonitoringTab.tsx:655:18: ERROR: Unterminated regular expression
```
esbuild 把多余的 JSX 标签解释成了正则字面量开头，报了个迷惑人的错。

### 根因
`202605111734` 这个提交把原来的"标题行 wrapper（`flex flex-col gap-4` + `sectionHeaderRowClass`）"重构成 `PageHero` 组件，并把主体包进了新的 `flex-1 overflow-auto` 滚动容器。但原本应该关闭 `flex flex-col gap-4` 的那个 `</div>`（L306）没有一起删除，反而变成了提前关闭新引入的滚动容器，结构完全错位，最终 JSX 标签数不匹配（开 48、关 49）。

### 修复
- 删除 `src/pages/InterfaceMonitoringTab.tsx` L306 处多余的一个 `</div>`
- 验证：div 开/关标签数 48/48 匹配，`npm run build` 通过

---

## 三、`PAMAuditTab.tsx` 构建报错 `Adjacent JSX elements must be wrapped`

### 现象
构建继续在另一个文件报错：
```
[vite:react-babel] Adjacent JSX elements must be wrapped in an enclosing tag.
File: src/pages/PAMAuditTab.tsx:565:4
```

### 根因
和 `InterfaceMonitoringTab.tsx` 的问题模式完全一致：`PageHero` 重构时多保留了一个 `</div>`。一开始我用 PowerShell 正则 `<div[\s>]` 去数标签，但没识别到 L476 那个自闭合的 `<div ... />`（遮罩背景），导致深度追踪误判，中途修复/又改回、反复一次。

### 修复
- 删除 `src/pages/PAMAuditTab.tsx` L564 处多余的一个 `</div>`
- 验证：构建通过（`built in 10.48s`）

### 经验教训
- 用正则数 JSX 标签嵌套深度时必须单独统计 `<div ... />` 自闭合形式，不能只数 `<div>` / `</div>`
- Babel 和 esbuild 在 JSX 失衡时报的错文本不同，但根因往往是同一个——缺/多一个闭合标签。以后看到 "Unterminated regular expression" 在 `.tsx` 里第一反应就是查 JSX 结构

---

## 四、`/access` 特权账号登录未经授权（严重安全漏洞）

### 现象
访问 `http://192.168.56.1:4300/access`，点任何设备的"终端登录 root"或"Web 登录 root"按钮，不需要任何审批/MFA 就能直接拿到 shell。

### 根因分析

**4.1 终端（本地 xshell）特权登录完全裸奔**
- 前端 `AccessCenterTab.tsx::handleAccessRequest` 的 `appType === 'xshell'` 分支**根本没判断 `identity === 'privileged'`**，管它是 user 还是 root 都直接 `fetch('/api/system/launch-terminal')`
- 后端 `backend/api/system.py::launch_terminal` 只把 `access_level` 写进 pam_sessions 做审计，**从未校验 MFA 或审批工单**，直接 `decrypt_credential` + `subprocess.Popen` 拉本地客户端
- 并且密码会以 `ssh://user:password@host` 形式出现在命令行上，`tasklist`/进程日志里都能看到

**4.2 Web 登录虽然有 MFA 但缺审批**
- `backend/api/pam.py::create_session` 对 admin 级只校验"6 位固定 PIN + 6 位动态码"
- 完全没有去查 `pam_access_requests` 表是否有 `status='approved'` 且未过期的工单
- 结果：虽然 UI 上叫"授权"，但后端其实只做了身份核验（MFA），**没有真正的审批动作记录**

**4.3 MFA 动态码的 fallback 后门**
- `backend/api/pam.py::request_mfa` L984-L986：如果审批人没配置飞书 webhook，会把 6 位码直接通过 `message: "授权码为: {code}（仅测试模式可见）"` 回到前端响应
- 这意味着用户可以在没有审批人参与的情况下自己给自己发码
- 本次没改，留明天讨论（改成仅 dev 模式允许，或干脆删掉）

### 修复（今日完成部分）

**后端：`backend/api/system.py::launch_terminal`**
- 新增 `mfa_code` / `fixed_pin` 两个字段
- `access_level == 'admin'` 时先调用 `_verify_mfa()`（复用 PAM 模块已有的校验函数）
- 未带 MFA → 返回 `requires_mfa: true` 让前端弹窗
- 校验失败 → 直接 `{success: false, error: ...}` 拒绝

**前端：`src/pages/AccessCenterTab.tsx`**
- `handleAccessRequest` 对 `appType === 'xshell' && identity === 'privileged'` 弹出 MFA 模态框（和 web 登录走同一个弹窗组件）
- 抽出独立的 `launchLocalTerminal()` 辅助函数，携带 `mfa_code` / `fixed_pin` 调用后端
- `handleMFAVerify` 根据 `mfaTarget.appType` 分流：`'xshell'` → `launchLocalTerminal`，`'web'` → `requestSession`

### 经验教训
- 任何"拉起本地客户端"的端点都必须视为和 "Web 受控会话" 同等敏感，不能因为传输层在用户本机就跳过验证
- 审批（approval）和身份认证（MFA）是两个正交的事，"过了 MFA" ≠ "有人批准了这次访问"。按 PAM 产品的语义，特权访问应当是：**审批人工单 approved + 本人 MFA 核身 双因子**

---

## 五、【遗留】MFA 验证码仍可被二次消费

### 现象
修完上面之后发现：
1. 用同一个 6 位动态码，先点"终端登录 root"通过，然后再点"Web 登录 root"，居然也能通过——**一码两用**
2. 点完第一次登录后 modal 自动关闭，再打开第二次 modal 时，倒计时、输入框内容都还在（**state 泄漏**）

### 今日已改的部分

**链路 A：后端可能的并发复用**
- 原 `_verify_mfa` 是"先 `get` 检查、成功才 `del`" 的非原子操作。并发或快速双击时，两个请求可能都读到同一个有效 code，两个都放行。
- 修成 `stored = mfa_store.pop(username, None)` —— 原子性地先拿走 code，任何失败路径都不会让它回流。

**链路 B：前端 state 泄漏**
- `showMFAModal=false` 时没清 `fixedPassword` / `dynamicCode` / `countdown` / `isSending`
- 抽出 `resetMFAState()` / `openMFAModal(target)` / `closeMFAModal()` 三个辅助函数，所有开/关弹窗路径都走这里
- `handleMFAVerify` 里先把 `code`/`pin` 快照出来，再 `closeMFAModal()`，最后用快照去 fetch —— 保证 UI 一定被清空

### 遗留问题（明天继续）

**即使上面两条都改了，还是能复用码。**用户实测：
- 第一次点"终端登录" → 通过 ✅
- 第二次点"Web 登录"，**重新输入同一个 code**（前端已清空，是用户自己手动输入的）→ 也通过 ❌

也就是说 `mfa_store.pop()` 没真正生效。可能的原因（待明天验证）：
1. `_verify_mfa` 里用的 `username` 参数在两次调用时不一致，导致 pop 的 key 和 store 的 key 对不上
   - 第一次终端登录：`requester_username = currentUsername` 来自 `/api/session` 的 `user.username`
   - 第二次 Web 登录：同样的来源，**应该**一样，但也可能因为 casing / 大小写 / 空格被不同模块处理过
2. 进程内存中 `mfa_store` 是模块级 dict，但如果 uvicorn 开了多 worker，两个 worker 各自有一份 `mfa_store`，第一次命中的 worker pop 掉了，第二次可能打到另一个 worker
3. `request_mfa` L984-L986 那个 fallback 把 code 直接回给前端，用户第二次点的时候前端并没有重新请求新 code，它只是把老 code 字符串再 POST 一次；如果后端 store 里没删掉或者用了不同 key，就会再次命中

### 明天的方案：**给验证码加唯一 nonce（编号）**

用户建议的方向是对的。设计如下：

**存储结构调整：**
```python
mfa_store[username] = {
    "nonce": uuid.uuid4().hex,   # 每次生成新码时附带一个唯一编号
    "code": "123456",
    "expire": time.time() + 300,
    "consumed": False,
}
```

**`/api/pam/mfa/request` 返回时带 nonce：**
```json
{"success": true, "nonce": "a1b2c3...", "message": "..."}
```

**前端缓存 nonce，verify 时一并提交：**
```json
POST /api/pam/sessions
{ "asset_id": ..., "access_level": "admin",
  "mfa_code": "123456", "fixed_pin": "......",
  "mfa_nonce": "a1b2c3..." }
```

**`_verify_mfa(username, fixed_pin, mfa_code, nonce)`：**
- 原子 `pop`
- 校验 `stored['nonce'] == nonce` + `code` 匹配 + 未过期
- 任何一项不符 → 拒绝
- 成功消费后再生成新 nonce 前，这个 username 不可能命中任何东西

**附加改动（待确认）：**
- `/api/pam/mfa/request` 是否要支持"同一个 username 发多次请求时主动让旧 nonce 失效"（防止用户重复点"发送验证码"后，旧的仍然有效）——明天一起讨论
- 把 fallback 后门改成仅 `settings.DEBUG == True` 时才返回明文 code，或者删掉
- 考虑把 `mfa_store` 从模块级 dict 挪到 Redis / SQLite，消除多 worker 不一致问题

---

## 今日代码改动清单

| 文件 | 说明 |
|---|---|
| `src/pages/InterfaceMonitoringTab.tsx` | 删除多余的一个 `</div>`（L306），修复构建错误 |
| `src/pages/PAMAuditTab.tsx` | 删除多余的一个 `</div>`（L564），修复构建错误 |
| `backend/api/system.py::launch_terminal` | 新增 admin 级 MFA 强制校验 |
| `backend/api/pam.py::_verify_mfa` | `get` + `del` 改为原子 `pop` |
| `src/pages/AccessCenterTab.tsx` | 终端登录接入 MFA 流程；新增 `openMFAModal` / `closeMFAModal` / `resetMFAState` 统一弹窗开关和 state 清理 |

---

## 明日待办

1. ⏳ **MFA 验证码 nonce 化**（本次核心遗留）
2. ⏳ 删除 `request_mfa` 中"飞书未配置就明文回显 code"的测试后门
3. ⏳ 讨论 `mfa_store` 是否挪到 Redis/SQLite（多 worker 场景）
4. ⏳ 为 `/access` 特权登录加上真正的 `pam_access_requests` 审批工单校验（目前只有 MFA 核身，没查工单）
