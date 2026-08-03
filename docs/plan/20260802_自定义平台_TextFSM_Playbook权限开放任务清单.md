# Nexora 自定义平台、TextFSM 与 Playbook 权限开放任务清单

> 日期：2026-08-02
> 状态：P0 审查未通过（后端基础骨架已交付，存在阻断问题，暂不具备进入 P1 或开放租户写入的条件）
> 目标：让租户用户能够安全地适配中兴、锐捷、迪普、迈普等多型号设备，并在受控范围内编写、测试和发布 TextFSM 与 Playbook。
> 核心原则：开放声明式平台、命令映射、解析模板和受控编排，不开放任意 Python、Shell、文件系统路径或自定义连接驱动。

## 0. 2026-08-03 P0 执行结果审查

### 0.1 审查结论

**结论：P0 未如期完整完成，当前结果判定为“部分交付，审查不通过”。**

- 计划提交 `31c6261` 的时间为 2026-08-02 23:53，P0 实现提交 `3f84c2d` 的时间为 2026-08-03 00:20；若按 8 月 2 日自然日作为截止时间，提交晚 20 分钟。
- 已完成数据库注册表、20 个 Action Definition、11 个 SYSTEM Profile、基础 Release 流程、部分 API 和 `execute_platform_action()` 骨架。
- 未完成 P0 要求的唯一执行入口、全部消费者迁移、TextFSM Sandbox、字段契约、缓存及精确失效、完整权限模型、原始回显安全、Playbook 版本模型、功能开关和完整质量门禁。
- 已复现 H3C 动作种子为 0、现有厂商回归失败、P0 测试夹具不可复现等阻断问题；在修复并重新通过门禁前，不应开放租户创建、审核、发布或执行自定义平台动作。

### 0.2 P0 分项完成度

| 清单范围 | 审查状态 | 已完成 | 主要缺口 |
| --- | --- | --- | --- |
| 3.1 标准逻辑动作注册表 | 部分完成 | 创建 `action_definitions`，注册 20 个标准动作，包含名称、用途、风险、部分字段、回显和记录限制、消费者 | `device_types`、可选字段、字段类型等定义为空；H3C Profile 未获得任何动作映射；未验证“未适配”动作必须显式拒绝 |
| 3.2 Platform Action Resolver | 部分完成/不通过 | 新增 `execute_platform_action()`，仅读取当前 PUBLISHED Release，具备单命令只读校验、输出限制和部分追溯字段 | 不是唯一运行入口；未校验 Site/设备作用域和消费者；未执行 TextFSM Sandbox；未调用标准 Normalizer；未校验字段契约；连接失败与命令失败未分码；无 Release/模板缓存及精确失效；未使用动作超时配置 |
| 3.3 现有调用链迁移 | 未完成 | 拓扑发现和 `operational_data_service` 开始从平台注册表解析命令 | 两处仍自行连接和执行命令，绕过 `execute_platform_action()`；CMDB、诊断、巡检、IP 定位、Playbook、快速查询前端等未完整迁移；旧厂商命令目录仍保留 |
| 3.4 SYSTEM 平台种子 | 部分完成/不通过 | 注册 Cisco、Huawei、H3C、Juniper、Arista 及 6 个国产设备 Profile | `h3c_comware` 的 `parser_platform` 为 `hp_comware`，动作目录却以 `h3c_comware` 为键，隔离迁移验证得到 0 个 H3C 动作；未形成真实 `show version` 样例与“未适配”标记闭环 |
| 4.1 表结构 | 部分完成 | 新增 Profile、Release、Action、Parser、样例、识别规则及审计等 10 张表 | 未新增或补齐 `playbook_versions`；仅有 `playbook_release_audit_logs` |
| 4.2 约束与索引 | 部分完成/不通过 | 有平台/模板编码检查、部分外键、唯一索引、事务发布和禁止创建者自审 | `devices.platform_profile_id` 与 `platform_profiles.current_release_id` 无外键；状态约束不完整；`lock_version` 未参与更新条件，不具备真正乐观锁；Release 编号生成和回滚缺少完整并发锁保护；模板版本绑定未校验租户、Profile 和 PUBLISHED 状态 |
| 4.3 兼容迁移 | 部分完成 | 增加设备绑定字段并回填 SYSTEM Profile；导入现有 TextFSM 文件并计算 checksum | 无迁移预览/冲突报告/兼容开关；无只读 Manifest；未绑定版本的动作仍调用文件式 `smart_parse_cli`，不能保证模板版本和 checksum 可追溯 |
| 5.1/5.2 权限与角色 | 未按计划完成 | RBAC 增加 `view/edit_draft/submit/approve/publish/rollback` 等通用动作词汇 | 未落地 `platform.*`、`textfsm.*`、`playbook.*` 等资源级权限项和推荐角色；当前 Operator 被全局授予 approve、publish、rollback，未实现职责分离 |
| 5.3 命令安全 | 部分完成/不通过 | 拒绝换行、管道、多命令拼接和非 `show/display/get` 前缀；`get_running_config` 仅 Administrator 可执行 | 前缀不是按连接驱动配置；缺少命令预览；拒绝/未支持动作未完整审计；敏感动作只按角色字符串判断，未做资源权限与 Site/设备作用域校验 |
| 5.4 原始回显安全 | 未完成 | 无可确认的完整交付 | 无保留期、脱敏、加密、读取/下载审计；`get_running_config` 的原始配置直接放入 API 返回值 |
| 11 API 清单 | 部分完成 | 实现 Profile 查询/创建、Release 创建/校验/提交/审核/发布/回滚、动作查询/更新，并额外提供动作执行 API | Parser Template、设备识别/绑定、Playbook 版本与发布 API 均未实现；稳定请求契约仍使用未类型化 `dict` |
| 13 上线策略 | 未完成/阻断 | 无 | 未实现 `PLATFORM_REGISTRY_ENABLED`；Router 默认注册，且 Operator 当前可创建、审核和发布，违反第一阶段“仅 SYSTEM、只读、不开放用户写入”的要求 |

### 0.3 阻断问题

1. **H3C 动作映射为空。** `SYSTEM_PROFILES` 将 H3C 解析平台定义为 `hp_comware`，`PLATFORM_ACTION_COMMANDS` 却使用 `h3c_comware` 键；迁移按 `parser_platform` 取动作，导致 H3C PUBLISHED Release 的动作数为 0。拓扑和快速采集会返回 `UNSUPPORTED_ACTION` 或空命令。
2. **“唯一执行入口”未成立。** 拓扑和 Operational Data 仅调用 `resolve_action_mapping()` 取命令，仍在各自服务中连接、执行和解析，绕过 Resolver 的权限、审计、输出限制与追溯逻辑；其余消费者尚未迁移。
3. **租户写入提前开放且职责未隔离。** 未设置功能开关，平台 Router 默认启用；Operator 同时拥有 create、approve、publish、rollback，虽然阻止创建者自审，但其他 Operator 仍可互审并发布。
4. **模板执行安全与追溯不达标。** `parse_with_template_content()` 在 FastAPI 进程内直接执行，无独立 Worker、超时和资源限制；字段契约未验证。隔离迁移中 Cisco 20 个动作仅 1 个绑定模板版本，Arista/Juniper 为 0 个，未绑定动作继续走文件式解析，无法固定模板版本/checksum。
5. **跨租户模板绑定风险。** 更新 Release 动作时只检查 `parser_template_version_id` 是否存在，未校验模板归属租户、平台、Profile 或发布状态，可引用其他租户或 DRAFT 模板版本。
6. **迁移与并发约束不足。** 缺少关键外键、真正的乐观锁和完整行锁；发布前校验与状态转换分属两个事务，存在校验结果与最终发布内容之间的竞争窗口。
7. **质量门禁记录与当前提交不一致。** 实施记录声称 focused tests 12 passed、vendor audit 279 passed；本次在当前提交复核均未通过，测试夹具也未随提交提供可复现实现。

### 0.4 本次复核证据

| 检查 | 结果 |
| --- | --- |
| 隔离 SQLite 执行 `m0072_platform_registry_p0.upgrade()` | 成功创建 20 个 Action Definition 和 11 个 SYSTEM Profile；H3C `action_count=0`；`playbook_versions` 表不存在 |
| P0 focused tests：`pytest backend/tests/platform_registry/test_platform_registry.py backend/tests/vendor_audit/test_platform_parser_boundary.py backend/tests/vendor_audit/test_lldp_collection_contract.py -q` | **失败：2 failed, 10 passed**；P0 测试依赖的 `isolated_db` 夹具返回 `None`。当前提交未包含与测试契约匹配的夹具，干净检出也无法复现实施记录中的 12 passed |
| 厂商回归：`pytest backend/tests/vendor_audit -q` | **失败：12 failed, 267 passed**；其中 5 项为动作目录接管后的直接回归：H3C 命令为空 3 项、Cisco LLDP 命令变化 1 项、Huawei VRP5 命令兼容性变化 1 项；另 7 项为现有 `isolated_db` 夹具问题 |
| 完整后端：`pytest backend/tests -q --maxfail=20` | **失败：20 failed, 280 passed, 25 subtests passed**，达到 `maxfail=20` 后停止；除共享数据库/既有夹具问题外，包含上述 P0 厂商回归和 P0 测试失败 |
| `npm run lint` | 通过 |
| `npm run build` | 通过；仅有 chunk size warning |
| PostgreSQL fresh schema / 前版本升级迁移 | 本次未独立验证，不能标记通过 |
| 浏览器端平台创建、模板测试、审核发布、设备绑定、Playbook 编辑 | 对应页面尚未交付，本次未验证 |

### 0.5 继续实施前的准入条件

- 修复 H3C `hp_comware` 动作种子并补充 Cisco、Huawei、H3C 映射回归，保证旧命令兼容性。
- 所有生产消费者统一调用 `execute_platform_action()`，不再只取命令后自行执行。
- 增加功能开关并默认关闭租户写入；拆分平台作者、审核者、发布者和执行者权限。
- 完成 TextFSM Sandbox、字段契约、模板归属/发布状态校验、模板版本/checksum 追溯和缓存失效。
- 补齐 Playbook 版本模型、关键外键、并发锁、原始回显安全和审计闭环。
- 提交可复现的隔离数据库测试夹具，重新通过 P0 focused tests、厂商回归、完整后端测试、PostgreSQL fresh/upgrade、lint 和 build 后，方可将 P0 状态改为完成。

### 0.6 2026-08-03 继续执行进展

- 已修复 `PLATFORM_ACTION_COMMANDS` 的 H3C 解析边界：使用 `hp_comware` 作为 Parser 键，并恢复 Cisco LLDP、Huawei VRP5 聚合命令和 H3C BGP 兼容命令。
- 新增 `m0073_repair_platform_registry_command_seeds` 幂等迁移，修复已应用 m0072 的 SYSTEM Release，并重新绑定可匹配的 SYSTEM Parser 版本；部署启动后才会作用于现有数据库。
- 新增平台注册表专用隔离 SQLite 测试夹具，补充 H3C/Cisco/Huawei 动作解析、跨 Profile 模板拒绝、租户设备作用域拒绝和 API 开关测试。
- 增加 `PLATFORM_REGISTRY_ENABLED=0` 默认关闭开关；平台注册表写入、Release 流转、回滚和新动作执行 API 默认关闭；审核、发布和回滚 API 收紧为 Administrator。
- Discovery 和标准运营采集类别开始通过 `execute_platform_action()` 执行，并携带 Release、命令和 Parser 版本追溯信息；拓扑 LLDP、巡检中与已发布动作精确匹配的命令、IP 定位本地接口查询已切到 Resolver，未纳入首批标准动作的参数化旧类别暂保留兼容路径。
- 执行动作增加租户/Site/设备组作用域校验、Parser 版本归属/状态/平台校验和审计追溯；公开动作 API 默认不返回原始回显，Playbook 数据库结果和 WebSocket 事件也统一脱敏。
- 增加 Release/动作解析的进程内缓存和发布/回滚后的精确失效；增加动作参数占位符的严格 Token 校验，并提供动作预览 API。
- TextFSM 绑定模板解析已移至独立短生命周期子进程，增加模板/回显/记录/字段限制、动作超时和 Windows 进程树终止；显式 field contract 增加必填字段与基础类型校验。
- 新增 `m0074_playbook_version_snapshots`、`m0076_playbook_version_lifecycle`，并在执行入口创建不可变 `SNAPSHOT`、写入 `playbook_executions.playbook_version_id` 和 checksum；新增 `m0075_custom_scenario_tenant_scope`，自定义场景按租户过滤。Playbook 已支持受控 `action_code`、参数、Dry Run 预览和动作追溯；平台注册开关开启时拒绝旧的原始命令步骤，开关默认仍为关闭。
- 新增 Playbook 版本服务和 API：草稿创建、校验、提交、审核、发布、回滚、租户隔离、作者禁止自审；执行入口支持指定已发布版本，并保留执行时 SNAPSHOT。
- 本轮验证：平台注册表 + Parser/LLDP + Playbook 版本 focused tests **32 passed**（其中平台注册专用 **24 passed**），`npm run lint`、Python 编译/模块导入检查和 `git diff --check` 通过；此前 `npm run build` 已通过，仅有 chunk size warning。
- 仍未达到 P0 完成条件：默认 SYSTEM 动作的完整 Normalizer/字段契约覆盖尚不齐全；诊断参数化路由、Operational Data 未纳入标准动作的类别、Playbook 内置旧场景和其他直接 Netmiko/SSH 消费者尚未全量迁移；原始回显目前完成集中脱敏但未完成加密、保留期、读取/下载审计；资源级权限词汇尚未拆成完整推荐角色；PostgreSQL fresh/upgrade 和共享库 m0073 应用后的厂商回归仍待验证。全量 `pytest backend/tests -q --maxfail=20` 本次仍在 collection 阶段被共享 PostgreSQL 的既有 `uq_devices_asset_id` 冲突阻断（`asset-845fd98f78a0`）；此前共享 PostgreSQL 厂商回归为 **5 failed, 267 passed, 7 errors**，失败原因仍需在隔离/升级库中复核。

## 0.7 2026-08-03 P0 继续执行结果（PostgreSQL 验收更新）

**结论：P0 质量门禁已通过，但 P0 功能清单仍未全部完成，暂不开放租户自定义平台生产写入。** 数据库和测试验收统一以 PostgreSQL 为准；本轮后端共享隔离夹具、平台注册专项和 vendor audit 均已切换到真实 PostgreSQL，不再以 SQLite 作为验收依据。

- 数据库迁移：当前开发 PostgreSQL 已从版本 72 升级到 **84**，新增设备组范围字段、Cisco BGP 命令契约修复；在当前库和全新临时 PostgreSQL 上二次执行迁移均为 `0`。
- 全新 PostgreSQL 初始化：**26** 个 Action Definition、**11** 个 SYSTEM Profile、**11** 个 PUBLISHED Release、**204** 个 Release Action 映射；Playbook 历史明文输出 `results_json/phases_json` 均为 **0**；`device_group_id` 列和索引存在；`fk_devices_platform_profile`、`fk_platform_profiles_current_release`、`ck_platform_releases_status` 均存在；临时数据库已删除。
- 权限和执行边界：Playbook 入队前增加设备租户、Site、设备组范围预检；平台注册动作执行继续校验 Command 资源范围；绑定设备的标准采集、诊断、巡检、拓扑、IP 定位、路由/BGP、配置备份和 Playbook 不再回退到厂商直连，未映射能力返回 `UNSUPPORTED_ACTION`。
- 命令契约：Cisco `get_bgp_neighbors` 统一为 `show ip bgp summary`，VRF 变体统一为 `show ip bgp vrf {{vrf}} summary`；新增幂等迁移修复现有 SYSTEM Release；PG 初始化阶段也修复了重复物理资产关联导致的 `uq_devices_asset_id` 启动失败。
- 测试和构建：平台注册表专项 **35 passed**；vendor audit **281 passed**；WAN/定位/诊断专项 **33 passed**；Cisco/H3C 快速查询审计 **90 passed**；完整 `pytest backend/tests -q` **445 passed、25 subtests passed**；Python 编译、`git diff --check`、`npm run lint`、`npm run build` 均通过，前端构建仅保留既有 chunk size warning。
- 本轮修复：共享后端测试改为每会话临时 PostgreSQL 数据库、每测试事务回滚；修复 PostgreSQL 分区采样表验收契约、JSONB `datetime` 审计序列化、VLAN 未分配站点写入 `NULL` 的外键兼容，以及凭据测试与生产 schema 漂移；新增只读迁移预览/冲突报告 API，不改变旧链路。
- 未完成项：功能开关仍默认关闭；平台/模板写入页面和浏览器验收、完整 Site/设备组资源矩阵、设备自动识别/人工绑定 API、全部资源级推荐角色、首批中兴/锐捷/迪普/迈普真实样例适配及剩余字段 Normalizer/契约覆盖仍需继续执行。质量门禁和迁移预览已不再是当前阻断原因。
- 当前开放策略：`PLATFORM_REGISTRY_ENABLED` 默认仍为关闭；在隔离 PostgreSQL 升级回归、剩余消费者/字段契约审计、写入/发布页面和浏览器验收完成前，不开放租户自定义平台的生产写入、审核、发布。

## 1. 目标与非目标

### 1.1 本期目标

- [ ] 将连接驱动、CLI 配置、解析配置拆成独立概念。
- [ ] 建立统一的逻辑动作注册表和运行时解析器。
- [ ] 让拓扑、接口采集、诊断、巡检、Playbook、自动化快速查询共用同一套平台动作解析。
- [ ] 支持平台、命令映射、TextFSM 模板的草稿、测试、审核、原子发布和回滚。
- [ ] 支持用户复制系统平台后进行租户级适配。
- [ ] 支持真实回显样例、字段契约和历史样例回归测试。
- [ ] 支持受控的 Playbook 编辑、测试、提交审核和发布。
- [ ] 保证运行任务只能读取已发布的平台版本。
- [ ] 保证所有运行记录可追溯到平台版本、命令版本和模板校验和。

### 1.2 明确不开放的能力

- [ ] 不允许用户上传或注册任意 Netmiko Python 驱动。
- [ ] 不允许 Playbook 执行任意 Python、Shell、PowerShell 或服务器命令。
- [ ] 不允许用户指定服务器文件路径或模板落盘路径。
- [ ] 不允许模板开发者直接发布生产版本。
- [ ] 不允许跨租户查看平台、测试回显、失败回显或执行记录。
- [ ] 不允许未发布版本进入拓扑、采集、诊断和 Playbook 运行链路。
- [ ] 第一阶段不开放配置模式命令和批量配置变更。

## 2. 目标架构

### 2.1 平台模型

```text
设备
└── platform_profile_id
    └── 当前已发布 Platform Release
        ├── connection_driver
        ├── cli_profile
        ├── parser_profile
        ├── identification_rules
        ├── action_mappings
        ├── parser_template_versions
        └── safety_policy
```

- [ ] 设备只绑定平台 Profile，不分别维护容易漂移的驱动、CLI 和 Parser 字段。
- [ ] 运行任务解析平台时获取一个不可变的 Platform Release。
- [ ] 发布平台时将命令映射、模板版本、字段契约和识别规则作为一个整体提交。
- [ ] 回滚通过切换当前 Release 指针完成，不修改历史版本。
- [ ] 运行记录持久化 `platform_release_id`、`action_code`、模板版本和 checksum。

### 2.2 三层职责

| 层级 | 用途 | 是否允许普通用户自定义 |
| --- | --- | --- |
| Connection Driver | SSH 登录、提示符、分页、配置模式和传输能力 | 否，只能从系统白名单选择 |
| CLI Profile | 逻辑动作到真实命令的映射 | 是，受命令安全策略限制 |
| Parser Profile | 逻辑动作到 TextFSM 模板和字段契约的映射 | 是，必须经过测试与审核 |

- [ ] 明确 `connection_driver` 使用 Netmiko/内部驱动标识。
- [ ] 明确 `platform_code` 是 Nexora 平台 Profile，不直接作为 Netmiko `device_type`。
- [ ] 明确 H3C 连接/业务平台与解析平台边界：连接按系统映射，TextFSM 统一使用 `hp_comware`。

## 3. P0：基础平台与统一动作解析器

> 这是所有后续页面和权限开放的前置条件。未完成本阶段前，不开放用户自定义平台。

### 3.1 标准逻辑动作注册表

- [ ] 新建统一的 Action Definition 注册表。
- [ ] 为每个动作定义稳定的 `action_code`。
- [ ] 定义动作中文名、英文名、用途和风险等级。
- [ ] 定义动作允许使用的设备类型。
- [ ] 定义动作必需字段、可选字段和字段类型。
- [ ] 定义动作最大回显大小、最大记录数、超时和敏感级别。
- [ ] 定义动作允许的业务消费者。
- [ ] 缺少动作映射时返回 `UNSUPPORTED_ACTION`，禁止静默回退到 Cisco 命令。

首批标准动作：

- [ ] `get_version`
- [ ] `get_lldp_neighbors`
- [ ] `get_interface_brief`
- [ ] `get_interfaces`
- [ ] `get_ip_interfaces`
- [ ] `get_link_aggregation`
- [ ] `get_arp_table`
- [ ] `get_mac_table`
- [ ] `get_vlan_table`
- [ ] `get_route_table`
- [ ] `get_bgp_neighbors`
- [ ] `get_ospf_neighbors`
- [ ] `get_transceivers`
- [ ] `get_cpu`
- [ ] `get_memory`
- [ ] `get_fans`
- [ ] `get_power`
- [ ] `get_temperature`
- [ ] `get_clock`
- [ ] `get_running_config`

### 3.2 Platform Action Resolver

- [ ] 新建唯一运行入口 `execute_platform_action()`。
- [ ] 根据设备绑定关系获取当前已发布 Platform Release。
- [ ] 从 Release 解析连接驱动、实际命令、模板版本和字段契约。
- [ ] 执行命令前验证动作风险、调用者权限和设备作用域。
- [ ] 执行命令后调用统一 TextFSM Sandbox。
- [ ] 通过标准 Normalizer 输出业务字段。
- [ ] 返回结构化错误码，区分连接失败、命令不支持、模板不匹配和字段契约失败。
- [ ] 对 Release 和模板 checksum 做只读缓存。
- [ ] Platform Release 变更后精确失效对应缓存。

### 3.3 现有调用链迁移

- [ ] 拓扑发现改用 `get_lldp_neighbors`、`get_interfaces` 和 `get_link_aggregation`。
- [ ] CMDB 接口采集改用标准接口动作。
- [ ] VLAN、ARP、MAC 和路由采集改用标准动作。
- [ ] 设备诊断改用标准动作。
- [ ] 巡检服务改用标准动作。
- [ ] IP 定位服务改用标准 ARP/MAC 动作。
- [ ] Playbook 内置场景改用 `action_code`。
- [ ] 自动化快速查询从后端平台动作目录获取默认命令。
- [ ] 前端移除中兴、锐捷、迪普、迈普命令分支硬编码。
- [ ] 配置备份动作与只读采集动作分开授权。
- [ ] 所有消费者迁移完成后，删除重复的厂商命令目录。

### 3.4 系统平台种子

- [ ] 将现有 Cisco、Huawei、H3C、Juniper、Arista 等映射注册为 SYSTEM 平台。
- [ ] 注册 `zte_5900_v6`，连接驱动 `zte_zxros`。
- [ ] 注册 `zte_zsrv2_v3`，连接驱动 `zte_zxros`。
- [ ] 注册 `ruijie_s6k_rgos12`，连接驱动 `ruijie_os`。
- [ ] 注册 `ruijie_eg_rgos11`，连接驱动 `ruijie_os`。
- [ ] 注册 `dptech_fw_s211`，连接驱动 `dptech_ios`。
- [ ] 注册 `maipu_s3330_v9`，连接驱动 `maipu`。
- [ ] 为每个平台录入表格中已确认的 `show version` 样例。
- [ ] 未提供真实回显的动作标记为“未适配”，不创建猜测模板。

## 4. P0：数据库与迁移

### 4.1 表结构

- [ ] 新增 `platform_profiles`。
- [ ] 新增 `platform_releases`。
- [ ] 新增 `action_definitions`。
- [ ] 新增 `platform_release_actions`。
- [ ] 新增 `parser_templates`。
- [ ] 新增 `parser_template_versions`。
- [ ] 新增 `parser_test_samples`。
- [ ] 新增 `platform_identification_rules`。
- [ ] 新增 `platform_release_audit_logs`。
- [ ] 新增 `playbook_versions` 或补齐现有 Playbook 版本模型。
- [ ] 新增 `playbook_release_audit_logs`。

### 4.2 约束与索引

- [ ] 所有租户字段沿用 Nexora 当前 TEXT ID 规范。
- [ ] 添加必要外键和明确的 `ON DELETE` 行为。
- [ ] 添加平台编码格式检查 `^[a-z][a-z0-9_]{2,63}$`。
- [ ] 添加模板字段名格式检查 `^[A-Z][A-Z0-9_]{0,63}$`。
- [ ] 全局系统平台和租户平台使用不同唯一索引，避免 PostgreSQL NULL 唯一性漏洞。
- [ ] 同一模板的版本号唯一。
- [ ] 同一平台 Release 的 `action_code` 唯一。
- [ ] 同一 Profile 同时只能有一个当前发布 Release。
- [ ] 发布状态转换使用事务和行锁。
- [ ] 增加乐观锁版本，防止多人编辑覆盖。
- [ ] 禁止创建者审核自己的提交。

### 4.3 兼容迁移

- [ ] 为 `devices` 增加 `platform_profile_id`、`platform_source`、`platform_locked`。
- [ ] 根据现有 `devices.platform` 回填 SYSTEM Profile。
- [ ] 保留现有 `platform` 字段作为兼容读取字段，完成迁移后再评估废弃。
- [ ] 将 `data/textfsm_templates` 中已存在的自定义文件导入版本表。
- [ ] 导入前计算 checksum，并检测重名、非法平台和重复命令。
- [ ] 系统内置模板保留在代码包中，通过只读 Manifest 注册。
- [ ] CUSTOM 模板运行时按 ID/版本解析，不再按同名文件静默覆盖 SYSTEM 模板。
- [ ] 提供迁移预览和冲突报告。
- [ ] 迁移失败不得影响旧版运行链路。
- [ ] 增加可回退的兼容开关。

## 5. P0：权限、安全和审计

### 5.1 权限项

- [ ] `platform.view`
- [ ] `platform.create`
- [ ] `platform.edit_draft`
- [ ] `platform.submit`
- [ ] `platform.approve`
- [ ] `platform.publish`
- [ ] `platform.rollback`
- [ ] `platform.bind_device`
- [ ] `command.view`
- [ ] `command.edit_draft`
- [ ] `command.test`
- [ ] `textfsm.view`
- [ ] `textfsm.create`
- [ ] `textfsm.edit_draft`
- [ ] `textfsm.test`
- [ ] `textfsm.submit`
- [ ] `textfsm.approve`
- [ ] `textfsm.publish`
- [ ] `textfsm.rollback`
- [ ] `sample_output.upload`
- [ ] `sample_output.view`
- [ ] `sample_output.delete`
- [ ] `playbook.view`
- [ ] `playbook.create`
- [ ] `playbook.edit_draft`
- [ ] `playbook.test`
- [ ] `playbook.submit`
- [ ] `playbook.approve`
- [ ] `playbook.publish`
- [ ] `playbook.execute`
- [ ] `playbook.schedule`
- [ ] `playbook.rollback`

### 5.2 推荐角色

- [ ] 平台查看者：只读平台、命令、模板和发布记录。
- [ ] 模板开发者：维护草稿、上传样例、执行测试、提交审核。
- [ ] 平台维护者：创建 Profile、维护命令映射和识别规则。
- [ ] Playbook 作者：在批准动作范围内编排草稿和测试。
- [ ] 审核发布者：审核、发布和回滚平台、模板与 Playbook。
- [ ] 自动化操作员：执行已发布 Playbook，无编辑和发布权限。
- [ ] 调度管理员：创建或修改已发布 Playbook 的调度计划。
- [ ] 系统管理员：维护驱动白名单、系统平台、安全限制和全局模板。

### 5.3 命令安全

- [ ] 第一阶段只允许只读动作。
- [ ] 按连接驱动定义允许的查询命令前缀，如 `show`、`display`。
- [ ] 禁止命令换行、多命令拼接和进入配置模式。
- [ ] 禁止普通作者绕过逻辑动作直接下发配置命令。
- [ ] `get_running_config`标记为敏感动作并单独授权。
- [ ] 命令预览必须显示实际命令、目标设备和平台版本。
- [ ] 记录命令创建、修改、测试、审核、发布和执行审计。

### 5.4 原始回显安全

- [ ] 按动作配置回显保留期，不使用全局固定值覆盖所有场景。
- [ ] 解析失败回显可配置更长保留期。
- [ ] 入库前脱敏密码、Community、密钥和认证信息。
- [ ] 敏感原始回显加密存储。
- [ ] 原始回显读取受租户、角色、Site 和设备作用域限制。
- [ ] 查看和下载原始回显写入审计日志。
- [ ] 运行配置不得自动转为普通模板开发者可见的测试样例。

## 6. P1：TextFSM 开发、测试与发布

### 6.1 在线编辑器

- [ ] 使用代码编辑器组件展示语法高亮和行号。
- [ ] 左侧编辑模板，右侧编辑或选择测试回显，下方展示结构化结果。
- [ ] 显示模板语法状态、解析耗时、记录数和字段列表。
- [ ] 显示字段完整率和字段契约差异。
- [ ] 显示旧版本和新版本模板 Diff。
- [ ] 显示旧版本和新版本解析结果 Diff。
- [ ] 支持从 SYSTEM 模板创建 FORKED 模板。
- [ ] 平台编码、模板编码创建后不可原地修改。

### 6.2 四级校验

- [ ] TextFSM 基础语法检查。
- [ ] 正则表达式编译检查。
- [ ] Value、Start、状态跳转和变量引用检查。
- [ ] 独立进程解析运行检查。
- [ ] 解析超时检查。
- [ ] 最大回显大小检查。
- [ ] 最大记录数和字段数检查。
- [ ] 动作字段契约检查。
- [ ] 字段类型、空值和标准化检查。
- [ ] 历史样例回归检查。
- [ ] 回归失败时阻止发布，审核豁免必须填写原因。

### 6.3 Sandbox

- [ ] TextFSM 不在 FastAPI 主请求进程中无限制执行。
- [ ] 使用独立子进程或专用 Worker。
- [ ] Windows 使用可终止整个进程树的超时机制。
- [ ] 评估 Windows Job Object 内存限制。
- [ ] 限制模板大小、回显大小、状态数、字段数、字段长度和记录数。
- [ ] 超时后确保 Worker 被销毁，不复用异常进程。
- [ ] 禁止模板访问文件路径和网络资源。

### 6.4 发布流程

- [ ] 状态采用 `DRAFT → IN_REVIEW → PUBLISHED → DEPRECATED`。
- [ ] 测试结果作为版本属性，不单独作为持久生命周期。
- [ ] 回滚记录为审计事件，并将当前 Release 指向历史已发布版本。
- [ ] 发布后版本不可原地修改。
- [ ] 修改已发布模板自动创建新草稿版本。
- [ ] 发布页面展示影响平台、设备、采集任务和 Playbook 数量。

## 7. P1：平台识别与设备绑定

### 7.1 声明式识别规则

- [ ] 识别命令由基础连接驱动提供，不依赖尚未识别的平台命令。
- [ ] 支持 `contains`、`starts_with`、`ends_with`、`equals`、受控 `regex`。
- [ ] 支持 ALL/ANY 条件组合。
- [ ] 支持规则优先级、置信度和否定条件。
- [ ] 规则只能绑定到同租户且兼容连接驱动的平台。
- [ ] 多条规则同分时不自动绑定，返回“识别冲突”。
- [ ] 自动识别前运行对应测试样例。

### 7.2 首批识别关键字

- [ ] 中兴 5960：`ZXR10 5960`、`5900 V6.`、`5960X_`。
- [ ] 中兴 1800-2S：`ZXR10 1800-2S`、`ZSRV2 V3.`。
- [ ] 锐捷 S6231：`S6231-48XS8CQ`、`S6K-A_RGOS 12.`。
- [ ] 锐捷 EG3000UE：`EG3000UE`、`EG_RGOS 11.`。
- [ ] 迪普 FW1000：`FW1000-TS-C`、`Software Release S211`。
- [ ] 迈普 S3330：`MyPower S3330`、`Software Version 9.7.`。

### 7.3 绑定方式

- [ ] 自动识别并建议绑定。
- [ ] 用户人工指定平台。
- [ ] 用户人工锁定平台。
- [ ] 人工锁定后自动识别只能提示差异，不能覆盖。
- [ ] 批量绑定必须展示设备数量、旧平台和新平台。
- [ ] 平台变更后触发兼容性验证，不自动执行高风险任务。

## 8. P1：受控 Playbook 编辑

### 8.1 编辑范围

- [ ] 用户可以查看和复制 SYSTEM Playbook。
- [ ] 用户可以编辑自己创建或有权限的草稿。
- [ ] 步骤只能引用已发布的 `action_code`。
- [ ] 支持参数、条件、分支、顺序、审批点和通知步骤。
- [ ] 禁止普通作者输入任意 Python、Shell 或服务器脚本。
- [ ] 原始命令步骤默认禁用；如保留，只允许单条只读命令并单独授权。
- [ ] 凭据只保存引用 ID，不进入 Playbook 内容和 Diff。

### 8.2 版本和发布

- [ ] Playbook 发布版本不可修改。
- [ ] 修改已发布版本时自动创建新草稿。
- [ ] 发布记录固定步骤定义及引用的平台 Release 范围。
- [ ] 执行记录固定实际使用的平台 Release、命令和模板版本。
- [ ] 作者不能审核自己提交的 Playbook。
- [ ] 发布、执行和调度权限相互独立。

### 8.3 测试与执行保护

- [ ] 支持不连接设备的结构预检。
- [ ] 支持指定实验设备执行测试。
- [ ] 支持 Dry Run，展示将执行的逻辑动作和实际命令。
- [ ] 限制最大步骤数、循环次数、并发数和总执行时长。
- [ ] 支持租户、Site、设备组和设备级作用域。
- [ ] 批量执行支持分批、灰度和失败阈值停止。
- [ ] 配置类动作后续开放时必须增加配置备份、Diff、维护窗口和二次审批。

## 9. P1：前端页面

- [ ] 新增“自动化平台管理”入口。
- [ ] 平台列表支持来源、状态、厂商、驱动、绑定设备数和健康度筛选。
- [ ] 平台详情按“基本信息、命令映射、解析模板、识别规则、测试样例、发布记录”分栏。
- [ ] 创建平台使用分步向导。
- [ ] 连接驱动使用系统白名单下拉框，不允许自由输入。
- [ ] 命令映射页面展示动作风险和字段契约。
- [ ] TextFSM 编辑器支持 Diff、测试和结果预览。
- [ ] 审核页面展示受影响设备、业务消费者和字段变化。
- [ ] 设备详情支持自动识别、人工指定和人工锁定。
- [ ] Playbook 编辑器只展示用户有权使用的步骤类型和动作。
- [ ] 所有页面处理加载、空数据、权限不足、冲突和后端失败状态。
- [ ] 补齐中英文文案。

## 10. P2：生产失败闭环与健康度

- [x] 保存结构化解析失败原因。
- [x] 失败回显可一键转为脱敏测试样例。
- [x] 新版本发布前自动运行全部历史回归样例。
- [x] 平台显示命令覆盖率。
- [x] 平台显示模板覆盖率。
- [x] 平台显示样例通过率。
- [x] 平台显示最近解析失败数量。
- [x] 平台显示绑定设备数量。
- [x] 平台显示受影响 Playbook 数量。
- [ ] 增加未知输出和识别冲突待办列表。
- [x] 增加解析性能和超时趋势。

## 11. API 清单

建议使用独立前缀，避免与现有 `/api/textfsm/templates` 直接冲突：

- [ ] `GET /api/platform-registry/profiles`
- [ ] `POST /api/platform-registry/profiles`
- [ ] `GET /api/platform-registry/profiles/{id}`
- [ ] `POST /api/platform-registry/profiles/{id}/releases`
- [ ] `POST /api/platform-registry/releases/{id}/validate`
- [ ] `POST /api/platform-registry/releases/{id}/submit`
- [ ] `POST /api/platform-registry/releases/{id}/approve`
- [ ] `POST /api/platform-registry/releases/{id}/publish`
- [ ] `POST /api/platform-registry/profiles/{id}/rollback`
- [ ] `GET /api/platform-registry/profiles/{id}/actions`
- [ ] `PUT /api/platform-registry/releases/{id}/actions/{action_code}`
- [ ] `GET /api/parser-templates`
- [ ] `POST /api/parser-templates`
- [ ] `POST /api/parser-templates/{id}/versions`
- [ ] `POST /api/parser-template-versions/{id}/test`
- [ ] `POST /api/parser-templates/{id}/samples`
- [ ] `POST /api/parser-templates/{id}/regression-test`
- [ ] `POST /api/devices/{id}/platform-detect`
- [ ] `PUT /api/devices/{id}/platform-binding`
- [x] `POST /api/playbooks/{id}/versions`
- [x] `POST /api/playbook-versions/{id}/validate`
- [x] `POST /api/playbook-versions/{id}/submit`
- [x] `POST /api/playbook-versions/{id}/approve`
- [x] `POST /api/playbook-versions/{id}/publish`
- [x] `POST /api/playbooks/{id}/rollback`

## 12. 测试与质量门禁

### 12.1 单元测试

- [ ] 平台编码和模板编码校验。
- [ ] Action Resolver 成功和不支持动作。
- [ ] 平台 Release 原子发布和回滚。
- [ ] 作者不能自审。
- [ ] 租户隔离和 Site/设备作用域。
- [ ] 命令安全校验。
- [ ] TextFSM 编译、超时、超限和字段契约失败。
- [ ] Platform Release 缓存和失效。
- [ ] 人工锁定不被自动识别覆盖。
- [ ] 识别规则冲突。
- [ ] Playbook 步骤白名单和权限拒绝。

### 12.2 厂商回归

- [ ] Cisco 平台动作回归。
- [ ] Huawei VRP 平台动作回归。
- [ ] H3C 连接平台到 `hp_comware` Parser 边界回归。
- [ ] 中兴 5960 V6 样例回归。
- [ ] 中兴 1800-2S ZSRV2 V3 样例回归。
- [ ] 锐捷 S6K RGOS 12 样例回归。
- [ ] 锐捷 EG RGOS 11 样例回归。
- [ ] 迪普 FW1000 样例回归。
- [ ] 迈普 S3330 样例回归。
- [ ] 厂商切换后旧平台不残留。
- [ ] 不同接口缩写通过共享 Canonicalizer 合并。

### 12.3 集成测试

- [ ] 新建平台草稿到发布完整流程。
- [ ] SYSTEM 模板复制为 FORKED 模板。
- [ ] 新模板发布后拓扑使用新版本。
- [ ] 新模板发布后接口采集使用新版本。
- [ ] Playbook 使用已发布逻辑动作。
- [ ] 草稿版本无法被生产任务读取。
- [ ] 回滚后新任务使用历史已发布版本。
- [ ] 历史任务仍可定位原模板 checksum。
- [ ] 旧数据迁移和兼容读取。

### 12.4 交付门禁

- [ ] 运行相关后端 focused tests。
- [ ] 运行完整 `pytest backend/tests`。
- [ ] 运行 `npm run lint`。
- [ ] 运行 `npm run build`。
- [ ] 验证 PostgreSQL fresh schema。
- [ ] 验证从前一版本升级迁移。
- [ ] 检查日志中无密码、Community、密钥和原始敏感配置。
- [ ] 浏览器验证平台创建、模板测试、审核发布、设备绑定和 Playbook 编辑。

## 13. 上线策略

- [ ] 增加功能开关 `PLATFORM_REGISTRY_ENABLED`。
- [ ] 第一阶段只注册现有 SYSTEM 平台，不开放用户写入。
- [ ] 第二阶段开放模板开发者草稿和测试。
- [ ] 第三阶段开放审核发布，并选择少量实验设备。
- [ ] 第四阶段迁移拓扑和接口采集。
- [ ] 第五阶段迁移 Playbook、诊断、巡检和快速查询。
- [ ] 对比新旧解析结果、记录数和失败率。
- [ ] 全部消费者迁移完成后关闭旧文件名自动覆盖机制。
- [ ] 保留一个版本周期的兼容回退能力。

## 14. Definition of Done

### 14.8 2026-08-03 前端平台注册表只读阶段

- 新增 `/management/platforms`“Platform Registry”入口，面向 Viewer 及以上角色开放只读查看；不暴露创建、编辑、审批、发布、回滚和执行按钮，符合当前 `PLATFORM_REGISTRY_ENABLED` 默认关闭的灰度策略。
- 新增平台注册表列表和详情视图：支持按来源、状态、厂商、注册表就绪度和关键词筛选；详情分为基本信息、命令映射、Release 记录，并显示连接驱动、解析平台、当前 Release、checksum、动作风险、字段契约、消费者和绑定设备统计。
- 后端 `GET /api/platform-registry/profiles` 与详情查询补充当前 Release 状态、校验状态、动作数、绑定设备数和在线设备数；设备统计按当前租户隔离，SYSTEM 平台不会跨租户泄露绑定量。
- 本阶段验证：平台注册 focused tests **32 passed**；`npm run lint` 通过；`npm run build` 通过。构建仍有既有的大 chunk 提示，不影响产物生成。
- P0-P2 仍未全部完成：平台注册写入/发布流程和浏览器验收、完整 Site/设备组资源矩阵、设备自动识别/人工绑定 API、TextFSM 注册表深度联动、首批国产厂商真实样例适配、迁移预览/冲突报告及剩余审计/健康指标仍待后续阶段收口；PostgreSQL fresh/upgrade、厂商全量回归和完整后端测试本轮已通过。

### 14.7 2026-08-03 消费者迁移补充

- 周期性接口同步对已绑定平台注册的设备改用 `get_interfaces`、`get_interface_brief`、`get_ip_interfaces` 三个标准动作合并写入接口状态；未绑定旧设备继续走兼容采集路径。
- 新增 Scheduler 消费者回归测试，平台/Playbook focused tests 当前 **31 passed**。
- P0 仍未完成：BGP VRF 等参数化命令、历史明文输出的强制处理、完整资源角色矩阵、PostgreSQL fresh/upgrade 和厂商全量回归仍待处理。

### 14.6 2026-08-03 继续执行补充记录

- 新增 `m0078_playbook_output_security`：Playbook 执行结果和设备阶段输出使用加密字段保存，旧兼容字段不再承载新明文；密钥不可用时新原始输出直接丢弃，不影响状态和计数持久化。
- 增加 `PLAYBOOK_RAW_OUTPUT_RETENTION_DAYS`（默认 30 天）和每日清理任务；详情、完整结果和解析接口读取加密数据，失败时返回 `PLAYBOOK_OUTPUT_UNAVAILABLE`，不泄露密文。
- 本轮质量门禁：`pytest backend/tests/platform_registry -q` 为 **30 passed**；平台/Playbook 加诊断证据组合为 **35 passed**；Python 编译、`npm run lint`、`git diff --check` 通过。
- 全量 `pytest backend/tests -q --maxfail=20` 仍在 collection 阶段被既有共享 PostgreSQL 的 `uq_devices_asset_id` 冲突阻断（`asset-845fd98f78a0`），未发现本轮改动导致的新增 collection 错误。
- P0-P2 仍未全部完成：历史明文输出在未配置加密密钥时仍保留兼容读取，全部消费者迁移、Site/设备组资源矩阵、PostgreSQL fresh/upgrade、厂商全量回归、前端管理页面和浏览器验收仍待收口。

### 14.5 2026-08-03 继续执行补充审查

- 本轮新增 `m0077_playbook_execution_tenant_scope`：Playbook 执行记录持久化 `tenant_id`，列表、详情、设备结果、解析、WebSocket 和确认提交均先做租户/资源作用域校验；无租户归属的历史记录对非 Administrator 默认不可见。
- Playbook 完整记录、完整执行结果和设备原始阶段输出读取均记录 `PLAYBOOK_OUTPUT_READ` 审计事件；平台动作返回继续默认不带原始输出。
- 平台 Resolver 现在真正使用 Action Definition 的必需字段进行校验，增加跨厂商字段别名归一化和声明类型的标量转换；IP Locator 与诊断对已绑定平台注册的设备改走标准 `get_arp_table`、`get_mac_table`、`get_route_table` 动作，未绑定旧设备保留兼容路径。
- 本轮验证：平台注册/Playbook focused tests **27 passed**；与 IP Locator/诊断证据测试组合执行 **46 passed，1 项在共享 PostgreSQL fixture 初始化阶段因既有 `uq_devices_asset_id` 冲突失败**；Python 编译、`npm run lint` 通过。
- P0-P2 仍未全部完成。尚未收口的高风险项包括：全部消费者迁移、原始输出加密/保留期/下载审计、完整 Site/设备组资源角色矩阵、PostgreSQL fresh/upgrade 与厂商全量回归、前端管理页面和浏览器集成验收；因此当前仍不能标记 P0 完成或开放租户写入。

- [ ] 用户可创建租户级平台草稿，但不能注册自定义驱动。
- [ ] 用户可配置标准逻辑动作的实际查询命令。
- [ ] 用户可编写 TextFSM、上传真实回显并查看结构化结果。
- [ ] 模板通过字段契约和历史回归测试后才能提交审核。
- [ ] 审核者可原子发布完整 Platform Release。
- [ ] 设备可自动识别、人工指定和人工锁定平台。
- [ ] 拓扑、接口采集、诊断、巡检、Playbook 和快速查询共用 Action Resolver。
- [ ] 用户可在已批准动作范围内编辑 Playbook 草稿并提交审核。
- [ ] 生产任务只使用已发布 Release。
- [ ] 任意任务都可追溯平台 Release、动作、实际命令、模板版本和 checksum。
- [ ] 租户隔离、命令安全、原始回显脱敏和审计测试全部通过。
- [ ] 中兴、锐捷、迪普、迈普首批样例适配通过，且 Cisco、Huawei、H3C 无回归。

### 14.9 2026-08-03 P0 收口验收（PostgreSQL）

- P0 运行时安全与质量门禁已收口：已绑定平台注册设备的拓扑、接口、ARP、MAC、路由、BGP、诊断、巡检、Discovery、Playbook 和快速自动化路径统一经过 `execute_platform_action()`；未映射动作返回 `UNSUPPORTED_ACTION`，不会回退到厂商命令或任意命令执行。Connectivity 的 ping/traceroute 在绑定设备上也已 fail-closed。
- TextFSM 在线测试改用独立 Sandbox 子进程，限制模板/回显/记录/字段/超时；Discovery 不再把原始 CLI 回显写入普通观察记录，Inspection 持久化前统一脱敏；Playbook 结果继续使用加密字段、保留期清理和读取审计。
- 权限动作词汇已集中到 `RESOURCE_ACTION_CATALOG`，平台、TextFSM、Playbook 审批/发布/回滚路由改用资源级权限依赖；新增推荐角色 Profile 元数据，Operator 不具备审批、发布和回滚权限。
- 新增迁移 `m0085_system_profile_adaptation_status`：中兴、锐捷、迪普、迈普 SYSTEM Profile 显式标记 `UNVERIFIED/MISSING`，没有真实设备回显时不伪造样例或模板；`PLATFORM_REGISTRY_ENABLED` 仍默认关闭，未开放租户生产写入。
- PostgreSQL 证据：当前开发库 `schema_migrations` 最大版本 **85**；平台注册专项 **37 passed**；`backend/tests/vendor_audit` **281 passed**；完整 `pytest backend/tests -q` **447 passed, 1 warning, 25 subtests passed**；`compileall`、`npm run lint`、`npm run build`、`git diff --check` 均通过。Build 仅保留既有 chunk size warning，测试仅保留 Starlette/httpx deprecation warning。
- P0 判定：**已完成并通过质量门禁**。国产 Profile 的 `UNVERIFIED/MISSING` 是适配资产状态，不是伪造的生产适配；在获得真实 `show version`/动作回显并完成回归前，相关动作仍不应开放到租户生产设备。下一阶段转入 P1，优先建设 TextFSM 注册表开发、样例上传/测试和发布前回归闭环。

### 15.1 2026-08-03 P1 TextFSM 注册表与平台识别首片

- 已新增租户隔离的 TextFSM 注册表开发服务和 API：模板创建、版本草稿、Sandbox 测试、模板列表/版本列表，以及从 SYSTEM 模板创建 FORKED 租户模板；SYSTEM 模板保持不可原地编辑，平台编码和模板编码创建后不提供修改入口。
- 已落地 TextFSM 版本生命周期：`DRAFT → IN_REVIEW → APPROVED → PUBLISHED → DEPRECATED`；提交、审批、发布均有状态前置条件，创建者不能自审，审批/发布由 Administrator 执行，发布前必须有通过的 Sandbox 测试并回归该版本全部历史样例。
- 已新增字段契约校验：required/optional/types 统一规范化，支持 string/integer/number/boolean，测试结果返回字段列表和字段完整率；解析失败、超限和契约失败返回结构化错误码。
- 已新增 `m0086_parser_template_lifecycle_security`：版本提交/审批/发布追溯字段、样例密文和保留期字段；样例无法加密时拒绝保存，历史明文样例迁移时加密或隔离，不向列表 API 返回原始回显或密文。新增 `m0087_device_binding_scope_columns`，确保设备绑定具备 Site、设备组作用域字段。
- 已新增声明式平台识别与人工绑定 API：支持 contains/starts_with/ends_with/equals/受控 regex、ALL/ANY、否定、置信度排序；同分时返回 `IDENTIFICATION_CONFLICT` 不自动绑定；人工绑定校验租户、Site/设备组资源权限，支持人工锁定，锁定后禁止普通用户覆盖。
- 已新增自动识别接口：只调用连接驱动白名单中的 `show/display version`，识别回显仅在内存中参与匹配，接口不返回或持久化原始回显；人工锁定设备仍只返回差异建议，不自动覆盖。
- 前端新增独立 `/automation/textfsm-registry` 注册表开发页，接入草稿保存、Sandbox 测试、样例加密上传、提交、审批和发布按钮；原有旧模板页保留，便于灰度期间兼容查看。
- 新增 TextFSM、平台识别和设备绑定的 Pydantic 请求模型，固定长度、编码、回显大小和字段类型边界；前端类型检查与生产构建通过。
- 当前 PostgreSQL 验证：平台注册专项 **45 passed**；P1 专项覆盖租户隔离、TextFSM Sandbox、字段契约、生命周期、自审阻断、样例加密/无密钥 fail-closed、SYSTEM Fork、识别冲突和绑定锁定。P1 仍未全部完成，在线编辑器、浏览器验收、真实设备识别命令采集、完整 Site/设备组资源矩阵和 Playbook/P2 健康度闭环继续执行。

### 15.2 2026-08-03 P1 识别闭环与回归门禁补充

- 新增 `POST /api/parser-templates/{id}/regression-test`，对指定可变版本执行全部历史加密样例回归；发布前回归逻辑与显式 API 共用同一 Sandbox/字段契约校验。
- 新增设备侧标准接口 `POST /api/devices/{id}/platform-detect` 与 `PUT /api/devices/{id}/platform-binding`，兼容保留平台注册命名空间路由；设备详情增加自动识别、人工指定、人工锁定和候选结果选择控件。
- 新增迁移 `m0088_seed_domestic_platform_identification_rules`：为中兴 5900/1800、锐捷 S6K/EG、迪普 FW1000、迈普 S3330 写入需求清单中的首批识别关键字，规则为 SYSTEM/ANY/contains，不伪造设备回显或生产适配状态。
- PostgreSQL 证据：开发库 `schema_migrations` 最新版本 **88**，首批 6 个国产平台规则均已落库；平台注册专项 **51 passed**，厂商回归 **281 passed**，完整后端 **461 passed，1 warning，25 subtests passed**；`compileall`、`npm run lint`、`npm run build` 和非 dist 差异检查通过。浏览器已登录只读核验 `/automation/textfsm-registry`，页面能加载 SYSTEM 模板和已发布版本；未提交任何写入表单。
- P1 仍未全部完成：代码编辑器语法高亮/行号、模板与解析结果 Diff、真实设备在线识别命令采集、完整 Site/设备组资源角色矩阵、受控 Playbook 编辑、浏览器对写入流程的验收及 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.3 2026-08-03 P1 TextFSM 编辑器 Diff 补充

- TextFSM 注册表页面已补充不新增依赖的代码编辑区：行号栏、滚动同步、基线版本选择、源码增删 Diff 和超大模板的线性降级策略。
- 已补充解析结果 Diff：比较基线版本与当前 Sandbox/版本摘要的记录数、字段新增和字段移除；历史回归按钮仍复用后端加密样例和 Sandbox 校验。
- 本轮门禁：平台注册专项 **51 passed**；完整后端 **461 passed，1 warning，25 subtests passed**；`npm run lint`、`npm run build`、`compileall` 和非 dist 差异检查通过。既有构建 chunk size warning 与 Starlette/httpx deprecation warning 未扩大。
- P1 剩余项：浏览器加载最新构建后的交互验收、真实设备在线识别命令采集、完整 Site/设备组资源角色矩阵、受控 Playbook 编辑及 P2 生产失败/健康度闭环。

### 15.4 2026-08-03 P1 Playbook 受控执行边界补充

- `validate_controlled_phases` 现已拒绝非法阶段结构、原始命令、非法 Action 参数、单个 Action 超过 32 个参数、非法/超过 10 次的重复次数，以及总步骤超过 200 的 Playbook 定义。
- `execute_playbook` 现已校验设备目标必须非空且不重复，最多 200 台；并限制并发为 1-20、变量最多 64 个、`dry_run` 必须为布尔值、`commit_confirmed_ttl` 必须在 0-3600 秒范围内。
- 版本校验和执行入口保留具体结构化错误码，不再把所有边界错误折叠为 `RAW_COMMAND_DISABLED`，便于审计和前端提示。
- PostgreSQL/质量门禁证据：平台注册专项 **53 passed**；完整后端 **463 passed，1 warning，25 subtests passed**；`compileall`、`npm run lint`、`npm run build` 和非 dist 差异检查通过。构建仅保留既有 chunk size warning，测试仅保留既有 Starlette/httpx deprecation warning。
- P1 仍未全部完成：条件/分支/通知步骤类型、版本编辑器 UI、最新构建的浏览器交互验收、完整 Site/设备组资源矩阵、真实设备在线识别、受控 Playbook 编辑和 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.5 2026-08-03 P1 Playbook 重复与分支语义补充

- 修正受控 Action 的 `repeat` 执行语义：校验通过的 1-10 次重复现在会按定义实际展开执行，并计入总步骤上限，不能通过重复配置绕过 200 步限制。
- 增加受控 `branch` 步骤：条件仅允许 `variables` 或安全设备字段，操作符限定为 equals/not_equals/contains/starts_with/ends_with/in/not_in/exists/not_exists，控制流深度最多 4 层；执行前确定性选择 `then` 或 `else` 分支。
- 未实现的 `notification`、审批或其他步骤类型继续返回 `UNSUPPORTED_STEP_TYPE`，不会被执行引擎静默跳过；通知/审批步骤仍是后续 P1 工作项。
- PostgreSQL 证据：平台注册专项 **58 passed**；完整后端 **468 passed，1 warning，25 subtests passed**；Playbook 专项 **17 passed**；前一轮 `npm run lint`、`npm run build` 已通过，本轮后端导入执行和非 dist 差异检查继续通过。
- P1 仍未全部完成：通知/审批步骤、版本编辑器 UI、最新构建的浏览器交互验收、完整 Site/设备组资源矩阵、真实设备在线识别、受控 Playbook 编辑闭环和 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.6 2026-08-03 P1 Playbook 通知步骤补充

- 新增受控 `notification` 步骤：只允许标题、消息和级别，禁止在 Playbook 定义中写入 webhook、渠道、密码、Token 或其他凭据；文本长度和级别均有边界校验。
- 通知执行只通过系统已配置渠道分发，并按执行租户过滤 active 用户；缺少租户、注册开关关闭、渠道失败和 Dry Run 均有结构化结果，不会泄露渠道地址或消息正文到执行回显。
- 通知处理写入 `PLAYBOOK_NOTIFICATION` 审计事件；通知失败会将任务标记为部分失败，但不会因通知故障触发设备配置回滚。
- PostgreSQL/质量门禁证据：平台注册专项 **61 passed**；Playbook 专项 **20 passed**；完整后端 **471 passed，1 warning，25 subtests passed**；`compileall`、`npm run lint` 和非 dist 差异检查通过。既有 Starlette/httpx deprecation warning 保持不变。
- P1 仍未全部完成：审批步骤、版本编辑器 UI、最新构建的浏览器交互验收、完整 Site/设备组资源矩阵、真实设备在线识别、受控 Playbook 编辑闭环和 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.7 2026-08-03 P1 SYSTEM 模板只读前端闭环

- 修复 `ParserRegistryTab` 的 SYSTEM 模板权限表现：源码编辑器和字段契约 JSON 使用 `readOnly`，SYSTEM 页面不再显示“保存草稿”，加密样例持久化按钮禁用，并显示 `SYSTEM 只读` 状态。
- 增加“Fork 为租户模板”入口，调用既有 `/api/parser-templates/{template_id}/fork` 接口创建租户模板后再进入可编辑草稿流程；浏览器核验仅确认按钮和只读属性，未替用户提交 Fork 写操作。
- 已登录浏览器核验结果：SYSTEM 模板显示只读标识；Fork 按钮可用；“保存草稿”不存在；源码与字段契约 `readOnly=true`；“加密上传样例”禁用；Sandbox 与历史回归保留为验证能力。
- PostgreSQL 后端证据沿用本轮已通过结果：平台注册专项 **61 passed**；Playbook 专项 **20 passed**；完整后端 **471 passed，1 warning，25 subtests passed**。本次前端增量门禁：`npm run lint`、`npm run build`、`git diff --check -- . ':!dist'` 通过；构建仅保留既有 chunk size warning，测试仅保留既有 Starlette/httpx deprecation warning。
- P1 仍未全部完成：审批步骤、真实设备在线识别命令采集、完整 Site/设备组资源矩阵、受控 Playbook 编辑闭环和 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.8 2026-08-03 P1 Playbook 版本编辑闭环

- 在自动化 Playbook 页面增加“受控版本编辑”视图：按场景加载版本、查看版本状态和校验状态；DRAFT 可编辑声明式 JSON，IN_REVIEW/APPROVED/PUBLISHED 自动只读。
- 新增 DRAFT 更新接口 `PUT /api/playbook-versions/{version_id}`，服务层按 PostgreSQL `lock_version` 做乐观并发条件更新；更新会重置校验状态为 `PENDING`、刷新 checksum，并写入 `UPDATE` 审计事件。非 DRAFT 版本返回 `PLAYBOOK_VERSION_IMMUTABLE`，不允许原地修改。
- 版本编辑器的创建、保存、校验、提交审核、审批、发布均复用既有权限和生命周期 API；未增加原始 Python、Shell 或任意命令执行入口。
- PostgreSQL/质量门禁证据：平台注册专项 **62 passed**；Playbook 专项 **21 passed**；完整后端 **472 passed，1 warning，25 subtests passed**；`python -m compileall -q backend`、`npm run lint`、`npm run build` 和 `git diff --check -- . ':!dist'` 通过。构建仅保留既有 chunk size warning，测试仅保留既有 Starlette/httpx deprecation warning。
- 浏览器状态：SYSTEM TextFSM 只读界面已核验；切换到 `/automation/tasks` 进行 Playbook 版本界面核验时，登录实例出现动态模块 `AutomationExecuteTab.tsx` fetch 失败并显示应用错误页，未执行强制刷新或任何写操作；Playbook 版本页面的浏览器交互验收待该实例恢复后补验。
- P1 仍未全部完成：Playbook 版本页面浏览器验收、受控执行全链路和 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.9 2026-08-03 P1 Playbook 执行审批门

- 受控步骤新增 `approval` 类型，仅允许在 `pre_check/execute` 阶段顶层定义；审批标题、说明、角色和字段集合均有边界，嵌套审批、`post_check/rollback` 审批和非 Administrator 审批角色会被拒绝。
- 新增 PostgreSQL 迁移 `m0089_playbook_execution_approvals`：持久化执行审批请求、租户、步骤路径、决策人、原因和时间；同时补齐旧执行表的状态与 `commit_confirmed_ttl` 字段，审批等待期间不丢失原执行参数。
- 受控执行遇到审批步骤时进入 `awaiting_approval`，所有审批通过后才恢复为 `pending` 并启动设备任务；任一拒绝进入 `approval_rejected`，不会启动设备任务。审批决策使用 PostgreSQL 行锁和条件更新，重复决策、自审批、跨租户和越权审批均被阻断。
- 新增 `GET /api/playbooks/{execution_id}/approvals`、审批和拒绝接口；审批正文不写入审计详情，仅记录审批 ID、步骤路径、结果和执行状态。前端编辑器及执行历史状态契约已同步支持 `approval/awaiting_approval/approval_rejected`。
- PostgreSQL/质量门禁证据：平台注册专项 **71 passed**；Playbook 版本专项 **26 passed**；完整后端 **481 passed，1 warning，25 subtests passed**；`python -m compileall -q backend`、`npm run lint`、`npm run build` 和 `git diff --check -- . ':!dist'` 通过。Build 仅保留既有 chunk size warning，测试仅保留既有 Starlette/httpx deprecation warning。
- P1 仍未全部完成：Playbook 版本页面浏览器验收、受控执行全链路和 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.10 2026-08-03 P1 在线识别与资源矩阵补充

- 在线识别命令现在从绑定 Profile 的 `connection_driver` 解析，不再把租户平台编码当作 Netmiko/命令目录键；支持 `zte/ruijie/dptech/maipu` Profile 编码映射，并将规范化驱动传入连接层。识别仍只执行白名单 `show version`/`display version`，原始回显只在进程内匹配，不写库、不返回 API。
- 增加 Cisco、Huawei、H3C、ZTE 驱动命令族回归：Cisco 使用 `cisco_ios/show version`，Huawei 使用 `huawei_vrp/display version`，H3C 使用 `hp_comware/display version`，避免 H3C 或国内平台静默回退 Cisco。
- 完善资源矩阵：平台识别读取和绑定校验使用 `site_id/site` 与 `device_group_id`；Playbook 执行详情、设备结果和解析等执行记录读取会按执行设备逐台验证租户、Site、设备组和资源动作；资源范围动作目录补齐 `bind_device/edit_draft/submit/publish/rollback/schedule` 等平台、TextFSM、Playbook 动作。
- PostgreSQL 证据：平台识别专项 **12 passed**；平台注册专项 **71 passed**；完整后端 **481 passed，1 warning，25 subtests passed**；`python -m compileall -q backend`、`npm run lint`、`npm run build` 和 `git diff --check -- . ':!dist'` 通过。构建仅保留既有 chunk size warning，测试仅保留既有 Starlette/httpx deprecation warning。
- P1 仍未全部完成：Playbook 版本页面浏览器验收、受控执行全链路和 P2 健康度/失败闭环仍待继续；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.11 2026-08-03 P2 运行健康度与失败闭环补充

- 新增 PostgreSQL 迁移 `m0090_platform_registry_health_telemetry` 和 `platform_action_runs`：每次平台注册动作记录租户、设备、Release、Action、解析阶段、结构化错误码、记录数、耗时、输出字节数和时间；失败回显仅在配置加密密钥时以密文保存，明文列固定为 `{}`，并带保留期。
- `GET /api/platform-registry/profiles/{profile_id}/health` 返回命令覆盖率、模板覆盖率、样例通过率、近窗口成功率、解析失败率、最近失败队列、绑定/在线设备、受影响 Playbook、平均/P95 延迟和按小时性能/超时趋势；健康分由覆盖度、成功率、解析失败率和最近运行新鲜度计算，暂无运行样本时返回 `unknown`。
- `POST /api/platform-registry/runs/{run_id}/parser-sample` 仅允许租户内失败记录，读取加密留存回显后先做凭据脱敏，再复用 TextFSM 样例加密写入链路；无密钥、过期、跨租户、无解析模板和非失败记录均 fail-closed。
- Release 校验、审批和发布前会对绑定的已发布解析版本读取全部历史加密样例回归；任一样例不可解密、解析失败或版本不再发布都会形成 `HISTORICAL_REGRESSION_FAILED`，阻断后续生命周期推进。
- 新增 PostgreSQL 迁移 `m0091_platform_identification_conflicts`：同分识别结果形成租户/设备/Site/设备组作用域内的 OPEN 待办，持久化内容仅为候选 Profile、规则 ID、分数和命令名；人工绑定后自动收口为 RESOLVED，提供 `GET /api/platform-registry/identification-conflicts` 查询。
- PostgreSQL/质量门禁证据：平台注册专项 **71 passed**；Playbook/解析专项 **26 passed**；完整后端 **481 passed，1 warning，25 subtests passed**；`python -m compileall -q backend`、`npm run lint`、`npm run build` 和 `git diff --check -- . ':!dist'` 通过。构建仅保留既有 chunk size warning，测试仅保留既有 Starlette/httpx deprecation warning。
- P2 代码收口已补齐：识别冲突待办持久化与查询接口仍保持只保存候选 Profile、规则 ID、分数和命令名，不保存原始回显；人工绑定后自动将对应设备的 OPEN 冲突标记为 RESOLVED。受控执行审批 API 与执行历史批准/拒绝控件已闭合；`PLATFORM_REGISTRY_ENABLED` 默认关闭保持不变。

### 15.12 2026-08-03 浏览器验收与剩余边界补充

- 浏览器验收已恢复并完成：登录态下 `/automation/playbooks` 可加载 Playbook 场景，受控版本编辑器显示场景选择、JSON 阶段编辑和创建草稿入口；未执行创建、保存、提交、发布等写操作。
- `/management/platforms` 可加载平台注册表和“运行健康度（近 7 天）”面板，当前样本为空时正确显示 `暂无运行样本`，同时展示命令/模板覆盖度、成功率、解析失败、延迟和失败队列入口。
- `/automation/textfsm-registry` SYSTEM 模板保持只读：可见 `Fork 为租户模板` 和 `Sandbox 测试`，没有 SYSTEM 原地保存入口；未上传样例、未提交或发布任何模板。
- 前端问题修复：移除 Playbook 页面误重定向到 `/automation/execute` 的旧逻辑，并为场景/平台/执行历史 API 补齐登录态请求头，避免已登录页面因 401 显示空数据。
- 实际 `/automation/history` 入口由 `ExecutionSchedule` 承载，已补充 `awaiting_approval/approval_rejected` 状态展示、审批记录读取及批准/拒绝操作；没有待审批样本时不强造执行记录，避免验收过程产生虚假业务数据。
- 最终质量门禁：平台注册专项 **71 passed**；完整后端 **481 passed，1 warning，25 subtests passed**；`compileall`、`npm run lint`、`npm run build` 和 `git diff --check -- . ':!dist'` 通过。Build 仅保留既有 chunk size warning，测试仅保留既有 Starlette/httpx deprecation warning。
- 剩余边界：本轮未对真实设备执行 Playbook Apply，也未在浏览器中批准一个真实审批实例；受控执行的数据库、锁、权限、自审批、拒绝和恢复路径由 PostgreSQL 专项测试覆盖。真实设备写操作必须在明确审批和实验设备范围内另行执行。
