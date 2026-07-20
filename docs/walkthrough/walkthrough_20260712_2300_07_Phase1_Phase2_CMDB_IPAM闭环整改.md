# Phase 1 / Phase 2 CMDB-IPAM 闭环整改完成记录

## 完成摘要

本轮完成 Phase 1 与 Phase 2 的核心闭环整改，采用非破坏式、兼容旧数据的方式完成：

- CMDB/IPAM/Discovery 三层事实源定义。
- CMDB 字段权威数据质量审计接口。
- CMDB 基础对象删除引用保护增强。
- IPAM 规范化字段兼容写入。
- prefix 重复/重叠校验增强。
- 原子 IP 分配、保留、释放接口。
- IP 地址生命周期状态 `allocated/reserved/released` 的服务层落地。
- 后端测试、前端 lint、生产 build 验证。

本轮没有删除 legacy 字段，也没有强制执行不可逆迁移。

## 实际修改文件

### 文档

1. `docs/plans/plan_Phase1_Phase2_CMDB_IPAM闭环整改.md`
2. `docs/architecture/cmdb_ipam_source_of_truth.md`
3. `docs/walkthrough/walkthrough_Phase1_Phase2_CMDB_IPAM闭环整改.md`

### 后端

1. `backend/api/cmdb.py`
   - 新增 `GET /api/cmdb/data-quality/field-authority`。

2. `backend/services/cmdb_service.py`
   - 新增 `get_field_authority_quality`。
   - 增强 site / VRF / VLAN 删除引用保护。

3. `backend/api/ipam.py`
   - 新增 `POST /api/ipam/subnets/{subnet_id}/allocate-next`。
   - 新增 `POST /api/ipam/subnets/{subnet_id}/reserve`。
   - 新增 `POST /api/ipam/addresses/{address_id}/release`。
   - 普通地址创建兼容 `interface_id`。

4. `backend/services/ipam_service.py`
   - 新增 prefix/address 规范化 helper。
   - 新增 prefix 重复与重叠校验。
   - 新增同连接事务式 allocate-next。
   - 新增 reserve/release。
   - 新写入 prefix 同步写：
     - `prefix_cidr`
     - `ip_version`
     - `prefix_len`
   - 新写入 address 同步写：
     - `address_inet`
     - `ip_version`
     - `ip_address`
     - `prefix_id`
     - `vrf_id`
     - `interface_id`

5. `backend/database/schema.py`
   - 为 `prefixes` 增加 nullable/兼容字段：
     - `prefix_cidr`
     - `ip_version`
     - `prefix_len`
   - 为 `ip_addresses` 增加 nullable/兼容字段：
     - `address_inet`
     - `ip_version`

6. `backend/tests/test_phase1_phase2_cmdb_ipam.py`
   - 新增 Phase 1/2 服务层测试。

## Phase 1 完成项

### CMDB-001：三层事实源定义

已完成。

新增文档：

```text
docs/architecture/cmdb_ipam_source_of_truth.md
```

明确：

- CMDB 是确认后的资产、站点、设备、接口、租户、VRF、VLAN 权威源。
- IPAM 是 prefix、address、pool、VIP、DHCP lease 与地址生命周期权威源。
- Discovery 是观测证据，不能直接覆盖 CMDB/IPAM。

### CMDB-002：设备、资产、接口关系重构

完成核心闭环：

- 已有设备/接口 CMDB 骨架。
- 本轮新增字段权威审计接口。
- 删除对象时增加引用阻断。
- `interface_id` 作为 IPAM/Topology 目标权威的迁移路径已经在文档与审计接口中落地。

新增接口：

```text
GET /api/cmdb/data-quality/field-authority
```

返回：

- `site_id_missing`
- `site_id_orphaned`
- `site_name_mismatch`
- `asset_id_orphaned`
- `asset_device_ip_mismatch`
- `duplicate_asset_links`
- `ip_missing_interface_id`
- `ip_orphaned_interface_id`
- `topology_missing_interface_id`
- `topology_orphaned_interface_id`

### CMDB-003：站点、租户、VRF、VLAN 关系增强

完成核心保护：

- tenant 删除已有引用保护。
- site 删除新增 devices/racks/vlans/prefixes 引用保护。
- VRF 删除新增 interfaces/prefixes/ip_addresses 引用保护。
- VLAN 删除新增 prefixes 与 interfaces access_vlan 引用保护。
- VLAN 已按 `(site_id, vlan_id)` 做唯一性校验。

## Phase 2 完成项

### IPAM-001：PostgreSQL 原生字段迁移兼容阶段

完成非破坏式兼容字段：

- `prefixes.prefix_cidr`
- `prefixes.ip_version`
- `prefixes.prefix_len`
- `ip_addresses.address_inet`
- `ip_addresses.ip_version`

说明：本轮字段类型使用兼容 `TEXT/INTEGER`，避免 SQLite 测试和现有部署断裂。后续在纯 PostgreSQL 部署阶段可进一步迁移为 `CIDR/INET` 原生类型和 GiST/SP-GiST 索引。

### IPAM-002：prefix 重叠和层级约束

完成服务层校验：

- 同 tenant/VRF/site 下禁止完全重复 prefix。
- 不同 VRF 下允许相同 prefix。
- 父子 prefix 允许存在。
- prefix 创建/更新都走校验。
- prefix 层级 rebuild 继续保留。

### IPAM-003：原子 IP 分配接口

新增：

```text
POST /api/ipam/subnets/{subnet_id}/allocate-next
POST /api/ipam/subnets/{subnet_id}/reserve
POST /api/ipam/addresses/{address_id}/release
```

实现要点：

- allocate-next 在同一个连接内锁定 prefix、计算候选地址、插入地址并提交。
- PostgreSQL 环境下使用 `SELECT ... FOR UPDATE` 锁定目标 prefix。
- SQLite 环境保留兼容路径。
- 写审计日志。

### IPAM-004：IP 地址生命周期模型

完成服务层语义：

- `allocate-next` 默认写 `allocated`。
- `reserve` 写 `reserved`。
- `release` 不硬删除，更新为 `released` 并清空设备/接口/MAC 绑定。

## 验证命令与结果

### 后端语法检查

```powershell
python -m py_compile backend\database\schema.py backend\api\cmdb.py backend\services\cmdb_service.py backend\api\ipam.py backend\services\ipam_service.py backend\tests\test_phase1_phase2_cmdb_ipam.py
```

结果：通过。

### 后端测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_phase1_phase2_cmdb_ipam.py backend\tests\test_cmdb_phase1.py backend\tests\test_cmdb_phase3_crud.py -q
```

结果：

```text
17 passed
```

### 前端 TypeScript 检查

```powershell
npm run lint
```

结果：通过。

### 前端生产构建

```powershell
npm run build
```

结果：通过。

备注：Vite 输出 chunk size warning，这是已有构建体积提示，不是失败。

### Diff 空白检查

```powershell
git diff --check
```

结果：通过，仅出现 Windows 换行提示。

## 未执行或延后事项

1. 未删除 legacy 字段：
   - `devices.site`
   - `ip_addresses.interface_name`
   - `topology_links.source_port/target_port`

2. 未强制 NOT NULL：
   - `devices.site_id`
   - `ip_addresses.interface_id`

3. 未立即使用 PostgreSQL `CIDR/INET` 原生列类型。

这些属于破坏性或部署环境相关迁移，应在数据质量审计结果稳定后执行。

## 剩余风险

1. 现有历史数据中可能存在格式不合法的 prefix/address，本轮不会主动清洗历史脏数据。
2. release 后地址保留为 `released`，不会硬删除；是否允许立即复用需要后续明确隔离期策略。
3. SQLite 环境无法提供 PostgreSQL 级别的 `FOR UPDATE` 行锁；生产 PostgreSQL 下才能完整体现并发锁语义。
4. `dist/index.html` 因执行 `npm run build` 被刷新。

## 后续建议

1. 打开 `GET /api/cmdb/data-quality/field-authority`，先看当前真实数据质量问题。
2. 根据审计结果执行：
   - site_id 回填。
   - interface_id 回填。
   - topology link interface_id 回填。
3. 在确认生产数据库为 PostgreSQL 后，设计下一阶段原生 `CIDR/INET` migration。
4. 前端 IPAM 页面后续可接入 allocate/reserve/release 三个新接口。
