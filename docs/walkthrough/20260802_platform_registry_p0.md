# P0 平台注册表基础闭环实施记录

日期：2026-08-02

本次完成的是 P0 的后端基础闭环，保持旧版 TextFSM 文件读取兼容，不修改生产数据库文件。

## 已交付

- 新增 `m0072_platform_registry_p0` 迁移，创建平台 Profile、不可变 Release、逻辑动作注册表、Release 动作映射、Parser 模板/版本/样例、识别规则和审计表。
- 回填 `devices.platform_profile_id`、`platform_source`、`platform_locked`、`tenant_id`，按既有平台值绑定 SYSTEM Profile。
- 导入 `data/textfsm_templates` 为 SYSTEM Parser v1，并记录 checksum；运行路径可按模板版本 ID 读取，不依赖同名文件覆盖。
- 注册 20 个标准 `action_code` 和 Cisco、Huawei、H3C、Juniper、Arista、中兴、锐捷、迪普、迈普 SYSTEM Profile。
- 新增统一 `execute_platform_action()`：只读取当前已发布 Release，拒绝未知动作、命令拼接、配置模式和非 show/display/get 命令，限制回显大小/记录数，并返回可追溯的 Release、命令和 checksum 信息。
- 新增平台注册表 API：Profile 查询/创建、Release 草稿、动作映射、校验、提交、审核、发布、回滚和动作执行。
- 拓扑发现的版本、接口、LLDP 命令改由已发布 Release 动作映射提供，缺少映射时返回 `UNSUPPORTED_ACTION`，不回退 Cisco 命令。
- RBAC 保留旧 generic action，同时加入 P0 的 `view`、`edit_draft`、`submit`、`approve`、`publish`、`rollback`、`bind_device`、`test`、`schedule` 等动作词汇。

## 验证结果

- `.venv\Scripts\python.exe -m pytest backend/tests/platform_registry/test_platform_registry.py backend/tests/vendor_audit/test_platform_parser_boundary.py backend/tests/vendor_audit/test_lldp_collection_contract.py -q`：12 passed
- `.venv\Scripts\python.exe -m pytest backend/tests/vendor_audit -q`：279 passed
- `npm run lint`：通过
- `npm run build`：通过；只有现有 chunk size warning
- `python -m compileall`：通过
- 完整 `pytest backend/tests`：在 124 秒无输出超时，未产生失败栈；需要后续在 CI/可交互终端继续定位既有长测阻塞

## 后续 P1/P0 延伸

前端平台管理页面、TextFSM 在线编辑器、声明式识别规则执行、Playbook 版本模型和其余消费者（CMDB/采集/诊断/巡检/IP 定位）的完整迁移仍属于清单中的后续工作；本次未把这些未完成项标记为已完成。
