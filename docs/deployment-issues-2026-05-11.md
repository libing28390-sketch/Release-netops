# 部署与开发问题排查报告
**日期：** 2026-05-11
**环境：** 开发机 Windows / Ubuntu 24.04 LTS
**版本：** Nexora NetOps v0.1.1
**状态：** ✅ 全部已修复并验证

---

## 问题汇总

今天集中解决了 License 提示友好化、网络设备巡检架构设计、TextFSM 模板管理、定时作业安全漏洞、Cisco enable 提权等一系列问题。

---

## 一、License 无效提示不友好

### 现象
后台返回的错误是英文原文：
```
License is bound to machine '7294-18B8-E08A-5D49', but current machine is '3C8F-F629-86D1-30BF'. If this is a new deployment, set MACHINE_ID_OVERRIDE in .env.
```
前端直接把这段英文技术信息贴到界面上，用户看不懂，也不知道怎么操作。

### 根因
- `LicenseAdminTab.tsx` 里虽然有 `translateError()` 函数做中文翻译，但匹配逻辑 `lower.includes('machine id')` 匹配不到实际错误文本里的 `"bound to machine"`，导致翻译逻辑直接走到兜底分支，把原始英文显示出来
- 英文模式下直接 `return err`，没做任何优化

### 修复
**`src/pages/LicenseAdminTab.tsx`：**
1. 重写 `translateError()`，匹配模式改为 `bound to machine / machine_id / machine id` 三种写法，覆盖后端所有可能的错误文本
2. 用正则 `/bound to machine\s*['"]([\w-]+)['"]/i` 从英文错误里提取授权绑定的机器码和当前机器码
3. 删掉英文模式下的 `return err` 捷径，让英文用户也能看到友好提示
4. 新增 6 种错误细分：机器码不匹配、授权未绑定、未找到授权、文件损坏、签名失败、公钥缺失、已过期、版本超限
5. Status Banner 新增对比卡片：红色卡片显示授权绑定机器码，白色卡片显示当前机器码 + 一键复制按钮

### 经验教训
- 后端错误信息不要依赖前端精准匹配，建议后端在返回错误时附带 `error_code` 枚举（如 `MACHINE_ID_MISMATCH`、`LICENSE_EXPIRED`），前端按 code 翻译更可靠
- 错误提示应该给用户"可以做什么"的引导，不是只讲"出了什么问题"

---

## 二、网络设备巡检架构设计（Cisco/华为/H3C/Juniper/Arista）

### 现象
之前的巡检功能只有 Linux Shell 脚本方式（`_execute_shell_script` 用 Paramiko 执行 Bash），**网络设备完全无法巡检**。打开"操作管理"页面，Cisco/Huawei 标签下是空的。

### 根因
1. `_inspect_single_device` 只走 Paramiko SSH 执行 Shell 脚本，网络设备没有 Shell，执行会直接失败
2. 数据库里没有任何网络设备的巡检脚本 seed
3. 前端标签页硬编码 `platformFilter === 'Cisco'`，但 seed 写入的 `platform` 是 `cisco_ios`、`cisco_nxos`，筛选不出来
4. 前端只有 `All | Linux | Cisco | Huawei` 四个标签，缺 H3C / Juniper / Arista

### 修复（完整重构）

**后端：**
- `inspection_service.py` 增加 `_inspect_network_device()` 和 `_inspect_server_device()` 两个分支，按 platform 路由
- 网络设备走 Netmiko 驱动，一次 SSH 连接执行所有巡检命令，批量采集后离线解析（避免多次连接打满 VTY 线路）
- 新增 TextFSM 解析层，支持 5 种 `parse_type`：`numeric`（数值阈值）、`count`（统计行数）、`diff`（对比上次巡检）、`status`（关键词判断）、`info`（仅记录）
- 并发从 10 提升到 20

**数据库：**
- `inspection_items` 表新增 6 字段：`parse_type`、`textfsm_template`、`parse_field`、`parse_filter`、`fallback_regex`、`enabled`
- `scripts` 表新增 3 字段支持版本管理：`parent_script_id`、`script_family`、`is_latest`
- Seed 预置 7 个综合巡检脚本（Cisco IOS/NX-OS、华为 VRPv5/v8、H3C、Juniper、Arista）
- Seed 预置 23 条网络设备巡检指标（CPU/内存/接口Down数/BGP邻居Down数/路由总数 diff 对比）

**前端：**
- `ScriptManagementTab.tsx` 新增 `PLATFORM_GROUPS` 映射：`Cisco` → 匹配 `cisco_ios/nxos/xr/asa/ftd` 一族
- 平台标签扩展为 `All | Linux | Cisco | Huawei | H3C | Juniper | Arista`
- `InspectionItemsTab.tsx` 的 `method` 下拉新增 `CLI (网络设备)` 选项
- `InspectionItem` 接口定义加入扩展字段
- VENDORS 列表同时包含友好名（`Cisco`）和 platform code（`cisco_ios`）

### 数据库迁移注意
由于 `init_db` 有 `_db_initialized` guard，已运行的系统需要：
1. 重启后端服务（一次即可）
2. 或手动删除 `scripts/inspection_items` 里旧数据让 seed 重新跑

### 经验教训
- **前端硬编码枚举是最容易爆的地方**。凡是平台、厂商、状态这类有限集合，应该用映射表，并且尽量从后端 API 拉取
- Seed data 要覆盖所有字段默认值，不要依赖 `DEFAULT` 约束（`status='released'` 我就是依赖默认值导致的隐性问题）

---

## 三、Seed 脚本元数据不完整

### 现象
Seed 进库的 7 个 `insp_*` 脚本：
- `script_type` 都是 `shell`（默认值），但实际应该是 `cli`
- `author` 是 `admin`，应该是 `system`
- `created_at` / `updated_at` 为空
- 导致巡检引擎执行时可能走错分支（按 shell 脚本用 Paramiko 执行而不是 Netmiko）

### 根因
- 批量 INSERT 语句只指定了 6 列 `(id, name, content, description, platform, category)`，其他字段走 `DEFAULT` 或 NULL
- `ON CONFLICT DO UPDATE SET` 也只更新了这些字段

### 修复
在 INSERT 之后用单独的 UPDATE 语句补齐：
```python
for sid in insp_script_ids:
    cursor.execute(
        "UPDATE scripts SET script_type=?, status=?, author=?, "
        "submitter_name=?, approver_username=?, "
        "created_at=COALESCE(NULLIF(created_at, ''), ?), "
        "updated_at=? WHERE id=?",
        ('cli', 'released', 'system', 'system', 'system', now, now, sid)
    )
```

### 经验教训
- Seed data 能一次性写全就别依赖默认值和 UPSERT
- `created_at` 用 `COALESCE(NULLIF(..., ''), ?)` 确保已存在记录的创建时间不被覆盖

---

## 四、`now` 变量未定义导致初始化失败

### 现象
```
UnboundLocalError: cannot access local variable 'now' where it is not associated with a value
```
在补 seed 脚本元数据的 UPDATE 语句时，引用了 `now` 变量，但当时它还没赋值。

### 根因
`now = _beijing_now_iso()` 的赋值位置在 `# Seed/Update default items` 下面，但我新增的 UPDATE 语句放在了 `std_scripts` 的 cursor.executemany 之后、default_items 之前。

### 修复
把 `now = _beijing_now_iso()` 提前到 `Seed standard scripts` 之前，原位置的重复赋值删除。

### 经验教训
- 新增代码前先查清依赖的变量在哪里定义
- Python 里 UnboundLocalError 这种错误 IDE 的 linter 其实能提前发现

---

## 五、TextFSM 模板管理功能

### 现象
需要支持网络设备多厂商的 CLI 输出解析，但：
- ntc_templates 包里缺少华为 CPU/内存/路由统计的模板
- H3C `display cpu-usage` / `display memory` 也没有
- 模板文件在 `.venv/Lib/site-packages/ntc_templates/templates/` 里，升级包会被覆盖
- 没有 UI 让用户自己加模板

### 根因
ntc_templates 是社区维护的公共库，对国内厂商覆盖不全，而且包目录不应该直接修改。

### 修复
**双目录合并策略：**
- `data/textfsm_templates/` ← 自定义目录（持久化，不受包升级影响）
- `ntc_templates/templates/` ← 内置目录（只读，来自包）
- 解析时先查自定义目录，同名时自定义优先

**新增后端：**
- `core/textfsm.py` 重写，新增 `parse_with_textfsm()`、`list_templates()`、`save_custom_template()`、`parse_with_template_content()` 等函数
- `api/textfsm_templates.py` 提供 6 个 REST API（列表/查看/创建/更新/删除/在线测试）

**新增前端：**
- `src/pages/TextFSMTemplatesTab.tsx` 完整的管理页面
- 左侧模板编辑器（含平台/命令/文件名自动生成）
- 右侧样本输出 + 在线测试（粘贴真实输出实时验证解析结果）
- 内置模板只读查看，自定义模板可增删改
- 路由 `/automation/textfsm-templates`

**预置 7 个自定义模板：**
- `huawei_vrp_display_cpu_usage.textfsm`（同时支持 VRPv5/v8）
- `huawei_vrp_display_memory_usage.textfsm`
- `huawei_vrp_display_ip_routing_table_statistics.textfsm`
- `hp_comware_display_cpu_usage.textfsm`
- `hp_comware_display_memory.textfsm`
- `hp_comware_display_ip_routing_table_statistics.textfsm`
- `juniper_junos_show_chassis_routing_engine.textfsm`

### 经验教训
- 任何依赖第三方包的配置/模板，都应该有"扩展层"让用户覆盖
- 在线测试功能是提升易用性的神器，用户不需要懂 TextFSM 语法细节也能写模板

---

## 六、定时作业修改脚本不走审批（安全漏洞）

### 现象
- 创建脚本：要走审批流程
- 创建定时作业：要走审批流程
- **修改已有定时作业的 `script_id` / `commands` / `cron_expr`：无任何审批**

这是个绕过审批的漏洞：攻击者只要能创建一个无害脚本（比如 `show version`）通过审批，然后通过编辑功能把 `script_id` 换成高危脚本（比如 `reload`），就能定时执行危险操作。

### 根因
`api/scheduled_jobs.py` 的 `update_scheduled_job()` 函数**完全没有审批校验**，只做了字段合法性校验。

### 修复
引入"敏感字段"概念：

```python
sensitive_changed = False
if action_type != row["action_type"]:
    sensitive_changed = True
if new_script_id != row["script_id"]:
    sensitive_changed = True
if new_commands != row["commands"]:
    sensitive_changed = True
if cron_expr != row["cron_expr"]:
    sensitive_changed = True

if sensitive_changed:
    # 必须有 approval_token + approval_code
    ok, err = verify_code(approval_token, approval_code)
    if not ok:
        raise HTTPException(403, err)
    consume_approval(approval_token)
```

只修改名称、描述、device_scope 等元数据不需要审批；但凡涉及**执行内容或触发时机**的修改，必须走审批。

### 经验教训
- **创建走审批 ≠ 修改也走审批**，这是极其常见的漏洞模式
- 审批流程的设计原则：**凡是能影响"最终执行效果"的字段变更，都应该走审批**
- 审计日志 severity 根据是否触及敏感字段分级：`high`（敏感）/ `medium`（元数据）

---

## 七、Cisco 路由器 Enable 提权失败 ⚠️ 最典型的"不加这行配置就完蛋"问题

### 现象
巡检执行时 Cisco 路由器一直报错，手动给设备加了这条配置后立刻好了：
```
R1(config)# aaa authentication enable default none
```

### 根因详解

**Cisco AAA 模型的两个独立认证入口：**

| 入口 | 作用 | 默认配置 |
|------|------|---------|
| `aaa authentication login default ...` | 控制 SSH/Telnet 登录认证 | 用 AAA 方法组（TACACS / RADIUS / 本地） |
| `aaa authentication enable default ...` | 控制 `enable` 提权认证 | 默认用 `enable secret` 或 `enable password` |

**问题链：**
1. 设备开启了 `aaa new-model`
2. 但没配置 `enable secret` 也没有配 `aaa authentication enable default`
3. Netmiko 调用 `conn.enable()` → 设备返回 `Password:` 提示
4. Netmiko 尝试发送 `params['secret']`，但代码里 `secret` 为空
5. 认证失败，要么挂住，要么被设备踢掉

**加上 `aaa authentication enable default none` 后：**
- `none` 关键字 = 不做任何认证
- 设备收到 `enable` 命令后直接允许进入特权模式，不再提示密码
- Netmiko 畅通无阻

### 当前代码是否适配 Enable 密码场景？

**修复前（静默吞异常版本）：**
```python
try:
    conn.enable()
except Exception:
    pass   # ← 问题：enable 失败不报错，后续 show 可能没权限
```

**修复后（智能判断）：**
```python
if params['device_type'] in ('cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa'):
    try:
        prompt = conn.find_prompt()
        if prompt.strip().endswith('>'):
            # privilege 1，需要提权
            try:
                conn.enable()
            except Exception as en_err:
                logger.warning(
                    f"Enable mode failed: {en_err}. "
                    f"Configure 'enable secret' or 'aaa authentication enable default none' on the device."
                )
        # 已经是 '#' 则跳过，privilege 15 账号无需 enable
    except Exception:
        # find_prompt 失败时盲 enable
        try:
            conn.enable()
        except Exception:
            pass
```

### 三种场景都支持

| 场景 | 账号权限 | 设备配置 | 当前代码行为 |
|------|---------|---------|------------|
| A | privilege 15 | 任意 | `find_prompt()` 返回 `#`，跳过 enable() |
| B | privilege 1 | 配了 enable secret | 账号表填 `enable_password` → Netmiko 用该密码 enable |
| C | privilege 1 | `aaa authentication enable default none` | enable() 发送后设备直接放行，无需密码 |
| D | privilege 1 | 都没配 | enable() 失败，代码 warning 但不阻断，提示用户 |

### 设备端建议配置

对于平台统一接入的设备，推荐以下两种配置之一（任选）：

**方案一：使用 enable secret（传统方式）**
```
enable secret <PASSWORD>
```
在平台设备表中填入 `enable_password` 字段，平台自动使用。

**方案二：无 enable 密码（信任 SSH 登录用户）**
```
aaa authentication enable default none
```
SSH 登录通过后直接允许 enable，无需额外密码。适用于 SSH 已经用 TACACS/RADIUS 强认证的场景。

**方案三：privilege 15 账号**
```
username admin privilege 15 secret <PASSWORD>
```
登录后直接进入特权模式，无需 enable。

### 经验教训
- **Netmiko 的 `conn.enable()` 是一个复杂黑盒**，失败原因可能是密码错、AAA 策略、提示符不识别等多种
- 永远不要 `try: X except: pass` 静默吞异常，至少记个 warning 日志
- 网络设备的"默认行为"严重依赖厂商和版本，不能假设
- 平台文档应该明确告诉用户：**设备接入平台前需要做的 3 件事**（SSH 开启、用户权限、enable 策略）

---

## 八、前端过滤逻辑匹配不上后端数据

### 现象
截图里"操作管理"页面点击 Cisco 标签，下面一片空白。但数据库里明明有 `insp_cisco_ios_full` 这个脚本。

### 根因
```typescript
// 旧代码（第 140 行）
scripts.filter(s => s.platform === platformFilter)   // platformFilter = "Cisco"
```
但 seed 的脚本 `platform = "cisco_ios"`，`"cisco_ios" !== "Cisco"` 永远是 `false`，过滤结果必然为空。

### 修复
```typescript
const PLATFORM_GROUPS: Record<string, string[]> = {
  'All': [],
  'Linux': ['Linux', 'linux', 'ubuntu', 'centos'],
  'Cisco': ['cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd', 'Cisco'],
  'Huawei': ['huawei_vrp', 'huawei_vrpv8', 'huawei', 'Huawei'],
  // ... H3C / Juniper / Arista
};

const matchesPlatformGroup = (scriptPlatform: string, group: string): boolean => {
  if (group === 'All') return true;
  const codes = PLATFORM_GROUPS[group] || [group];
  return codes.some(c => c.toLowerCase() === (scriptPlatform || '').toLowerCase());
};
```
一个厂商标签可以匹配该厂商下的多个具体 OS 平台，同时兼容老数据里直接写 `"Cisco"` 的记录。

### 经验教训
- 前后端约定枚举值时，要对齐大小写和具体 vs 抽象（是 `Cisco` 还是 `cisco_ios`）
- 映射表比 `===` 严格比较更健壮

---

## 快速排查命令

```bash
# 检查 seed 数据是否入库
D:\netsops\.venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'backend')
from database import get_db_connection
conn = get_db_connection()
rows = conn.execute(\"SELECT id, platform, script_type FROM scripts WHERE id LIKE 'insp_%'\").fetchall()
for r in rows: print(dict(r))
"

# 重新触发 seed（不会删除已有数据，只会更新）
D:\netsops\.venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'backend')
import database
database._db_initialized = False
database.init_db()
"

# 验证所有 TextFSM 模板语法正确
D:\netsops\.venv\Scripts\python.exe -c "
import pathlib, textfsm
for p in pathlib.Path('data/textfsm_templates').glob('*.textfsm'):
    textfsm.TextFSM(open(p, encoding='utf-8'))
print('OK')
"

# 设备端排查 enable 问题
# 登录路由器执行：
show running-config | include aaa
show running-config | include enable
# 确认至少有以下之一：
#   enable secret <password>
#   aaa authentication enable default none
```

---

## 设备接入平台 Checklist（给用户参考）

新设备加入平台前，在设备上确认以下配置已正确：

### Cisco IOS/IOS-XE
```
! 1. SSH 服务已开启
ip ssh version 2

! 2. 用户已创建且权限正确（任选其一）
username admin privilege 15 secret xxx    # 方案A：privilege 15，无需 enable
! 或
username admin privilege 1 secret xxx     # 方案B：privilege 1 + 下面任一
enable secret xxx                          # B1：配 enable secret
! 或
aaa authentication enable default none     # B2：不要 enable 密码

! 3. VTY 允许 SSH
line vty 0 15
 transport input ssh
 login local      ! 或 aaa 认证
```

### 华为 VRP
```
# 创建 AAA 用户
aaa
 local-user admin password cipher xxx
 local-user admin service-type ssh
 local-user admin privilege level 15    # 直接给最高权限

# SSH 配置
stelnet server enable
ssh user admin service-type stelnet
ssh user admin authentication-type password
```

### H3C Comware
```
# SSH 服务
ssh server enable

# 本地用户
local-user admin class manage
 password simple xxx
 service-type ssh
 authorization-attribute user-role network-admin

# VTY
line vty 0 15
 authentication-mode scheme
 user-role network-admin
```

### Juniper JunOS
```
# SSH 服务
set system services ssh root-login allow
set system login user admin class super-user authentication plain-text-password
```

---

## 总结

今天共识别并修复了 8 个问题，关键收获：
1. **不信任默认值** — 无论是前端枚举、Seed data 字段、还是设备出厂配置
2. **错误提示要引导** — 告诉用户出了什么问题的同时，明确告诉 Ta 下一步怎么办
3. **审批流不能只守创建** — 所有能改变最终行为的路径（创建/修改/复制/导入）都要守
4. **多厂商适配是长期工作** — TextFSM 模板、CLI 方言、AAA 策略各家都不一样，要建立可扩展机制让用户自己补
5. **静默吞异常是技术债** — 至少记个 warning 日志，好为将来的排查留线索
