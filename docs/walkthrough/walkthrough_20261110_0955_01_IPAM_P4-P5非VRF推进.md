# IPAM P4-P5 非 VRF 范围推进

## 完成摘要

按用户要求继续 P4/P5，并暂缓 VRF 创建、映射和迁移专项。批量重复 CIDR 提示已显示具体 CIDR、记录数及站点。P5 A01-A36 首轮证据矩阵已建立，非 VRF 项仍需逐项复核，不能据此宣称 P5 完成。

**最新状态（2026-11-11）：**仅处理华三侧。当前正式表为 46 条 Prefix、22 条已映射、24 条待确认；H3C 侧 29 条过时/冗余 Prefix 已通过审计删除且均无台账依赖，其中 8 条 `10.200.*` 与 6 条 `10.255.0.1–.6` 当前 H3C 路由/接口无依据，另 15 条为现行 `10.254.*` canonical Prefix 的同站点冗余副本。3 条有当前路由依据的 H3C Prefix 已映射到 Global。余下 12 组/24 条重复 CIDR 都包含 Cisco 侧记录；按用户要求未连接、未验证、未修改 Cisco。P4 两份 CSV 已刷新并通过结构与只读事实验证；P5 仍未全验收。

## 实际修改文件

- `docs/plans/plan_20261110_0955_01_IPAM_P4-P5非VRF推进.md`
- `docs/walkthrough/walkthrough_20261110_0955_01_IPAM_P4-P5非VRF推进.md`
- `docs/plans/ipam_p4_mapping_review_20261110.csv`（按当前台账只读刷新：5 条已有地址空间映射，55 条仍待确认）
- `docs/plans/ipam_p4_duplicate_review_20261110.csv`（26 组重复 CIDR，52 条记录）
- `docs/plans/ipam_p5_evidence_matrix_20261110.csv`（覆盖 A01–A36 的首轮证据定位和后续缺口）
- `backend/services/ipam_service.py`（显式 Global routing-context 映射可解析 H3C 空 key unknown context）
- `docs/plans/ipam_p4_mapping_review_20261110.csv`、`docs/plans/ipam_p4_duplicate_review_20261110.csv`（2026-11-11 最新事实和 Cisco 未处理范围）
- `docs/plans/plan_20261105_1322_01_IPAM核心范围与台账归属整改.md`
- `handoff.md`
- `backend/services/ipam_address_space_service.py`
- `backend/tests/ipam/test_ipam_address_spaces.py`
- `scripts/validate_ipam_p4_mapping_review.py`
- `src/pages/IPVlan/PrefixManagementTab.tsx`
- `src/pages/IPVlan/PrefixManagementTab.test.tsx`

## 关键范围约束

- 初始基线（2026-11-10）：60 条 Prefix；其中 5 条已映射到现存 `kind=vrf` 地址空间，55 条未映射；26 组重复 CIDR 涉及 52 条记录。5 条现存映射仅记录状态，不作 VRF 审查或变更。
- 当前基线（2026-11-11）：46 条 Prefix；22 条已映射、24 条未映射；12 组/24 条重复 CIDR。所有剩余重复组均包含 Cisco 侧记录；用户要求本轮仅处理 H3C，故 Cisco 侧保留。
- 不把无 VRF 的 Prefix 自动视作 Global。
- 不读取、回填或清理历史 discovery observations。
- 不向应用库/生产库写入，不运行迁移，不连接真实设备。
- P4 映射、试点和回滚依赖人工确认的目标地址空间；目标 scope 与 canonical 选择保持空白。
- 批量预览只读；任何一项有阻断时不提交部分结果。

## 验证命令与结果

- 数据基线：`PGOPTIONS='-c default_transaction_read_only=on'` 下设置 `SET TRANSACTION READ ONLY`，只读取 Prefix、地址空间 ID、站点和 CIDR；最后 rollback/close。未访问历史观察表。结果：60 Prefix、5 已映射、55 待确认、26 个重复 CIDR 组/52 行。
- 后端 P4：`.venv/Scripts/python.exe -u backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_address_spaces.py -k batch_address_space_preview_blocks_duplicate_cidrs`：**1 passed, 20 deselected**；runner 确认 configured application database was not opened，并删除本次 source DB。
- 后端 P5 非 VRF 定向集：**8 passed, 81 deselected / 143.39s**；runner 删除本次 source DB。

  ```powershell
  .venv/Scripts/python.exe -u backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_pools.py backend/tests/ipam/test_ipam_allocation_policy.py backend/tests/ipam/test_ipam_write_lock_order.py backend/tests/ipam/test_ipam_write_idempotency.py backend/tests/ipam/test_ipam_address_spaces.py backend/tests/ipam/test_ipam_vips_leases.py -k "ipv6_64_first_free_search_does_not_iterate_the_network or ipv6_64_pool_candidate_is_bounded_without_enumerating_subnet or concurrent_last_address_allocation_has_no_duplicate_or_hang or allocate_next_replays_same_idempotency_key_and_rejects_changed_payload or address_revision_rejects_stale_edit or batch_prefix_address_space_confirmation_rolls_back_every_prefix_on_late_failure or pool_ranges_conflict_across_parent_child_prefixes_but_not_spaces or expired_or_unscoped_lease_never_releases_existing_static_address"
  ```

- 后端 P5 A02：`.venv/Scripts/python.exe -u backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_address_spaces.py -k same_address_space_rejects_cross_site_duplicate_prefix_but_other_space_allows_reuse`：**1 passed, 21 deselected / 111.01s**；验证同空间跨站点重复被拒、不同地址空间可复用 CIDR。
- 后端 P5 A16：`.venv/Scripts/python.exe -u backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_address_spaces.py -k ipv6_equivalent_host_text_is_canonical_and_cidr_suffix_is_rejected`：首轮测试断言期待 Prefix 内重复文案，但实现先在 address-space 冲突层拒绝，原断言 **1 failed**；将断言改为匹配实际的更严格地址空间级拒绝后复跑 **1 passed, 22 deselected / 93.85s**。同时确认地址带 `/128` 后缀被拒绝。两次 runner source DB 均已删除。
- 前端：`npx --no-install vitest run src/pages/IPVlan/PrefixManagementTab.test.tsx`：**16 passed**，新增用例确认提示包含标准 CIDR、重复数量、涉及站点，并且阻断时确认按钮不可用。随后 `npx --no-install vitest run src/pages/IPVlan`：**139 passed / 20 files**。
- TypeScript：`npm run lint -- --pretty false` 通过。
- PostgreSQL-only：`.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：**0 violations**。
- P4工作表检查：`.venv/Scripts/python.exe scripts/validate_ipam_p4_mapping_review.py`：确认 60 Prefix / 5 mapped / 55 unmapped / 26 duplicate groups / 5 partly mapped groups；负向临时副本将无效 CIDR 拒绝。脚本只读 CSV，不连接数据库、不推断 scope。
- Python：相关 address-space service、API、schema 和测试文件 `py_compile` 通过。
- 生产构建：`npx --no-install vite build --outDir node_modules/.cache/nexora-ipam-p4-p5-novrf-20261110`：**4362 modules transformed，build 成功**；输出位于独立 cache 目录。
- 浏览器：未完成。Computer Use 无法高置信度判断 Chrome 当前 URL 后停止；未进行页面输入、登录或提交。

## 未执行验证及原因

- 全量 P5 A01–A36 复核、非 VRF 代表性性能门槛、完整迁移/fresh-schema/失败回滚矩阵、真实设备和浏览器验收未完成。
- P4 的 55 条待映射 Prefix 与 26 组重复 CIDR 尚缺人工目标空间及 canonical/跨域复用决策；依赖这些决策的 preview、shadow compare、pilot 和 rollback rehearsal 未做。
- 用户要求 VRF 相关事项先跳过；此处没有创建、迁移或调整任何 VRF。

## 剩余风险与后续建议

- P4 工作表中的 55 条未映射 Prefix 仍需逐条确定地址空间；26 组重复 CIDR 需确认合法跨域复用或 canonical 记录。5 条现存 VRF 映射按当前用户要求不审查。
- P5 按证据矩阵继续完成非 VRF 项；当前本轮已补 A02 同域跨站点唯一性回归及A15/A17/A18/A19/A20/A28/A29定向证据。真实设备、浏览器全流程、migration/fresh schema、规模性能门槛、恢复与回滚演练仍需分别留证。
- 未提交、推送、部署或改动生产数据。

### 2026-11-10 A31 非 VRF 权限边界修复

#### 完成内容

- Prefix/IP 相关读路由统一按授权 Prefix ID 或 tenant/site scope 过滤；过滤发生在聚合、总数、库存站点清单和分页之前。覆盖 Prefix 列表与分类汇总、IP inventory、单 Prefix 地址、冲突、IPAM summary、利用率 analytics、层级树。
- 接口候选预览对受限用户只返回授权 tenant/site 下的候选，并隐藏无法可靠确定归属的 skipped 样本及计数；候选生成在 API 与 service 两层都限制授权范围，越权 candidate ID 不会进入写入阶段。
- 地址空间单条/批量预览与确认检查目标空间的完整可见范围；校验范围包含 Prefix、活动 routing-context 和当前已映射 ARP/ND/FHRP/interface 观测来源的 owner site。创建 Prefix 时校验目标空间；共享地址空间的 next-available IP/Prefix 查询也执行同一检查。
- 隐藏的 discovery evidence detail 与不可见站点查询返回 404。独立导出端点不存在；当前导出通过受范围过滤的页面 API 获取数据。没有做受限角色的浏览器导出验收。
- 新增 `backend/tests/ipam/test_ipam_read_scope_matrix.py`，以两个站点、共享地址空间、受限 Viewer/Operator 覆盖列表与汇总、inventory、冲突、next-available、原始 evidence、单条/批量目标 scope、Prefix 创建目标及候选预览/生成边界。

#### 实际修改文件

- `backend/api/ipam.py`
- `backend/services/ipam_service.py`
- `backend/tests/ipam/test_ipam_read_scope_matrix.py`
- `docs/plans/plan_20261110_0955_01_IPAM_P4-P5非VRF推进.md`
- `docs/plans/plan_20261105_1322_01_IPAM核心范围与台账归属整改.md`
- `docs/plans/ipam_p5_evidence_matrix_20261110.csv`
- `docs/walkthrough/walkthrough_20261110_0955_01_IPAM_P4-P5非VRF推进.md`
- `handoff.md`

#### 验证

- 隔离 PostgreSQL 综合定向回归：**8 passed, 49 deselected / 131.06s**，覆盖新增权限矩阵和既有地址空间审批、Pool scope、current evidence 与非 VRF 候选基线；runner 确认未打开配置中的应用数据库，临时 source DB 已删除。

  ```powershell
  .venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_read_scope_matrix.py backend/tests/ipam/test_ipam_address_spaces.py backend/tests/ipam/test_ipam_pools.py backend/tests/ipam/test_ipam_current_endpoint_api.py backend/tests/ipam/test_ipam_interface_snapshot_candidates.py -k "restricted_user_lists or address_space_previews_require_complete_target_scope or interface_candidate_preview_and_generation_are_site_scoped or prefix_address_space_resolution_requires_fresh_explicit_confirmation or batch_address_space_api_enforces_scope_for_every_selected_prefix or pool_id_next_and_allocate_require_scope_to_both_prefixes or current_endpoint_routes_use_only_current_observations_and_explicit_writes or snapshot_candidates_without_vrf_require_explicit_global_and_are_not_bulk_generated"
  ```

- 单独的新增矩阵文件：**3 passed / 86.86s**，其中含受限用户批量映射、Prefix 创建目标和候选生成越权不落库断言；source DB 已删除。
- `py_compile`、`scripts/validate_postgresql_only.py`（0 violations）和相关路径 `git diff --check` 通过。

#### 未完成项与限制

- P5 A31 的后端主要非 VRF 路径已修复并回归；完整角色/动作组合、浏览器导出行为、真实授权角色配置矩阵尚未验收。
- P5 A01–A36 其余非 VRF 项仍需逐条证据复核；VRF 查询上下文与迁移专项按用户要求暂缓。
- P4 的 55 条 Prefix 目标空间、26 组重复 CIDR 的跨域复用/canonical 选择仍待人工决定；没有进行任何数据映射、数据库迁移、设备操作或部署。

### 2026-11-10 A15/A18/A20 非 VRF 定向完善

- A15 修复 `get_next_available_prefix` 仅扫描前 1,000 个子网候选的问题。新增 `_first_available_child_prefix`：将 address-space 内现存 Prefix 转换成候选序号的阻断区间，按现存记录量查找空位，候选总数再大也不遍历整个地址块；同时修正已有子网落在某个大候选内时应阻断该候选的判断。
- A15 新增 10,000 个已占 host 后继续找到首个 free IP、1,000 个已占 IPv6 `/64` 后找到第 1,001 个子网、服务层 1,000 个已登记 `/26` 后仍返回第 1,001 个候选，以及现存 `/25` 阻止重叠 `/26` 的回归。
- A18 新增并发竞争 PostgreSQL 测试：external DHCP Pool range create、接口快照生成、人工 first-free allocation 三个线程同时争同一 host/range；同一 scope advisory lock 使结果保持互斥，不出现 Pool 与正式 IP 双重占用。
- A20 加强 batch late-failure 测试：第一条审计事件先真实写入同一事务，第二条模拟审计异常；随后断言 Prefix、正式 IP、Pool 和 audit event 全部回滚。

#### 综合验证

- 隔离 PostgreSQL A31/A15/A18/A20 定向集：**11 passed, 61 deselected / 177.27s**；覆盖 A31 最新 target owner 检查、A15 5 项边界/service wiring、A18双人及三方并发和A20审计事务。临时 source DB 已删除。
- A18 Pool range + interface generation + allocation 三方竞态单独隔离：**1 passed, 2 deselected / 85.63s**；source DB 已删除。

  ```powershell
  .venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_read_scope_matrix.py backend/tests/ipam/test_ipam_interface_snapshot_candidates.py backend/tests/ipam/test_ipam_write_lock_order.py backend/tests/ipam/test_ipam_allocation_policy.py backend/tests/ipam/test_ipam_address_spaces.py -k "restricted_user_lists or address_space_previews_require_complete_target_scope or interface_candidate_preview_and_generation_are_site_scoped or interface_generation_and_manual_allocation_cannot_claim_same_address_concurrently or external_pool_generation_and_allocation_do_not_claim_the_same_range_concurrently or first_free_address_searches_past_ten_thousand_occupied_hosts or first_available_child_prefix_searches_past_one_thousand_occupied_subnets or first_available_child_prefix_skips_ranges_inside_an_existing_child or next_available_prefix_finds_child_after_one_thousand_existing_prefixes or test_ipv6_64_first_free_search_does_not_iterate_the_network or batch_prefix_address_space_confirmation_rolls_back_every_prefix_on_late_failure"
  ```

- `py_compile` 相关 API/service/测试文件通过；`scripts/validate_postgresql_only.py` 为 **0 violations**；P4 工作表脚本报告 60 Prefix、5 mapped、55 unmapped、26 duplicate CIDR groups、5 partly mapped groups，未访问数据库；路径 `git diff --check` 无 whitespace error（Git 仅提示 LF→CRLF 的后续转换）。
- 未执行大规模耗时/SQL基准；A15性能预算仍待定。A18更大worker压力及更多Pool边界、A20不同写入位置的完整失败矩阵还未覆盖。P4目标映射和浏览器导出验收仍待处理。

### 2026-11-10 A18/A20 与非 VRF P5 复核补充

- A18 三方并发测试现在在一个隔离 PostgreSQL 数据库内重复 5 轮。每轮由 external DHCP Pool 创建、当前接口快照候选生成、人工首个可用 IP 分配同时争同一地址；五轮都保持互斥，没有 Pool 与正式 IP 双重占用。
- A20 增加 Pool 更新约束失败注入：批量确认先更新 Prefix 与正式 IP，再在 Pool 更新时触发 PostgreSQL `CheckViolation`；确认整个事务回滚，Prefix、IP、Pool address-space 和 audit event 均未残留。此前的第 2 条 audit 写入失败测试也已验证首条真实 audit insert 会随事务回滚。
- 选定的 P5 A21、A23–A29 后端隔离 PostgreSQL 回归：**9 passed, 96 deselected / 148.23s**。包括正式 owner/观察位置分离、同站点跨地址空间网关 IP、FHRP current projection、Anycast正式关系、FDB unknown path、释放隔离期和过期/无 scope DHCP lease。
  ```powershell
  .venv/Scripts/python.exe -u backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_write_lock_order.py backend/tests/ipam/test_ipam_address_spaces.py backend/tests/ipam/test_ipam_allocation_policy.py backend/tests/ipam/test_prefix_batch_and_gateway_candidates.py backend/tests/ipam/test_ipam_fhrp_groups.py backend/tests/ipam/test_ipam_current_endpoint_api.py backend/tests/ipam/test_ipam_vips_leases.py -k "external_pool_generation_and_allocation_do_not_claim_the_same_range_concurrently or batch_prefix_address_space_confirmation_rolls_back_after_pool_constraint_failure or manual_inventory_keeps_observed_endpoint_fields_out_of_ledger_owner or same_site_gateway_ip_is_isolated_between_explicit_address_spaces or anycast_one_formal_vip_and_multiple_members or current_group_route_returns_only_member_current_snapshot_and_coverage or current_fdb_path_classifier_never_promotes_unknown_interface_to_edge or released_address_is_blocked_until_quarantine_expires or expired_or_unscoped_lease_never_releases_existing_static_address"
  ```
- A21/A27 前端定向回归：`npm run test:frontend -- --run src/pages/IPVlan/IPAddressTab.edit.test.ts src/pages/IPVlan/DiscoveredEndpointsTab.test.tsx`，**2 files / 23 tests passed / 6.78s**。
- A15 10,000 条正式 IP service 用例单独隔离运行 **1 passed, 36 deselected / 97.27s**；另有既有 11-test 联合批次涵盖 10,000 host 纯算法、1,000 Prefix service、A31读范围、A18并发与A20 audit回滚。以上 runner 使用临时 source DB，均确认未打开配置中的应用数据库并删除临时 DB。
- 代码与静态校验：更新后测试通过 `py_compile`；PostgreSQL-only policy 为 **0 violations**；P4工作表校验为 60 Prefix / 5 mapped / 55 unmapped / 26 duplicate groups / 5 partly mapped groups，无数据库访问。
- 未完成项仍包括：A15 latency/SQL预算，A18更大 worker 压力及更多 Pool 边界，A20更完整的第 N 项失败组合；浏览器/真实设备验收；P4的55条目标空间及26组重复CIDR人工决策。VRF 专项仍按要求跳过。

### 2026-11-10 P4实时事实核对、A31修正与A34恢复演练

- P4实库只读核验按 `physical_site` 对应的 `sites.site_name` 比较；初次把 site_code 当成站点名称产生的假差异已排除。真实差异为5条既有映射Prefix的 `current_vrf_id` 事实列为空；只补齐这些当前值，保持所有人工决策列不变。
- 新增并运行 `scripts/validate_ipam_p4_live_facts.py`：当前正式表与两份P4工作表在60条Prefix事实、26组重复记录/站点/地址空间映射字段上 **0 mismatch**。校验使用 PostgreSQL 只读事务；仅访问 Prefix、site、address-space、当前routing-context及正式IP/Pool/VIP/Lease表，不读历史 observations。
- A31错误已修复：`/api/ipam/routing-contexts` 列表对每个映射行使用设备site授权，并确认用户可见该地址空间；不再要求用户看见此共享地址空间的所有站点。完整IPAM首次运行 **286 passed, 1 failed / 2311.67s**，失败正是该过严条件。修复后包含该用例、A31 scope matrix、A18八worker、A20回滚等的隔离批次 **7 passed**；失败由单项回归复现并已通过。完整IPAM套件修复后未重跑。
- A18八worker测试同时启动8个first-free allocator、external DHCP Pool创建和接口快照生成，验证同一host不会被Pool与正式IP重复占用；已在上述7-test批次通过。
- A25补充确认：同一地址空间内Anycast VIP占用会阻止普通IP复用；不同地址空间可以复用同一host。定向隔离 **1 passed, 19 deselected / 123.67s**。前端 `ipamExport.test.ts` 增加导出分页权限头/过滤条件回归，**7 passed**。
- A34新增 `scripts/rehearse_ipam_current_data_restore.py` 并实跑通过：两个本地临时PostgreSQL库执行fresh schema version 320 → 四张当前台账表逻辑dump → fresh库restore → 正常初始化复核；1个address-space、2条Prefix、1条正式IP、1个Pool一致恢复，未映射Prefix仍未归入Global。临时库均删除，历史观察表未dump。
- 其他验证：`scripts/validate_ipam_p4_mapping_review.py`通过；PostgreSQL-only扫描0违规；受影响Python文件`py_compile`通过。用户要求停止浏览器调用，未做浏览器导出/角色矩阵和真实设备验收。
- 尚未完成：A15延迟/SQL目标，A18更长时间和更多Pool边界压力，A20其他故障点矩阵；P4 55条目标空间和26组重复CIDR人工裁决、影子比对、试点/回滚。VRF继续跳过；没有修改应用/生产数据库、运行应用/生产迁移或连接设备。

### A15 大规模分配性能优化（2026-11-10）

- 100,000 条记录只存在于临时压测库，作为合成正式 IP 规模，不是用户当前 IP 数；测试结束自动删除。之前只读应用库基线 formal IP=0。
- `allocate_next_address` 现在通过 PostgreSQL 按 address-space、候选范围及可占用状态寻找正式 IP 的首个空位，再检查当前发现、网关和 VIP 占用。旧格式中 `address_inet IS NULL` 的正式 IP 会回退到既有规范化路径。
- 25 次隔离性能样本：IP 分配 P50 449.02 ms、P95 709.55 ms、最大 712.23 ms、P95 SQL 语句数 28；1,000 子 Prefix 候选 P95 18.79 ms、2 SQL。正式 IP 分配 P95 达到脚本 1,000 ms 初始目标。
- 定向回归：分配/网关/当前观察/IPv6 **9 passed**；Pool 边界/IPv6 Pool/八 worker 与 Pool 和接口生成并发 **8 passed**。临时测试库已清理；py_compile、PostgreSQL-only（0违规）和相关文件 `git diff --check` 通过。
- 记录本节时尚未重跑完整 IPAM suite；后续全量 293 passed 结果见文末。生产规模、真实部署延迟尚未验证；没有调用浏览器，没有写应用数据或运行迁移。VRF 暂缓；P4 的 55 条目标映射及 26 组重复裁决仍待人工决定。

### A20 批量确认迟发故障回滚（2026-11-10）

- 既有审计第二项失败与 Pool CheckViolation 用例之外，新加 Prefix UPDATE、IP UPDATE、Pool rowcount 校验及最终 commit 四个故障注入点。
- 官方隔离 PostgreSQL runner：**6 passed, 22 deselected / 164.26s**；每种故障后 Prefix/IP/Pool/address-space 映射与审计事件均未残留。runner 明确未打开配置中的应用库，并删除临时 source DB。
- 两操作者使用同一预览并发确认，注入一方第二条审计写失败；隔离回归 **1 passed / 81.80s**，另一方成功后Prefix/IP/Pool全部映射、仅保留成功事务的两条审计事件。更广交叉故障矩阵仍待做；未调用浏览器，VRF 按要求跳过。

### A18 16-worker 并发分配压力（2026-11-10）

- 16 个 allocator 同时竞争同一个 Prefix，连续执行 3 轮，共 48 次分配；连接锁等待和 SQL 执行分别设为 5 秒/10 秒超时。
- 官方隔离 runner **1 passed / 93.77s**；地址均唯一并精确覆盖网关后连续的48个 host。临时 source/template/test DB 已自动清理，配置中的应用数据库未打开。
- 更长时长、不同 Pool Range 边界和更高同时连接数仍待覆盖；未调用浏览器，VRF 继续暂缓。

### A18 16-worker Pool/接口混合竞态（2026-11-10）

- 16 个 allocator 与 external DHCP Pool 创建、接口 Prefix 生成共18个参与者，同时争同一 address-space 的相交地址/range；设定10秒锁和20秒语句超时。
- 官方隔离 runner **1 passed / 146.83s**，无重复正式 IP 或 Pool 双占用，接口 Prefix 生成成功；临时库已删除，未打开应用库。
- 更长压力与更多Pool边界仍待覆盖；未调用浏览器，VRF继续暂缓。

### 全量 IPAM 隔离回归（2026-11-10）

- 官方 `run_isolated_pytest.py -q backend/tests/ipam`：**293 passed, 0 failed / 1661.09s**，当前全量 IPAM 后端套件通过。
- 此次全量结果包含 A31 修复、A15 分配优化、A18 16-worker三轮并发和 A20 六类迟发失败回滚测试。runner 确认没有打开配置中的应用数据库，并删除临时 source DB。
- A09 另外运行受支持的 Cisco FHRP collection 与不支持平台/命令测试：官方隔离 runner **8 passed, 14 deselected / 94.08s**；unsupported 路径断言不解析凭据、不打开设备会话。无真实设备 I/O。
- 前端 `src/pages/IPVlan` **20 files / 140 tests passed**；全项目 `npm run lint -- --pretty false` 退出码0。
- 只读复核当前 P4 正式台账：60 Prefix、5 mapped、55 unmapped、26 duplicate groups/52 rows、0 `fact_mismatches`；未查历史观察表，没有推断或写入映射目标。P5矩阵更新为当前全量测试结果，36行7列。
- 浏览器保持停用，VRF按要求跳过。该结果不能替代真实设备/部署容量、受限角色 UI、P4人工映射和重复CIDR裁决证据。

### A32 m0320 相邻旧版本升级与失败回滚（2026-11-10）

- 临时 PostgreSQL 库模拟 schema 版本319并重建旧 `uq_ip_addresses_scope_active` 索引；包装 m0320 migration 使其在 `DROP INDEX` 后抛出异常。
- 验证失败事务回滚后索引仍存在、320未入 `schema_migrations`；恢复 migration 后只应用一次，再执行返回0。官方隔离 runner **1 passed / 85.90s**，临时 source DB 已删除。
- 仍需覆盖 m0308–m0319 邻近旧schema升级以及更广的迁移失败位置；未碰应用/生产库，未调用浏览器，VRF迁移跳过。

### A16 IPv6 等价文本边界扩展（2026-11-10）

- 扩展IPv6 canonicalization 用例：同一登记地址的4种大小写、压缩、零填充/展开形式均因等价host被拒；带 `/128` 的host仍被拒。
- 官方隔离 runner **1 passed / 87.74s**；P5 evidence matrix 已写入当前用例链接。其他IPv6 host/mask边界仍待复核；没有浏览器调用或VRF处理。


### A16 IPv6 zone 标识边界（2026-11-10）
- 在正式 host 登记入口拒绝 fe80::1%eth0 与 fe80::1%3，因为接口 zone 不是地址身份的一部分。observations 的解析没有改动。
- 新增回归 test_manual_registration_rejects_ipv6_zone_identifiers；官方隔离 PostgreSQL runner 1 passed / 125.19s。configured application database 未打开，临时 source DB 已清理。
- P5 A16 矩阵已更新：等价 IPv6 文本、CIDR 后缀和 zone ID 校验均有证据。真实设备 IPv6 输入样本未采集，归属 A06/A09；本轮未调用浏览器，未处理 VRF。


### A20 并发 Pool 迟发失败与重试（2026-11-10）
- 两个操作员使用同一批量预览并发确认。确定性同步让失败方完成 Pool 更新后，重试方进入并等待相同地址空间锁，再让失败方抛错回滚。
- 官方隔离 PostgreSQL runner 1 passed / 133.42s；失败方事务回滚，重试方成功，最终 Prefix/IP/Pool 目标空间和两条审计事件一致。runner 未打开应用数据库，临时 source DB 已删除。
- P5 A20 矩阵已加入新用例；不同批次范围和其他故障点交叉组合仍待覆盖。


### A19 幂等写路径矩阵（2026-11-10）
- Prefix、手工 IP、预约、Pool、VIP、DHCP Lease 同键重放/请求体冲突/审计不重复矩阵：隔离 PostgreSQL 1 passed。
- 接口 Prefix generation 重放：隔离 PostgreSQL 1 passed，结果保持一致且正式 Prefix/IP 仅各一条。
- FHRP group update、member remove、VIP detach 重放扩展：隔离 PostgreSQL 2 passed；既有用例覆盖 group create、member add、VIP attach、delete。
- 各 runner 未打开配置的应用数据库，临时 source DB 已删除。P5 A19 evidence matrix 已更新。尚未验证每个 API route 的 Idempotency-Key HTTP header 透传。


### A07/A08 complete-empty 与失败保留矩阵（2026-11-10）
- 复核 ARP/NDP 共用 current endpoint store、FDB 独立 store、FHRP 按 device/protocol 分区的删除条件，确认各自只替换其来源/上下文单元。
- NDP 回归补出此前缺失的两点：同一 unknown context 的 ARP 行不被 NDP complete-empty 清除；NDP failed attempt 保留 Green context 的 prior success row/generation。
- 官方隔离 PostgreSQL runner 1 passed / 88.09s；应用数据库未打开，临时 source DB 删除。A07/A08 存储语义通过；真实采集器状态映射和平台支持仍分别留在 A06/A09。


### A19 API Idempotency-Key 路由与 HTTP 重放（2026-11-10）
- 15条显式 key-enabled 路由的完整性和 Header alias/method/path/规范化值服务转发契约：隔离 runner 1 passed / 117.89s。
- Prefix create TestClient 实测同键重放返回相同 201 body；不同 body 重用同键返回 409：隔离 PostgreSQL 1 passed / 102.89s。
- 结合 service-level 写入矩阵，A19 非 VRF Idempotency-Key 路径已通过。测试 runner 均未打开配置应用数据库并删除临时库。


### A32 m0309 legacy Pool catalog 升级（2026-11-10）
- 模拟 m0309 之前没有 Pool scope/policy 列、索引和约束的 PostgreSQL catalog；旧 Pool 行在升级后保留，映射到 Global Prefix 的 address_space_id 被回填，management_mode/allocation_allowed 继续为 NULL。
- 第二次调用 m0309 后比较完整 ipam_pools columns/constraints/indexes，catalog 完全一致。官方隔离 runner 1 passed / 89.32s；未打开应用库，临时 source DB 已删除。
- 只关闭 m0309 这项非 VRF legacy-catalog/idempotency gap；其余旧 schema、故障回滚与完整链路比较仍待覆盖。


### A32 m0311 旧 schema 注入失败回滚（2026-11-10）
- 在 minimal legacy schema 完整执行 m0311 DDL 后注入异常并 rollback；确认 revision/Pool assignment/FK/idempotency catalog 均恢复迁移前状态，legacy IP/Pool 行未变化。
- 重试 m0311 成功，再执行一次无变化。官方隔离 runner 1 passed / 81.38s，应用数据库未打开，临时 source DB 已删除。
- 配合 m0309 旧 Pool catalog replay，非 VRF 的两个历史迁移点现在有强旧 schema 证据；其余迁移矩阵仍未完成。


### A18 32-worker 五轮 allocator 压力（2026-11-10）
- 32 worker 每轮同时开始，连续5轮，共160笔真实 PostgreSQL事务分配；结果全唯一、地址连续，数据库持久化行数160。
- 官方隔离 runner 1 passed / 87.20s；应用数据库未打开，临时 source DB 已清理。
- 更长时间、混合 Pool/接口并发及其他 Range 边界仍待验证。


### A32 m0313 unknown-context 旧表失败回滚（2026-11-10）
- 旧 current-interface observation + latest-success generation 模拟迁移前 catalog；unknown-context 快照被导入为 unknown，未生成 VRF/routing-context。
- 注入 DDL 与 backfill 后异常，确认表/数据事务回滚；恢复迁移后成功，重复运行 catalog 不变。隔离 runner 1 passed / 81.65s，临时 source DB 清理，应用库未打开。
- 连同 m0309、m0311，当前有三个非 VRF 迁移点的 legacy-catalog 与 retry evidence；其他迁移/完整相邻升级仍待做。


### A32 m0314 unknown-context DDL 失败回滚（2026-11-10）
- 模拟没有 current endpoint state/observation 表的旧 catalog；m0314 完成 DDL 后注入异常，rollback 后两张表均消失。
- 重试后创建表、写入 unknown-context 状态/观察，第三次执行 catalog 不变。隔离 PostgreSQL 1 passed / 79.03s；无 VRF/routing-context，配置应用库未打开。
- 当前已覆盖 m0309/m0311/m0313/m0314 四个非 VRF迁移点，广义相邻版本和失败矩阵仍待补。


### A32 m0316 FDB migration constraint rollback（2026-11-10）
- 模拟 m0316 前 ARP-only source constraint；在迁移完成后注入异常，确认新 FDB 表和 ARP/FDB 约束扩展一起回滚。
- retry 成功，unknown-context FDB state/row 可以写入，重复迁移后 catalog 相同。官方隔离 PostgreSQL 1 passed / 79.09s；没有 VRF/routing-context，临时库删除。
- 这是 A32 的第五个非 VRF legacy-catalog/rollback 点；其余旧迁移矩阵仍未完成。


### A32 m0318 HSRP-only migration rollback（2026-11-10）
- 对 m0318 旧 catalog 注入 post-DDL failure，确认 state/observation 两表事务回滚；retry 创建表并写入 HSRP record，重复执行 catalog 不变。
- 官方隔离 PostgreSQL 1 passed / 82.34s；仅临时设备数据，不包含 VRF 或真实设备 I/O。
- 现有非 VRF迁移失败/目录证据点为 m0309、m0311、m0313、m0314、m0316、m0318，完整相邻升级矩阵仍待做。


### A32 m0310 VIP/Lease legacy catalog rollback（2026-11-10）
- 模拟迁移前 VIP/Lease 表和 legacy 未映射行；注入 m0310 DDL 后异常，新增 scope/link 列、FK、check 和 index 均回滚，旧记录保留。
- retry + repeat 成功；VIP scope 保持 NULL、Lease 为 scope_unknown，未推断路由域。官方隔离 PostgreSQL 1 passed / 83.49s；无 VRF，应用库未打开。
- A32 新增一个非 VRF migration failure/retry 点，广义旧版本矩阵仍待继续。


### A32 m0317 unknown-context NDP 约束回滚（2026-11-10）
- 用隔离旧约束模拟 ARP/FDB source + IPv4-only address family；注入迁移异常后确认回滚恢复旧约束，retry 可写入 IPv6 NDP unknown row，重复执行定义一致。
- 官方隔离 PostgreSQL 1 passed / 80.25s；未涉及 VRF/routing-context，测试库已清理。
- 当前已覆盖 m0309/m0310/m0311/m0313/m0314/m0316/m0317/m0318 八个非 VRF迁移点，完整迁移矩阵仍待做。


### A32 m0319 Global-only catalog rollback（2026-11-10）
- 在旧 catalog 上运行 m0319，完成后注入异常；确认 address-space composite index 与 FHRP groups/members/VIPs 三表整体回滚。
- 重试和重复执行后 catalog 稳定；Global address-space 的 HSRP group 可写。官方隔离 PostgreSQL 1 passed / 86.25s，没有 VRF/address-space-VRF 数据。
- 当前 A32 九个非 VRF迁移点有真实 PostgreSQL 旧 catalog/失败/重试证据，其他版本矩阵仍未完成。


### A20 并发第二个 Prefix IP 更新迟发失败（2026-11-10）
- 两操作员使用同一批预览；失败方已完成第一个 Prefix/IP 与第二个 Prefix 更新，进行第二个 IP 更新后触发异常。重试方先进入并等待相同 scope 锁。
- 失败事务回滚，重试事务提交；Prefix/IP/Pool 与两条 audit 最终一致。官方隔离 PostgreSQL 1 passed / 87.54s；configured app DB 未打开、临时 source 已删除。


### A20 三 Prefix 并发迟发失败（2026-11-10）
- 两操作员并发确认三条 Prefix；失败事务执行到第三个 IP UPDATE 后抛错，重试方已进入同一 scope lock 等待。
- 失败方整体回滚，重试方成功；最终三条 Prefix、IP、Pool 与三条 audit 一致。隔离 PostgreSQL 1 passed / 80.01s；临时 source 清理、应用库未打开。
- A20 现覆盖二/三 Prefix 批次，以及 audit、Pool、第二/第三 IP 故障点的并发重试；更大范围仍待覆盖。


### A32 m0315 unknown raw-key 约束失败回滚（2026-11-10）
- 将 collection state、CMDB interface-address、current endpoint 三个表恢复到旧的 unknown key 空值约束；m0315 约束替换后注入异常并 rollback。
- retry 后三个存储都接受 unknown context 的非空 raw key；重复执行约束稳定。隔离 PostgreSQL 1 passed / 92.09s，没有 VRF 数据，应用库未打开。
- A32 当前已有十个非 VRF迁移点测试；相邻版本链和更广 failure/catalog matrix 仍待完成。


### 2026-11-10 A32 m0309–m0311 startup migration chain
- Isolated PostgreSQL test `test_m0309_m0310_m0311_adjacent_global_upgrade_preserves_legacy_rows`: **1 passed / 78.98s**.
- The test reconstructs the pre-309/310/311 catalog, keeps later migration history applied, executes the application baseline bootstrap followed by the three pending migrations, and verifies schema catalog convergence plus idempotent second startup. Only Global address-space data is used; m0308/m0312 VRF migrations are not run.
- Legacy Prefix/IP/Pool/VIP/Lease data survives. Pool scope is backfilled only from a mapped Global Prefix while old policy stays unset; VIP and lease scopes are not inferred; the lease remains `scope_unknown`.
- The official runner used a temporary loopback PostgreSQL source database, reported the configured application database was not opened, and dropped the temporary source. The current live-facts query separately used a read-only transaction and found 0 formal IP/Pool/VIP/Lease rows with no P4 fact mismatch.


### 2026-11-10 A20 concurrent four/five-prefix rollback
- Deterministic two-operator isolation tests inject failure after the 3rd IP UPDATE in a four-Prefix batch and after the 4th IP UPDATE in a five-Prefix batch.
- Both retries were already waiting on the same address-space scope lock. **2 passed / 85.49s**; each failing transaction rolled back and each retry committed all Prefix/IP/Pool rows and audit events.
- Official runner used temporary loopback PostgreSQL databases, did not open the configured application database, and dropped its temporary source. Full IPAM suite was not rerun after these cases.


### 2026-11-10 A32 non-VRF migration chain m0313-m0319
- `test_m0313_to_m0319_non_vrf_startup_chain_is_catalog_idempotent`: **1 passed / 79.34s** on isolated PostgreSQL.
- The test removes tracking rows for versions 313–319, runs the startup baseline, then applies seven migrations in strict order. m0312 is kept applied and not executed. Catalog comparison covers columns, constraints/validation, and indexes for the interface-address, endpoint/FDB/NDP/FHRP observation, and FHRP relationship tables.
- Repeated migration run applies zero changes. Temporary runner source DB was dropped; the configured application DB was not opened. With the m0309→m0311 chain, A32 non-VRF adjacent startup coverage is complete; VRF migrations remain deferred per scope.

### 2026-11-10 A18 adjacent parent-child Pool ranges
- `test_adjacent_parent_child_pool_ranges_are_allowed`: **1 passed / 78.26s** on isolated PostgreSQL. In one Global address-space, parent range `.20–.29` and child-Prefix range `.30–.39` are adjacent and both accepted.
- The official runner did not open the configured application database and dropped its temporary source. Longer mixed-resource concurrency is still pending.

### 2026-11-10 A20 six-prefix late IP failure
- The concurrent batch late-IP failure test now covers 4 Prefix failing after IP update 3, 5 Prefix after update 4, and 6 Prefix after update 6. **3 passed / 91.20s**.
- A retrying operator waited on the same scope lock; each failing transaction rolled back all Prefix/IP/Pool/audit changes, then the retry committed the full batch. The isolated runner did not open the configured application database and dropped its temporary source.
- Batches above six and other commit/resource failure combinations remain untested; the full IPAM suite was not rerun after these additions.

### 2026-11-10 full isolated IPAM regression after P5 additions
- Ran `.venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam`: **320 passed / 1852.41s**.
- This full run includes the adjacent Pool range boundary, concurrent four/five/six-Prefix late IP failure/retry cases, and both non-VRF adjacent migration chains.
- Official runner used a disposable loopback PostgreSQL source, did not open the configured application database, and dropped the source after pytest. No browser/device operations or application ledger writes occurred.

### 2026-11-10 A18 mixed Pool/interface 16 and 32 allocators
- The same-scope race test runs 16 and 32 allocation workers alongside external Pool creation and interface Prefix generation. **2 passed / 86.53s**.
- Allocated IPs remained unique; successful Pool creation never overlapped a formal IP; interface Prefix generation succeeded. The isolated runner did not open the configured application database and dropped the temporary source.
- A longer multi-round mixed-resource run remains outstanding. The full IPAM suite result of 320 passed predates the added 32-worker mixed case.

## 2026-11-10 P4/P5 当前数据核对与全量回归

- P4 mapping/duplicate CSV structural validator: **60 Prefixes, 5 mapped, 55 unmapped, 26 duplicate CIDR groups, 5 partly mapped groups**，无自动推断且未访问数据库。只读 live-facts validator 当前正式账本差异 **0**，只读事务未查询历史观察表。
- 官方隔离 IPAM 全量回归：**323 passed / 3009.78s**；runner 未打开 configured application DB，并删除临时 source。包含A20 8-Prefix第8条IP迟发失败/等待重试及A18 10轮混合回归的最初断言版本。后续只强化A18接口IP归属/无跳过断言，未改生产代码，并单独复跑通过。
- A18 final strengthened test 定向复跑 **1 passed / 106.13s**：32个allocator、外部Pool创建和接口Prefix生成每轮34个参与者，10轮；接口IP位于 allocator 首选地址范围之外，每轮显式断言新Prefix、接口IP归属、无跳过、allocator唯一以及Pool/IP不重叠。
- A20 8-Prefix迟发失败用例定向 **1 passed / 99.30s**；失败事务回滚，waiting retry提交所有Prefix/IP/Pool/audit。
- A23 后端 `ambiguous` 与前端状态不一致已修复；新增A23 no-match/ambiguous手工选择保留、A24 FHRP partial coverage/last-success、A25 Anycast/VRRP冲突表单回归。聚焦 **35 tests / 3 files passed**，完整IPVlan **146 tests / 20 files passed**；`npm run lint -- --pretty false`通过，Vite隔离目录 build **4362 modules**通过。
- `scripts/validate_postgresql_only.py` **0 violations**；相关后端 py_compile、path-scoped `git diff --check` 通过。没有调用浏览器；isolated build 未覆盖仓库 `dist`。
- A09 profile route collector mock-action集成测试：临时 PostgreSQL **1 passed / 109.68s**，覆盖VRF inventory、default/VRF action dispatch及三个context写入route_cache/route_table。真实S6850 collector persistence未运行。
- P4的55条目标地址空间和26组canonical裁决仍待用户填写；浏览器按要求停用，真实生产容量/恢复/DHCP/FHRP设备证据未做；m0308/m0312 VRF migration旧catalog失败重试及IPAM context mapping依旧暂缓。

## 2026-11-11 IP Locator 使用当前 VLAN/FDB 证据

- 对照用户提供的 VLAN 7 页面与本机当前快照：目标 IP `172.16.5.10` 的 ARP 源为 `S6850-5 / Vlan-interface7`，目标 MAC `8e47-5760-0706` 在 VLAN 7 成员端口 `GE1/0/2` 命中，接口描述为 `TO-PC-7`。
- 修正定位上下文，不再把 ARP 的 SVI 显示成主机物理端口；将 `Vlan-interface7` 列为 ARP 来源，并把 MAC 对应的物理接口单独列出。未采到接入模式时只报告 MAC 所在接口/候选，不伪称 Access 端口；保留原本更强的 SNMP 终端证据。
- 路由追踪遇到其他候选设备失败时，唯一已确认端口仍作为部分定位结果；用户错误列表保留设备可读错误，不展示 UUID 形式的内部 `route_failed` 标记。
- 隔离后端目标用例 **2 passed**；前端 `IPLocatorPage.test.tsx` **4 passed**；TypeScript、`py_compile`、`git diff --check` 通过。隔离 runner 确认未打开配置应用数据库并删除临时 source DB。
- 本机浏览器检查了 `/ipam/locate?ip=172.16.5.10`，页面成功显示 `S6850-5 / GE1/0/2`、VLAN 7、`TO-PC-7`、ARP 来源接口 `Vlan-interface7`。本地 5400 前端和 15310 API 已恢复，健康接口返回 healthy/database connected；这不是生产部署或全角色验收。
- P4 两份人工 CSV 仍空白，P5 真实设备/部署/容量及受限角色验收未全部完成；VRF 按要求跳过。交接：[handoff_20261111_0004_01_IPAM_P4-P5与IP定位.md](../../handoff_20261111_0004_01_IPAM_P4-P5与IP定位.md)。


## 2026-11-11 当前数据校正与在线验收

- 本地页面首次复核时，5400/15310 均未监听；从唯一 main 仓库启动 `node scripts/dev-internal.mjs` 后，5400 返回 200，15310 `/api/health` 为 healthy/database connected。开发服务目前保持运行。
- 浏览器复核 `/cmdb/vlans` 的 VLAN 7 明细：当前记录包括网关网段 `172.16.5.0/24`，ARP `172.16.5.10 → 8e47-5760-0706`，FDB 同一 MAC 位于 `GigabitEthernet1/0/2`，接口骨架 `GE1/0/2` 描述为 `TO-PC-7`。IP 定位重新查询成功，显示 VLAN 7、S6850-5、GigabitEthernet1/0/2，`Vlan-interface7` 独立标作 ARP 来源接口；用户指出的数据确实能形成目标终端路径证据。
- Prefix 浏览器页显示：地址空间待确认 54 条、跨站点重复 CIDR 26 组（52 条 Prefix）、已确认复用 0；提示明确区分待裁决与冲突/合法复用。跨站点复用卡片说明已校正为“同一明确地址空间”口径。
- P4 两份 CSV 按当前正式 Prefix/地址空间台账刷新事实列，未读取历史 observation 表、未改 IPAM 台账、未推断目标。当前 60 条 Prefix 中已有映射 6 条、待映射 54 条；26 组重复 CIDR、52 条记录，其中 6 组部分映射。原 CSV 有 1 条事实已过期（`10.200.35.0/30` 在 WH-DC-01 的 Prefix 当前已有 VRF 地址空间 ID）；工作表现已镜像该现存映射。54 条未映射 Prefix 的目标地址空间仍空，26 组 duplicate/canonical 裁决仍待人工决定。
- `scripts/validate_ipam_p4_mapping_review.py` 与只读 `scripts/validate_ipam_p4_live_facts.py` 均通过；live-facts 为 0 mismatch，声明未查历史观察表、未推断目标、只读事务。当前正式 IP、Pool、VIP、DHCP Lease 台账行数均为 0。
- S6850_1 标准 route collector 只读采集已验证：发现 VRF_A/VRF_B；default route 41 条、每个 VRF 8 条，共 57 条、3 张表均成功，缓存写入本机 route_cache/route_table（2026-11-11 00:17:21 +08）。未创建设备上下文映射。Vlan-interface10/20 当时为 down，VRF 路由表没有对应 connected /24。
- 本轮验证：后端 `test_prefix_cross_site_reuse.py` 6 passed；前端 `PrefixManagementTab.test.tsx` 20 passed；`npm run lint`、py_compile、变更文件 diff check 通过；PostgreSQL-only scanner 0 violations。测试用隔离 PostgreSQL；没有修改正式 IPAM 数据。
- 尚未满足“全部完成”：54 条目标地址空间与 26 组重复 CIDR 决策仍待用户工作表输入；VRF mapping/迁移按用户要求跳过；P5 受限角色、真实多厂商端点/FHRP/DHCP、生产容量与备份恢复等外部验收仍未齐。当前仍是中间交接，尚未生成最终 handoff，也未关机。


### 2026-11-11 A20 10-Prefix concurrent late failure and retry
- Official isolated PostgreSQL runner: `.venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_address_spaces.py -k ten-prefix-fails-on-tenth-ip`: **1 passed, 37 deselected / 97.38s**.
- The failing operator injected an error after the tenth IP UPDATE while the retrying operator waited on the same scope lock. The failed transaction left no Prefix/IP/Pool/audit changes; the retry committed all ten Prefixes, ten IPs, Pool mapping, and ten audit rows. Configured application DB was not opened; temporary source DB was dropped.
- A20 now covers through 10 Prefixes; >10 batches and other concurrent commit/resource failure combinations remain. Matrix A33 now uses the current count of 54 unresolved Prefixes.


## 2026-11-11 P5 浏览器只读页面核验

- 使用现有管理员会话只读检查 `/ipam/pools`、`/ipam/dhcp`、`/ipam/endpoints`、`/ipam/vips`、`/ipam/fhrp`。当前分别显示 Pool 0 条、DHCP Lease 0 条、发现终端 IP/MAC-only 观察均 0 条、正式 VIP 0 条、FHRP 正式组 0 组。
- 在地址池页打开新建表单但未保存，确认“外部 DHCP 管理”会禁用“允许本地静态分配”；“禁止范围内逐个登记 IP”和“利用率按范围计入”仍单独可选。取消表单后列表仍为 0 条，没有 IPAM 页面写入。
- 这些空状态证明当前没有可以支撑真实 DHCP/FHRP 及 MAC-only row presentation 的本地业务记录；不证明真实设备未配置这些协议，也不替代外部 DHCP、其他厂商或受限角色验收。P5 矩阵 A06/A12/A13/A24/A25/A27/A29 已记录此边界。
- A02 的批量映射 preview 未触发：当前地址空间目录唯一条目是 VRF，用户要求 VRF 映射先跳过；没有用 VRF 目标作假设，也没有提交映射。


## 2026-11-11 A18 最小前缀 Pool 范围边界
- 新增 `test_pool_range_accepts_minimum_ipv4_ipv6_prefix_boundaries`，覆盖 IPv4 `/31` 两端点、IPv4 `/32` 单点、IPv6 `/127` 两端点、IPv6 `/128` 单点的 Pool 创建及列表回读。
- 官方隔离 PostgreSQL runner 定向结果 **4 passed, 25 deselected / 113.83s**；configured application DB 未打开，临时 source DB 已删除。
- A18 的本地范围边界已扩展；生产规模争用仍未验证。


## 2026-11-11 A20 12/16-Prefix 并发迟发失败与重试
- 扩展 `test_concurrent_batch_confirmation_late_nth_ip_failure_is_atomic_and_retry_wins` 到 12 条第12次与16条第16次 IP UPDATE 故障。
- 定向官方隔离 PostgreSQL runner **2 passed, 38 deselected / 102.21s**。失败事务完整回滚，等待同一 scope lock 的重试者完整提交所有 Prefix/IP/Pool/audit；配置应用库未打开，临时 source DB 删除。
- A20 当前覆盖至16 Prefix；>16批次及其他并发 commit/resource 故障交叉仍未闭合。


## 2026-11-11 A20 批量 API 上限与并发提交失败闭合
- API `ResolvePrefixAddressSpaceBatchRequest.items` 的最大值为 100。当前隔离 PostgreSQL 定向用例通过：100条批次第100次 IP UPDATE 失败/重试 **1 passed / 96.42s**；12/16条批次 **2 passed / 102.21s**；并发 `commit()` 失败后同scope等待者重试 **1 passed / 95.31s**。此前 full IPAM suite 中已覆盖并发 audit/Pool 失败与2/3条迟发IP故障。
- 100条批次失败事务回滚全部 Prefix/IP/Pool/audit；重试事务提交完整100条及关联Pool/audit。commit失败并发测试验证失败提交不残留、等待同一地址空间锁的重试完整胜出。
- 所有新 runner 均未打开 configured application DB，并删除临时 source DB。A20 本地原子性/审计验收覆盖到 API 最大批次与已识别资源故障点；真实部署吞吐仍由 A15 生产容量验收约束。

## 2026-11-11 P4 两条唯一 Prefix 映射验证

- 管理员 /ipam/prefixes 页面最初已选中 54 个待确认 Prefix；清空选择后，仅选择只读核验出的两个唯一 CIDR：10.254.46.0/30 和 172.16.6.0/24。创建并选中 Global-kind 全局地址空间，未选择已有 VRF global。
- 逐项批量预览均为无阻断，正式 IP、Pool、VIP、DHCP 影响均为 0；用户确认框勾选后提交，UI 返回已将 2 个网段映射到 全局地址空间。刷新后的记录显示两条 Global 归属；总体地址空间待确认数从54降到52。没有选择或修改重复 CIDR。
- 当前数据库事实表复核 75 Prefix、23 mapped、52 unmapped、32 重复组/73 行。静态 validator 和 live-facts validator 均成功，fact_mismatches=[]；25 条既有正式 IP 保持原状，Pool/VIP/DHCP 为0。历史 observation 表没有被查询。
- review CSV 已刷新为75 Prefix及32个重复组；重复组按用户要求标记暂缓、canonical留空。UI的跨站点重复统计为26组/61行，CSV中的其余6组/12行属于同站点重复，均未处理。

## 2026-11-11 H3C 当前 Prefix 重复清理

- 本轮仅处理 WH-DC-01 的 9 台 H3C 设备。读取每台设备 current successful interface generation，并实时执行只读 `display ip routing-table`；没有尝试连接 Cisco。
- H3C 当前接口/路由确认 `10.254.*`、`172.16.5.0/24`、`192.168.56.0/24`、`192.168.96.0/24`；全部 9 台 H3C 当前路由表均未出现 `10.200.*`、`10.255.0.1–.6`。删除 29 条 H3C 侧过时/冗余 Prefix（8 条当前路由/接口无证据的 `10.200.*`、15 条与当前 `10.254.*` canonical Prefix 重复的同站点旧行、6 条当前 H3C 接口/路由中不存在的 `10.255.0.1–.6`）；逐条确认没有正式 IP、Pool、VIP、Lease 引用，使用 revision-checked batch service 并写入审计。
- 将 `172.16.5.0/24`、`192.168.56.0/24`、`192.168.96.0/24` 三条 H3C Prefix 映射到 Global。`AC_11` 上 `192.168.56.0/24` 当前处于 Global routing table，且接口无 VPN-instance；新增显式 `cli/global/--` mapping，并让当前候选投影仅在显式 mapping 存在时解析空 key unknown context。候选页预览 `172.16.5.0/24`、`192.168.56.0/24` 均为 `existing`；后者合并 3 个 H3C 当前接口。
- 当前正式台账 46 Prefix、22 mapped、24 unmapped；12 组/24 行重复 CIDR仍包含 Cisco 侧数据，按用户要求未作处理。正式 IP 25 条未变化，Pool/VIP/DHCP Lease 为0。
- P4 CSV刷新到 46 Prefix、12 组。`validate_ipam_p4_mapping_review.py` 与只读 `validate_ipam_p4_live_facts.py` 均通过，`fact_mismatches=[]`，历史 observation 表未查询。`backend/services/ipam_service.py` py_compile 通过；未调用浏览器。
- P4 的 shadow compare/rollback rehearsal 与 P5 外部验收仍未完成。

## R76 2026-11-11 A21 当前正式 IP 台账与 VRF 范围

- 当前只读查询发现正式 IP 台账 25 条、分布在 15 个 VRF-mapped Prefix；其中 19 个 IP 可匹配 current ARP observation，6 个无匹配。部分 IP 在多个来源设备上出现，未据此推断唯一位置。
- 本轮没有读取历史 observation 表、没有修改正式 IP 数据。全部正式 IP 样本均处于 VRF 范围，因此按用户要求不做 VRF 专项浏览器核对；没有创建测试 owner。
- A21 仍待一个获批的非VRF正式 owner 做浏览器/API 登记与当前观察位置对照。P4 唯一 Prefix Global pilot 和重复项暂缓状态不变。
