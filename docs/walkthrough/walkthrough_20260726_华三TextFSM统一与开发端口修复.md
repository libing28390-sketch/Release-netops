# 华三 TextFSM 统一与开发端口修复

## 变更

- 在 `backend/core/textfsm.py` 增加统一解析平台映射：设备/业务层的 `h3c_comware`、`h3c_comware9` 等值进入 TextFSM 后统一使用 `hp_comware`。
- Playbook 解析、巡检、运营采集、拓扑 LLDP 和 normalizer 显式使用该映射。
- 新保存的华三模板自动规范为 `hp_comware_*.textfsm`；现有 `h3c_comware_*.textfsm` 保留为兼容回退，不再作为新模板命名规范。
- 增加/修复 `hp_comware` 的接口简表、VLAN、链路聚合和 IPv4 BGP 路由模板，覆盖 Comware V5/V7/V9 fixture。
- 更新网络驱动 skill，固定华三 TextFSM 平台规则。
- Windows 默认开发端口从保留的 `5150` 改为可配置的 `VITE_PORT`，当前默认 `5400`。`5300` 后续被系统排除端口 `5241–5340` 覆盖，因此不再作为默认端口。

## 验证

- `pytest backend/tests/vendor_audit/test_h3c_textfsm_contract.py backend/tests/vendor_audit/test_h3c_cisco_quick_queries.py -q`: 92 passed，另有 1 个既有 Comware V5 BGP 命令 fixture 不一致失败。
- `pytest backend/tests/vendor_audit/test_h3c_textfsm_contract.py backend/tests/test_custom_textfsm_flow.py backend/tests/normalizers/test_vendor_normalizers.py -q`: 17 passed。
- `npm run lint`: passed。
- `npm run build`: passed。
- `skill-creator quick_validate.py .agents/skills/netops-network-drivers`: passed。
- `npm run dev:frontend`: 默认监听 `0.0.0.0:5400`；如需临时切换，可设置 `VITE_PORT`。
- 全量 `pytest backend/tests -q` 在当前环境超过 300 秒未完成，已停止测试进程；未将其结果作为通过依据。
