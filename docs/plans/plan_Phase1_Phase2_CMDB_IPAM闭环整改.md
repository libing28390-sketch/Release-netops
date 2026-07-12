# Phase 1 / Phase 2 CMDB-IPAM 闭环整改实施计划

## 任务目标

完成企业级整改路线图中 Phase 1 与 Phase 2 的核心闭环能力：

- Phase 1：CMDB/IPAM 权威数据模型。
- Phase 2：PostgreSQL 原生 IPAM 与并发安全。

本轮实施采用“低破坏、可验证、兼容旧数据”的策略，不直接删除 legacy 字段，不强制执行不可逆 schema 变更。

## 当前完成状态

已完成或部分完成：

1. `ENT-001`：CMDB/IPAM 数据关系图与权威矩阵。
2. `CMDB-000`：设备 + 接口纳入 CMDB 主骨架。
3. `CMDB-002` 前置：字段权威边界与迁移路径。
4. 凭据中心账号角色可解释化。
5. SSH/运行数据采集凭据模式修复。

仍需补齐：

1. `CMDB-001`：三层事实源文档与 API 设计引用。
2. `CMDB-002A`：字段权威只读审计接口。
3. `CMDB-003`：站点、租户、VRF、VLAN 引用检查和删除阻断。
4. `IPAM-001`：IPAM 规范化字段与写入兼容策略。
5. `IPAM-002`：prefix 重叠和层级约束。
6. `IPAM-003`：原子 IP 分配、保留、释放接口。
7. `IPAM-004`：IP 地址生命周期语义。

## 实施范围

### 本轮优先完成

1. 新增三层事实源架构文档。
2. 新增 CMDB 字段权威数据质量审计接口。
3. 增强 CMDB 基础对象删除前引用检查。
4. 新增 IPAM 服务层：
   - prefix 格式规范化。
   - IPv4/IPv6 版本与前缀长度计算。
   - 同 VRF/site/tenant 下 prefix 重叠校验。
   - allocate-next / reserve / release。
5. 新增 IPAM API endpoint。
6. 前端先不大改页面，只保证后端 contract 稳定；如已有 IPAM 页面接入点清晰，再补最小展示。
7. 完整验证：
   - 后端语法检查。
   - pytest 相关测试或新增轻量测试。
   - npm lint。
   - git diff check。

### 本轮不做

1. 不删除 `devices.site`、`ip_addresses.interface_name` 等 legacy 字段。
2. 不强制 `site_id/interface_id` 非空。
3. 不做破坏性数据库迁移。
4. 不立即把所有 IPAM 查询迁移为 PostgreSQL `inet/cidr` 运算。

## 拟修改文件

- `docs/architecture/cmdb_ipam_source_of_truth.md`
- `backend/services/cmdb_service.py`
- `backend/api/cmdb.py`
- `backend/services/ipam_service.py` 或现有 IPAM 服务文件
- `backend/api/ipam.py` 或现有 IPAM API 文件
- `backend/tests/`
- `docs/walkthrough/walkthrough_Phase1_Phase2_CMDB_IPAM闭环整改.md`

## 实施步骤

1. 梳理现有 IPAM API 与服务实现。
2. 补三层事实源架构文档。
3. 补 CMDB 字段权威审计服务与 API。
4. 补 CMDB 删除引用检查。
5. 补 IPAM prefix 校验与原子分配服务。
6. 补 IPAM API。
7. 补测试。
8. 运行验证并记录结果。

## 验证计划

1. `python -m py_compile` 覆盖新增/修改后端文件。
2. `pytest` 覆盖新增服务测试。
3. `npm run lint`。
4. `git diff --check`。
5. 必要时通过浏览器或 API 请求做 smoke test。

## 风险与回滚思路

- 风险：IPAM 现有 API 命名可能与新 endpoint 冲突。
- 风险：历史数据中 prefix/address 格式不规范，校验可能需要兼容跳过。
- 回滚：本轮新增能力为主，删除新增 API/服务函数即可回退；不涉及 destructive migration。
