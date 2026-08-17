# 同步 LibreNMS 全量 MIB 库实施方案

## 1. 任务背景与目标

用户明确要求：“我要的是这个项目（https://github.com/librenms/librenms）里全部的 MIB”。
LibreNMS 仓库官方维护了全球最庞大、覆盖 300+ 厂商的 `mibs/` 目录。
本次任务目标：
1. **真实拉取 LibreNMS 完整 `mibs/` 目录**：通过 Git Sparse Checkout 或专用同步脚本拉取全部厂商目录下的真实 MIB 文本文件。
2. **全厂商自动归类与批量解析入库**：自动扫描所有厂商子目录，批量解析 MIB 符号节点（OID、SYNTAX、Description）并建立高性能索引。
3. **支持一键在线同步与离线加载**：
   * 编写专用同步脚本 `backend/scripts/sync_librenms_mibs.py`。
   * 后端提供 `POST /api/platform-registry/mibs/sync-librenms` 异步同步接口。
   * 前端 MIB 管理弹窗增加“同步 LibreNMS 全量 MIB 库”功能。

---

## 2. 拟修改与新增文件清单

| 文件路径 | 变更类型 | 说明 |
| :--- | :--- | :--- |
| `backend/scripts/sync_librenms_mibs.py` | [NEW] | 独立全量同步与批量解析脚本 |
| `backend/services/snmp_mib_service.py` | [MODIFY] | 优化高并发/大批量 MIB 节点批量写入与目录扫描 |
| `backend/api/devices.py` | [MODIFY] | 增加 `/platform-registry/mibs/sync-librenms` 接口与状态管理 |
| `src/components/SnmpMib/MibUploadModal.tsx` | [MODIFY] | 增加“从 LibreNMS 全量同步”交互与进度展示 |
| `backend/tests/snmp/test_snmp_mib_repository.py` | [MODIFY] | 测试全量同步服务与批量解析逻辑 |

---

## 3. 验证计划

1. 运行 `sync_librenms_mibs.py` 验证实际拉取与入库结果。
2. 运行 `pytest backend/tests/snmp/` 验证测试。
3. 运行 `npm run lint` 验证前端代码。
