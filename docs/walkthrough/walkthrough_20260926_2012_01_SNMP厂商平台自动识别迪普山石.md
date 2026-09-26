# SNMP 厂商平台自动识别迪普与山石实施记录

## 完成摘要

资产详情的“自动识别”现在先读取实时 SNMP `sysObjectID` / `sysDescr`，再用已缓存版本，最后才走 CLI。厂商识别结果作为候选展示，不会自动改写设备厂商或平台；如果 SNMP 识别结果和已登记厂商/平台族不一致，会显示冲突提示并停止生成平台候选。

- 迪普沿用已有 enterprise OID `1.3.6.1.4.1.31648` 和 DPtech 平台候选映射。
- 补充 `S211...` 版本字符串提取，避免从 `sysDescr` 识别出 DPtech 厂商后误落到“未知系统”。
- 山石沿用已有 enterprise OID `1.3.6.1.4.1.24681`、`1.3.6.1.4.1.28557`，新增 `hillstone_stoneos` 平台候选与 system profile。
- 山石 profile 由版本 `m0255_hillstone_stoneos_platform` 幂等迁移为存量数据库创建；迁移尚未在当前运行数据库执行。

## 实际修改文件

- `backend/api/platform_registry.py`：将 live SNMP 身份检测放到缓存版本和 CLI 回退之前。
- `backend/api/assets.py`：让 Hillstone / StoneOS / 山石在资产创建和平台兼容纠正时都落到 `hillstone_stoneos`，不再默认使用 Cisco。
- `backend/services/config_vendor_platform_service.py`：将 StoneOS、Hillstone StoneOS、山石平台别名规范化到 Hillstone canonical platform。
- `backend/services/platform_identification_service.py`：消费现有 SNMP vendor resolver，返回识别厂商、来源和候选；补 Hillstone 归一化、平台映射和 DPtech S211 版本提取，并对资产厂商/平台族冲突 fail closed。
- `backend/services/platform_registry_service.py`：注册 `hillstone_stoneos` system profile、连接驱动允许项、别名和平台元数据。此前已有的 Hillstone 备份命令保持为：运行配置 `show configuration running`，启动配置 `show configuration startup`。
- `backend/database/migrations/m0255_hillstone_stoneos_platform.py`：调用既有 system profile seed helper，保持可重复执行；回滚时保留 profile，避免破坏设备外键引用。
- `src/components/DeviceDetailModal.tsx`：展示 SNMP 识别到的厂商及来源，翻译识别状态；厂商或平台族冲突时提示先核对资产信息，并禁用选择和保存。
- `src/utils/platformVendor.ts`：补齐 Hillstone / StoneOS / 山石的厂商归一化和中英文名称。
- `backend/tests/platform_registry/test_platform_identification.py`：同步已有识别来源断言，并增加 DPtech/Hillstone OID 候选、冲突不写回、SNMP 优先顺序覆盖。
- `backend/tests/configuration/test_startup_config_backup.py`：同步内置厂商及 Hillstone 命令覆盖预期。
- `backend/tests/vendor_audit/test_hillstone_support.py`：覆盖资产 API 和配置模板厂商/平台别名。

## 验证

- `.venv\Scripts\python.exe -m pytest -q --tb=short backend/tests/configuration/test_startup_config_backup.py backend/tests/configuration/test_config_vendor_platform_service.py backend/tests/configuration/test_scheduled_backup_driver_dispatch.py backend/tests/platform_registry/test_platform_identification.py backend/tests/vendor_audit/test_hillstone_support.py`：76 passed（180.95s），使用命名隔离 PostgreSQL 测试库；执行结束后已删除。
- `npm run lint`（`tsc --noEmit`）：通过。
- `.venv\Scripts\python.exe scripts/validate_postgresql_only.py`：0 项违规。
- `.venv\Scripts\python.exe -m py_compile ...`：变更的 Python 服务、迁移及测试文件语法检查通过。
- `git diff --check`：通过；Git 提示工作副本的 LF 会在后续写入时转成 CRLF，无空白错误。
- 未连接真实设备或对当前应用数据库执行迁移。

## 未验证项与剩余风险

- 真实设备返回的 sysObjectID/sysDescr 尚未核对。识别需要已配置且可达的 SNMP；没有可用 SNMP 数据时，仍回退到缓存版本或既有 CLI 流程。
- 迪普平台候选会按 `sysDescr` 中的软件信息区分 S211 与 ConPlat 未知版本；山石先按 StoneOS 家族候选处理，不推断未验证的版本差异。
- 存量数据库需要在后端启动/迁移流程应用 m0255 后，才能从平台列表读取山石 profile。识别只返回建议；厂商与平台字段仍由资产维护和用户保存绑定控制。
