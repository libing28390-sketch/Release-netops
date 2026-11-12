# 完成摘要

接口页通知增加 8 秒自动清理和手动关闭；终态采集详情可单独关闭。IP 地址页补齐后端 scope_pending/matched 状态，未知状态不再兜底为 Global；接口采集设备不再误称接入交换机。没有修改后台采集、登记、分配、数据库或部署。

## 实际修改文件
- src/pages/CmdbManagementTab.tsx
- src/pages/CmdbManagementTab.test.tsx
- src/pages/IPVlan/IPAddressTab.tsx
- src/pages/IPVlan/IPAddressTab.edit.test.ts
- 本任务计划与本文；内部页面覆盖记录追加本次范围。

## 原因与实现
- notice 没有清理入口：接口页使用 effect 定时清理，notice 改变/卸载时取消旧定时器；手动关闭无需刷新。失败后的旧任务详情仍保留；详情只在任务终态提供关闭入口。
- IPAddressTab 的 prefix_match_status 类型缺少后端 scope_pending/matched，helper 将所有其他值视为 Global。现显式区分待确认/已匹配/全局/未匹配，缺失值保持待确认。
- interface_cli 中的 device_id/hostname 是接口所属设备，原 helper 却套用 ARP 接入位置文案；现标明“采集设备 / IPAM 未登记”。资产列仍保留正式登记的语义，未把交换机资产冒充终端资产。

## IPAM 重复与红框核查

| 项目 | 当前源码事实 | 判定边界 |
| --- | --- | --- |
| 同 IP 多行 | backend/services/ipam_service.py 的 list_ip_inventory 合并正式 IP、legacy network_endpoints、current ARP/NDP 及接口观察；current 行按来源设备/上下文保留，接口观察另加 | 不等于正式 IP 重复入库；也未形成按地址空间聚合证据的最终呈现 |
| 登记网段 | 正式 IP 通过 subnet_id 关联 prefixes；接口观察投影的 subnet_prefix 为空，接口观察网段由 IP/掩码计算 | “未关联”不能证明没有该网段，更不能证明现场没有路由 |
| 前缀匹配 | 接口观察按 tenant、IP包含、站点和已映射 address_space 筛选候选 | 地址空间未知不得仅据站点/CIDR认定归属 |
| 设备关系 | IP 正式 device_id 为登记分配；ARP 的观察交换机为接入证据；interface_cli 为接口所有者 | 三者不可互相覆盖 |
| 资产关系 | 正式 IP → devices.asset_id → physical_assets | 缺值只表示当前登记链路缺失，不等于没有设备或资产 |

关键源码入口：backend/api/ipam.py:1148；backend/services/ipam_service.py:2733；backend/services/ipam_inventory_scope.py:57；backend/database/migrations/m0314_ipam_current_endpoint_observations.py:128。正式地址有 address-space/IP 活动唯一性，不能用裸 IP 将多来源观察直接删除。

无凭据的本机 API 查询返回 401，浏览器也显示登录页，因此本次未读取截图目标 IP 的实际行 ID/来源上下文。截图可证明重复展示，不能单独证明同空间重复登记。本次未绕过鉴权、未删除观察或调用真实设备。

## VRF 与 NetBox 对标结论

CMDB VRF 人工创建；vrf_name 必填，RD/描述可选。create_vrf 同事务创建对应 VRF 地址空间。接口采集/路由发现不自动完成 CMDB 目录与设备上下文映射。Global 是显式地址空间，不需创建名为 global/default 的假 VRF；Prefix 选 Global 空间，设备已识别的本地上下文再映射到它。未知/空上下文继续待确认。

NetBox 官方规则：无 VRF 的登记对象属于 Global；站点是管理范围；IP 可分配给设备/VM接口或FHRP组。当前 Nexora 额外采用显式 address_space 身份，仍需完成旧 Prefix 归属、设备上下文、台账分配与观测对账的闭环。不能将已有底座和单元测试称为整体对标完成。

- https://netbox.readthedocs.io/en/stable/models/ipam/vrf/
- https://netbox.readthedocs.io/en/stable/models/ipam/prefix/
- https://netbox.readthedocs.io/en/stable/models/ipam/ipaddress/

前期 P4 记录的未映射/重复 CIDR 数字是历史核查结果，本次没有重查业务库，不将其作为实时事实。额外发现 VRF 改名未同步地址空间名称，删除因自动生成的映射受阻；本次仅记录，不扩大为数据库维护变更。

## 验证命令与结果
- npm run test:frontend -- --run src/pages/CmdbManagementTab.test.tsx src/components/CmdbInterfaceCollectionProgress.test.tsx：2 files / 22 tests passed；覆盖超时、手动关闭、保留详情、再次启动失败。
- npm run test:frontend -- --run src/pages/IPVlan/IPAddressTab.edit.test.ts src/pages/IPVlan/IPAddressTab.table.test.tsx src/pages/IPVlan/ipAddressTablePresentation.test.ts：实际匹配 2 files / 19 tests passed（仓库不存在 table.test.tsx）；覆盖状态及设备关系文案。
- npm run lint：exit 0；在 IP 页面补丁前启动。最终 src 全部 .ts/.tsx 另以继承原 tsconfig 的 node_modules/.cache/tsconfig-cmdb-ipam-20261111.json 验证：npx tsc --project node_modules/.cache/tsconfig-cmdb-ipam-20261111.json --noEmit --pretty false，exit 0。
- npx vite build --outDir .codex-build-validation-cmdb-notice-20261111：最终 4362 modules passed / 1m21s，隔离输出未覆盖 dist。
- git diff --check -- src/pages/CmdbManagementTab.tsx src/pages/CmdbManagementTab.test.tsx src/pages/IPVlan/IPAddressTab.tsx src/pages/IPVlan/IPAddressTab.edit.test.ts：通过（仅 LF/CRLF 标准化提示）。

## 未验证项、风险与后续范围
未登录验收运行中的完整采集交互，未执行真实设备采集，未写业务数据库，未提交/推送/部署。原 dist 和登录页用户改动保留。后续整改应验收：正式台账与观察有明确入口、观察按已确认地址空间聚合且可展开来源、Prefix 同空间归属、IP分配接口与设备资产链、FHRP共享地址、Global与未知区分、完整端到端流程。不得用隐藏重复行取代这些关系。
