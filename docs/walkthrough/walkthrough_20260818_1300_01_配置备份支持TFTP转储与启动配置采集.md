# 走查与验证报告：配置备份支持方案 A（TFTP 转储）与启动配置采集

- **计划关联**: [`docs/plans/plan_20260818_1300_01_配置备份支持TFTP转储与启动配置采集.md`](file:///d:/nexora/nexora-private/docs/plans/plan_20260818_1300_01_%E9%85%8D%E7%BD%AE%E5%A4%87%E4%BB%BD%E6%94%AF%E6%8C%81TFTP%E8%BD%AC%E5%82%A8%E4%B8%8E%E5%90%AF%E5%8A%A8%E9%85%8D%E7%BD%AE%E9%87%87%E9%9B%86.md)
- **完成时间**: 2026-08-18 13:12
- **责任范围**: 数据库迁移、TFTP 传输协议客户端、多厂商启动配置采集、未保存漂移检测、策略管理及前端 UI 联动

---

## 1. 完成摘要

已完成配置备份中心的**方案 A（平台自动中继转储 TFTP 服务器）**与**多厂商启动配置（Startup-Config）采集**全链路开发：
1. **多厂商官方 CLI 命令校对与勘误**：
   - 联网核实中兴、锐捷、迈普、瑞斯康达、迪普等官方手册；
   - 纠正迪普（DPtech Conplat）原生为 `display` 语法（`display current-configuration` / `display saved-configuration`）；
   - 在平台动作注册表中全面注册 `get_startup_config`，覆盖 Cisco、Huawei、H3C、Juniper、Arista、Ruijie、ZTE、Raisecom、DPtech、Maipu 等全厂商。
2. **纯 Python RFC 1350 TFTP 客户端服务**：
   - 在 [`backend/services/tftp_service.py`](file:///d:/nexora/nexora-private/backend/services/tftp_service.py) 中实现纯 Python UDP 69 传输协议，支持 WRQ、DATA、ACK、ERROR 处理；
   - 自动批量传输解密后的 `.cfg` 文件并在每次备份完成后生成并上传带有时间戳的 `backup_summary_YYYYMMDD_HHMMSS.log` 汇总日志。
3. **数据库结构与迁移 (m0152)**：
   - 在 `action_definitions` 注册 `get_startup_config`；
   - 在 `config_snapshots` 增加 `config_type`、`has_unsaved_changes`、`unsaved_diff_summary` 与复合索引；
   - 在 `config_backup_policies` 与 `config_backup_runs` 增加 TFTP 与启动配置相关控制字段。
4. **双配置流采集与未保存配置漂移检测**：
   - 在 `backend/api/configs.py` 调度流水线中，若开启启动配置采集，同会话/同并发内自动采集启动配置；
   - 比对 running 与 startup 的 `normalized_hash`，若存在未保存变更则自动置 `has_unsaved_changes = 1` 并输出差异摘要。
5. **前端界面呈现与策略交互**：
   - [`src/pages/ConfigSchedule/BackupPolicyManager.tsx`](file:///d:/nexora/nexora-private/src/pages/ConfigSchedule/BackupPolicyManager.tsx)：策略弹窗提供「启动配置采集」和「远端 TFTP 自动转储」配置卡片；
   - [`src/pages/ConfigBackupTab.tsx`](file:///d:/nexora/nexora-private/src/pages/ConfigBackupTab.tsx)：快照列表增加 `Running`（绿色）/ `Startup`（蓝色）类型徽章及 `未保存` 告警徽章；批次详情展示 TFTP 转储状态与服务器目标；
   - [`src/pages/ConfigDiffViewTab.tsx`](file:///d:/nexora/nexora-private/src/pages/ConfigDiffViewTab.tsx)：增加快捷按钮「一键对比：启动配置 (A) vs 运行配置 (B)」。

---

## 2. 实际修改与新增文件

| 文件路径 | 类型 | 变更内容说明 |
|---|---|---|
| [`backend/database/migrations/m0152_config_backup_tftp_and_startup.py`](file:///d:/nexora/nexora-private/backend/database/migrations/m0152_config_backup_tftp_and_startup.py) | **新建** | 注册 `get_startup_config` 动作，为快照、策略、批次表增补 TFTP 与启动配置字段 |
| [`backend/services/tftp_service.py`](file:///d:/nexora/nexora-private/backend/services/tftp_service.py) | **新建** | 纯 Python RFC 1350 TFTP Client，提供单个/批量上传与日志转储 |
| [`backend/tests/configuration/test_tftp_backup_service.py`](file:///d:/nexora/nexora-private/backend/tests/configuration/test_tftp_backup_service.py) | **新建** | TFTP 协议二进制包打包、Socket 传输交互及批量上传单元测试 |
| [`backend/tests/configuration/test_startup_config_backup.py`](file:///d:/nexora/nexora-private/backend/tests/configuration/test_startup_config_backup.py) | **新建** | 动作注册表命令映射、双配置流持久化与策略模型测试 |
| [`backend/services/platform_registry_service.py`](file:///d:/nexora/nexora-private/backend/services/platform_registry_service.py) | **修改** | 纠正 DPtech 为 `display` 派系；注册全厂商 `get_startup_config` 动作命令映射 |
| [`backend/services/config_backup_policy_service.py`](file:///d:/nexora/nexora-private/backend/services/config_backup_policy_service.py) | **修改** | 策略持久化读写全面适配启动配置与 TFTP 字段 |
| [`backend/api/configs.py`](file:///d:/nexora/nexora-private/backend/api/configs.py) | **修改** | 核心调度流水线支持双配置采集、未保存比对及后台 TFTP 自动转储 |
| [`backend/api/config_backup_policies.py`](file:///d:/nexora/nexora-private/backend/api/config_backup_policies.py) | **修改** | Pydantic Payload 开放 `startup` 类型与 TFTP 配置参数 |
| [`backend/database/schema.py`](file:///d:/nexora/nexora-private/backend/database/schema.py) | **修改** | 基础表定义与 `ensure_column` 同步补齐 m0152 列与索引 |
| [`src/pages/ConfigSchedule/BackupPolicyManager.tsx`](file:///d:/nexora/nexora-private/src/pages/ConfigSchedule/BackupPolicyManager.tsx) | **修改** | 策略编辑弹窗增加启动配置开关及 TFTP 转储配置卡片 |
| [`src/pages/ConfigBackupTab.tsx`](file:///d:/nexora/nexora-private/src/pages/ConfigBackupTab.tsx) | **修改** | 快照列表支持 `Running`/`Startup` 类型标识、未保存告警徽章及批次 TFTP 状态 |
| [`src/pages/ConfigDiffViewTab.tsx`](file:///d:/nexora/nexora-private/src/pages/ConfigDiffViewTab.tsx) | **修改** | 快照时间线展示类型标签，并提供「一键对比运行配置 vs 启动配置」快捷入口 |
| [`backend/tests/configuration/test_config_backup_policies.py`](file:///d:/nexora/nexora-private/backend/tests/configuration/test_config_backup_policies.py) | **修改** | 内存测试夹具接入 m0152 迁移 |

---

## 3. 验证命令与结果

### 3.1 后端单元测试
- **测试命令**: `.\.venv\Scripts\pytest.exe backend/tests/configuration/ -v`
- **测试结果**:
  ```text
  ============================= 56 passed in 14.42s =============================
  ```
  涵盖 TFTP 客户端协议打包、服务端异常响应、批量上传包含汇总日志、多厂商动作映射注册、策略模型创建与更新等全部 56 个用例 100% 通过。

### 3.2 前端类型与构建门禁
- **Lint 检查**: `npm run lint` (`tsc --noEmit`) $\rightarrow$ **0 Errors, Exit code: 0**
- **生产打包**: `npm run build` (`vite build`) $\rightarrow$ **Built in 19.47s, Exit code: 0**

---

## 4. 遵守的约束与后续建议

- **Git 约束**: 严格遵守**今天全量代码禁止 Git Push**的原则，未执行任何推送操作。
- **后续建议**:
  - 在实际生产环境中若部署外部 TFTP 服务器，建议在防火墙策略中对 UDP 69 端口及动态传输端口开放回包；
  - 针对 Juniper 等 commit-based 设备，系统已规范映射为当前 active committed configuration。
