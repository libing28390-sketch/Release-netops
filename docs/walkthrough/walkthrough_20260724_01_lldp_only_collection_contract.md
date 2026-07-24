# LLDP-only 邻居采集契约落地

## 目标

为新网段/存量网段自动发现提供稳定的邻居证据入口：所有厂商统一使用 LLDP，复用已验证的 Automation Playbook/TextFSM 解析结果；思科路径不得发送 CDP。

## 已完成

- 增加 `backend/services/neighbor_collection_contract.py`，冻结 LLDP 场景、厂商命令白名单、统一结果字段和采集状态。
- 在 operational data 和 topology 的命令解析、SSH 发送前分别做校验，命令中出现 CDP 会直接失败，不进入设备会话。
- Quick Query 移除 Cisco 的 CDP 命令拼接；诊断逐跳路径在 LLDP 禁用时明确记录状态，不再 CDP fallback。
- 拓扑重建仅使用 LLDP 观测；历史 CDP 链路被标记为 stale，不再进入活动拓扑。
- 拓扑观测增加 `first_seen_at`、`last_seen_at`、`miss_count`、`is_active`，成功采集时按连续 3 次缺失老化；采集失败不删除上一份有效证据。
- 新增 `m0031_lldp_collection_contract`，并同步更新 PostgreSQL 旧库的基线字段兼容处理。
- 建立入口盘点文档：`docs/architecture/lldp_collection_call_inventory.md`。
- 增加 `read_only_collection_adapter.py`，统一接口、VLAN、路由、LLDP、ARP、MAC 的只读批次封装。
- 增加 `prefix_discovery_service.py`：按租户/站点/VRF/地址族/前缀聚合证据；无充分证据的网段保持 `unclassified`，人工网络类型不会被自动规则覆盖。
- 增加前缀观察和分类历史表；全量成功扫描后连续 3 次未出现的自动前缀才会老化，部分设备失败时不进行老化。
- 同一租户下同一前缀跨站点出现时保留站点隔离，并写入 `cross_site_prefix` 冲突证据；分类变化写入历史表。
- 终端定位的上联判断同时参考 LLDP 链路、接口 trunk/access 模式、聚合口特征和 MAC 数量，减少把接入口误判为上联口。

## 本轮优化

- 前缀候选增加 `mixed_network` 标记：同一前缀同时出现 SVI/IRB、Loopback、P2P、Management 等角色时保留候选，但降低自动分类置信度，交由人工复核。
- VIP 不改变前缀的主 `network_type`，而是以地址级 `address_roles_json` 记录 `service_vip`、VIP 类型和状态，避免把 VIP 地址误判成服务器网段。
- DHCP 租约同样写入 `address_roles_json`，保留地址、MAC、主机名、DHCP Server 和租约状态；新增 `m0033_dhcp_lease_tenant_scope` 为租约补齐租户范围，历史记录默认归属 `tenant-default`。
- 新增 `/api/ipam/prefixes/classification-summary` 汇总自动、人工、未分类、混合角色、跨站点冲突和老化数量；前缀管理页展示这些待处理项。
- 前缀管理页对自动分类值做显式映射，`unclassified` 显示为“待确认”，不会因为前端缺少枚举而回退显示成“服务器网”。
- 对 `Loopback/Lo` 接口增加专用主机前缀规则：采集结果只有地址、没有掩码时，IPv4 生成 `/32`、IPv6 生成 `/128`；普通接口仍要求真实掩码或前缀长度。
- 接口采集成功后立即触发前缀候选 upsert；后续完整只读扫描继续对同一前缀补充 Connected Route、LLDP、ARP、MAC 等证据，避免接口表与 Prefix 表脱节。
- 自动发现仍以 Automation Playbook/TextFSM 的只读结果为唯一采集入口；思科邻居采集保持 LLDP-only，禁止 CDP。
- ARP 仅用于把已发现的前缀补充为地址证据，MAC 表仅按已知 VLAN 关联到前缀；两者都不会在缺少掩码时凭空生成前缀。观察到的 VLAN/VRF 会随前缀快照持久化。

## 验证

- `pytest backend/tests -q`：175 passed，25 subtests passed。
- `npm run lint`：通过。
- `npm run build`：通过；仅保留既有 chunk size warning。

## 下一步

继续把接口、VLAN、VRF、Connected Route、ARP/MAC/DHCP 证据接入同一采集批次，并在此契约之上实现新/存量网段 upsert、证据快照、人工覆盖和分类置信度。
