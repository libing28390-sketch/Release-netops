# Nexora 自定义平台、TextFSM 与 Playbook 权限开放任务清单

> 日期：2026-08-02
> 状态：待实施
> 目标：让租户用户能够安全地适配中兴、锐捷、迪普、迈普等多型号设备，并在受控范围内编写、测试和发布 TextFSM 与 Playbook。
> 核心原则：开放声明式平台、命令映射、解析模板和受控编排，不开放任意 Python、Shell、文件系统路径或自定义连接驱动。

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

- [ ] 保存结构化解析失败原因。
- [ ] 失败回显可一键转为脱敏测试样例。
- [ ] 新版本发布前自动运行全部历史回归样例。
- [ ] 平台显示命令覆盖率。
- [ ] 平台显示模板覆盖率。
- [ ] 平台显示样例通过率。
- [ ] 平台显示最近解析失败数量。
- [ ] 平台显示绑定设备数量。
- [ ] 平台显示受影响 Playbook 数量。
- [ ] 增加未知输出和识别冲突待办列表。
- [ ] 增加解析性能和超时趋势。

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
- [ ] `POST /api/playbooks/{id}/versions`
- [ ] `POST /api/playbook-versions/{id}/validate`
- [ ] `POST /api/playbook-versions/{id}/submit`
- [ ] `POST /api/playbook-versions/{id}/approve`
- [ ] `POST /api/playbook-versions/{id}/publish`
- [ ] `POST /api/playbooks/{id}/rollback`

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
