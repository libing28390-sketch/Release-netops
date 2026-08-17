# EVAL-016 Evidence

## Task ID

EVAL-016 — 使用 Mock/Fixture 验证 Cisco、Huawei、H3C 平台映射和只读命令。

## 目标

在不连接真实网络设备、不执行写命令、不使用 SQLite 的前提下，验证 Huawei VRP、Cisco IOS/IOS-XE/NX-OS、H3C Comware v5/v7/v9 的平台映射、命令族、TextFSM 解析和只读执行边界。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-016-PLATFORM-READONLY-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval016_platform_check.py`
- `tests/knowledge_engine_v2/test_eval016_platform.py`
- `docs/knowledge-engine-v2/eval/eval-platform-readonly-v1.manifest.json`
- `docs/walkthrough/20260817_eval016_platform.md`

## 实现内容

- 固化三厂商平台与只读命令 contract。
- 使用仓库内官方 CLI fixture、TextFSM fixture、Mock driver 和只读 command guard。
- `-p no:conftest` 运行 fixture 测试，不加载任何历史数据库 fixture。
- 增加 PostgreSQL V1 baseline 只读探针，确认平台测试没有破坏现有检索基线。

## 执行命令与结果

环境：`DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/netops`，`PYTHONPATH=backend`。

1. `.venv\Scripts\python.exe -m py_compile scripts\knowledge_engine_v2_eval016_platform_check.py tests\knowledge_engine_v2\test_eval016_platform.py` — PASS。
2. `.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval016_platform_check.py` — **PASS**；Huawei/Cisco/H3C、只读命令和 UNKNOWN boundary 全部 PASS；fixture **123 passed**；V1 PostgreSQL baseline 10/10；`sqlite=not_used`。
3. `.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval016_platform.py -q -p no:cacheprovider` — **2 passed**。
4. Fixture/Mock focused suite（`-p no:conftest`）— **123 passed**；无数据库连接、无 SQLite fixture。
5. V1 PostgreSQL baseline：retrieval_accuracy=1.0、citation_accuracy=1.0、wrong_vendor_rate=0.0、version_conflict_rate=0.0、rollback=transaction_rollback。
6. `git diff --check` — PASS。

## 关键输出

- Huawei：VRP5 版本、接口、ARP、LLDP、Eth-Trunk 解析与 VRP5/VRP8 alias 映射 PASS。
- Cisco：IOS/IOS-XE/NX-OS 命令族、LLDP-only neighbors、官方 fixture 解析 PASS。
- H3C：Comware v5/v7/v9 显式模板 variant、BGP/接口/VLAN/环境命令族分离 PASS。
- Read-only：`configure terminal`、shell chaining、running-config 安全边界 PASS；enable secret 仅显式提供时使用，日志不泄露密码。
- UNKNOWN：未知平台保持 unknown，不默认降级为 Cisco。

## 数据库影响

Mock/Fixture 测试不建立数据库连接；V1 只读基线使用 PostgreSQL 临时表并事务回滚，无生产写入。SQLite 未作为证据。

## 安全影响

验证命令写入 guard、shell chaining 拒绝、enable secret 边界、密码日志脱敏和未知平台 fail-closed；不连接设备、不发网络包。

## 回滚方式

无设备和生产 DDL/DML 写入；V1 probe rollback=transaction_rollback。代码变更可随提交回滚。

## 已知限制

本任务不替代真实设备兼容性验收；真实设备只能在批准的只读窗口执行。需要数据库持久化的 platform registry 历史 SQLite 测试不属于本门禁。

## 最终结论

**PASS** — Cisco、Huawei、H3C 平台映射、Mock/Fixture 解析、只读命令安全边界和 PostgreSQL V1 保持要求均满足。
