# IPAM 同步一致性：执行与验证

## 完成摘要
四类复现问题已完成代码修正：列表/核对保留跨 VRF 同 IP 的独立记录；周期发现遵守禁用策略；partial/未采集设备不赋予前缀老化资格；终端缓存写入 canonical site_id，名称从 CMDB sites 目录读取。

## 实际修改与分工
- 主 Agent：`backend/services/ipam_service.py`、新增 `backend/services/ipam_inventory_scope.py`、新增 `backend/tests/ipam/test_ipam_inventory_scope.py`；现有本地 `backend/tests/test_ipam_capacity_and_reconciliation.py` 的最小 PostgreSQL schema fixture 补充租户/VRF/站点列（该历史文件已被仓库忽略规则排除，未新增运行时兼容分支）。
- 周期发现执行者：`backend/services/prefix_discovery_service.py`、新增 `backend/tests/vendor_audit/test_prefix_discovery_job_scope.py`。
- 站点写入执行者：`backend/services/ip_locator_service.py`、新增 `backend/tests/ipam/test_endpoint_collector_site.py`。
- 主 Agent 统一集成及公共验证，计划与本文为统一交接记录；保留原有告警、前端及 dist 改动。

## 关键实现
1. 人工地址按行保留，发现匹配使用 `(tenant_id, vrf_id, canonical IP)`。VRF 名称通过租户内 VRF 目录解析，未知或歧义 VRF 不匹配权威记录；IPv6 文本形式统一。失去 CMDB 设备的端点保留为独立发现项，不推定默认租户；遗留父前缀缺失时保留地址自己的 VRF。前缀最长匹配限制租户/VRF，非法站点归属被排除，站点未知且同长前缀歧义时不任意归属。过滤/分页及响应字段保留。
2. 核对迭代全部人工地址，不再用 IP 字符串覆盖；同 IP 不同 VRF 分别产生 stale/mismatch findings。人工字段的发现补充只发生在返回对象，不写入人工记录。
3. 周期发现先调用 `should_collect(..., 'prefix_projection')`。只有显式 `collection_status='success'` 的设备进入完整覆盖集合；partial、unknown、异常及被策略跳过的设备分别计数，不计成功。
4. 老化必须显式收到覆盖集合，并要求 prefix_observations 与 discovered_devices_json 中全部 owner 已完整覆盖。未知 owner、离线/删除旧 owner、未完整覆盖的共享 owner 均不老化；人工前缀、同轮已观察前缀保持保护。
5. ARP fallback、MAC 最佳接入及直接缓存保存统一解析站点目录，交换机 hostname 不再写入站点。设备存在却无合法站点时为空；重复站点名称不任意选择。资产站点优先级与设备查询的 `COALESCE(NULLIF(pa.site_id,''), NULLIF(d.site_id,''))` 保持一致（`backend/api/devices.py`）。列表兼容历史错误缓存，读取 CMDB 当前归属并显示 sites.site_name。

## 验证
测试执行前新建 `nexora_pytest_...` 源数据库，subprocess 的 DATABASE_URL 指向该库，再由共享 fixture 创建/删除各用例数据库。源库在 finally 删除；未初始化或写入配置中的应用数据库。真实设备采集全部 mock。

- `.venv/Scripts/python.exe artifacts/run_ipam_sync_fix_tests_20261002.py`：首次 **83 passed、2 failed**，306.26 秒。两处失败均为新增测试误读取 create_address 返回中不存在的 subnet_id；修正为读取库存项中的 subnet_id，服务行为断言已通过。
- `.venv/Scripts/python.exe artifacts/run_ipam_sync_fix_tests_20261002.py backend/tests/ipam/test_ipam_inventory_scope.py -k same_ip_in_two_vrfs`：**2 passed、12 deselected**，97.18 秒。
- 集成审查追加三个边界后重新运行完整聚焦集合：`.venv/Scripts/python.exe artifacts/run_ipam_sync_fix_tests_20261002.py`，最终 **88 passed**，284.80 秒，exit code 0；临时源数据库已删除。
- `npm run lint`：通过（tsc --noEmit）。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：通过，0 violation(s)。
- 相关服务和新增测试 `py_compile`：通过。
- `git diff --check`：通过。

日志：`artifacts/ipam_sync_fix_pytest_20261002.log`、`artifacts/ipam_sync_fix_pytest_retry_20261002.log`、`artifacts/ipam_sync_fix_pytest_final_20261002.log`。未执行全量后端回归、生产构建、真实 SNMP/SSH 或部署：本次为局部同步修正，使用聚焦测试和隔离数据库，未改变前端打包行为。

## 剩余风险与回滚
- `network_endpoints` 与 `ip_inventory` 的旧发现缓存仍以 IP 为唯一键；本次已修复权威 IPAM 查询/核对记录丢失与错误合并，但不能宣称发现缓存已支持同时存储多 VRF 的重复 IP。缓存作用域改造涉及 schema 与全部写入/查找契约，应独立处理。
- 未自动回填历史错误 site 或恢复历史误标 stale 的前缀；查询会兼容旧 site 值。已有误失效前缀可在正常发现后人工核对，避免批量恢复真实失效数据。
- 带历史未知/删除 owner 的前缀保守保留，不擅自视为缺失。设备绑定资产时资产 site_id 是权威归属，仅改 devices.site_id 不会覆盖资产位置。
- 无数据库迁移、提交、推送或部署。回滚本任务服务及测试差异即可；保留之前的用户/告警改动。

## 同期 LLDP 只读排查
用户确认错误来自另一部署，且诊断显示 13 邻居，当前无法提供日志。只读确认本地代码：诊断每 walk 5 秒、UI 上限 10000 行、6 项并发；拓扑 LLDP 每 walk 4 秒、200 行、9 项并发。4 秒包围完整 walk，UDP transport 1 秒、最多两次发送；设备外层默认 300 秒、最多两次尝试。13 邻居本身不触发 200 行限制；某个 walk 失败/超时即可在仍有邻居时返回 partial。另发现本地 LLDP OID 两处错误映射，未在本次 IPAM 任务中修改；没有远端版本或日志，不能断定远端根因。

## 提交前补充
独立审查发现全部类别被过滤后空 envelope 的 `0 == 0` 判断仍返回 success。read_only_collection_adapter 现要求非空类别且全部成功；空类别返回 partial。新增适配器状态及真实周期发现/前缀老化回归，保护 miss_count=2 的旧前缀。审查后前缀与 LLDP 聚焦集合 71 passed。今天修改过的历史最小 PostgreSQL 夹具 `backend/tests/test_ipam_capacity_and_reconciliation.py` 此次精确加入版本控制，保留原断言，便于后续重现验证。
