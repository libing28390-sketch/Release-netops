# 官方厂商文档来源清单

版本：2026-08-28
权威机器清单：[official-document-source-catalog.yaml](./official-document-source-catalog.yaml)

## 结论

本清单覆盖华为、H3C、锐捷和 Cisco 的配置、命令参考、产品入口与故障排查来源。它是“候选来源目录”，不会自动开启采集，也不会修改 PostgreSQL。运行时是否允许采集，仍由 CAT-001 精确来源白名单、CAT-002 来源类型、CAT-003 清洗规则和 CAT-004 分块规则共同决定。

当前知识库共有 252 篇文档，其中锐捷为 0 篇，故首批应优先补齐锐捷 RGOS；H3C 现有 35 篇，但主要缺少系统化排障材料；华为和 Cisco 已有一定配置资料，下一步重点是版本化配置指南和排障文档。

## 清单汇总

| 厂商 | 来源数 | 已在 PG 注册 | 配置/命令候选 | 排障候选 | 导航入口 | 首批优先级 |
|---|---:|---:|---:|---:|---:|---|
| Huawei | 11 | 3 | 4 | 3 | 1 | P1；排障 P0 |
| H3C | 10 | 3 | 2 | 4 | 1 | P0 |
| Ruijie | 14 | 0 | 4 | 4 | 6 | P0 |
| Cisco | 13 | 4 | 2 | 3 | 4 | P1；排障 P0 |
| 合计 | 48 | 10 | 12 | 14 | 12 | — |

> “已在 PG 注册”表示该 URL 已存在于 `kb_source_registry` 且为 active/valid；不能再次创建来源记录。导航入口只用于发现具体文档，不直接分块或向量化。

## 在线抽查结果

2026-08-28 对代表性页面进行了只读抽查：H3C 文档中心与排障手册、锐捷文档中心与二层排障案例、Cisco Catalyst 技术说明索引与 Nexus 9.2(x) 排障指南均可访问。华为中文支持站对通用抓取客户端返回 403 或超时，因此相关中文页面继续保持禁用，必须先复核登录、Cookie、访问条款和安全客户端策略。该抽查不是 48 个 URL 的批量采集验收。

## Huawei

官方主机：`support.huawei.com`、`info.support.huawei.com`

| ID | 文档/入口 | 类型 | 版本/产品 | 状态 |
|---|---|---|---|---|
| `huawei-ce16800-product-center-zh` | [CE16800 产品支持与文档中心](https://support.huawei.com/enterprise/zh/data-center-switches/ce16800-pid-252837173) | 导航 | CE16800 | 仅发现 |
| `huawei-s5700-s6700-ospf-en-existing` | [配置不同网络类型的 OSPF 属性](https://support.huawei.com/enterprise/en/doc/EDOC1100459443/d770f3cd/configuring-ospf-attributes-on-different-types-of-networks) | 配置 | S5700/S6700 | PG 已启用 |
| `huawei-s5700-s6700-routing-en-existing` | [静态路由与动态路由](https://support.huawei.com/enterprise/en/doc/EDOC1100333453/ac09508/static-routes-and-dynamic-routes) | 配置 | S5700/S6700 | PG 已启用 |
| `huawei-ce6800-vxlan-bgp-evpn-en-existing` | [BGP EVPN 分布式 VXLAN 网关](https://support.huawei.com/enterprise/en/doc/EDOC1100463796/5d103d4d/establishing-vxlan-tunnels-in-bgp-evpn-mode-distributed-vxlan-gateway) | 配置 | CE6800 | PG 已启用 |
| `huawei-s5700-s6700-ethernet-v200r024c10-zh` | [MUX VLAN 配置示例](https://support.huawei.com/enterprise/zh/doc/EDOC1100459455/a3558870/example-for-configuring-mux-vlan-on-an-aggregation-device) | 配置 | V200R024C10 | 待白名单 |
| `huawei-s5700-s6700-ospf-v600-zh` | [OSPF 配置](https://support.huawei.com/enterprise/zh/doc/EDOC1100278276/c3f6a316) | 配置 | V600 | 待白名单 |
| `huawei-s5700-s6700-vrrp-v200-zh` | [VRRP 可靠性配置](https://info.support.huawei.com/enterprise/zh/doc/EDOC1100459453/99234d3a) | 配置 | V200 | 待白名单 |
| `huawei-s5700-s6700-qinq-command-v200-zh` | [QinQ 命令参考](https://info.support.huawei.com/enterprise/zh/doc/EDOC1100459421/ddc3d496) | 命令 | V200 | 待白名单 |
| `huawei-ospf-network-flap-troubleshooting-zh` | [OSPF 网络频繁震荡排查](https://info.support.huawei.com/enterprise/zh/doc/EDOC1100305532/b79910c8) | 排障 | 路由交换 | 待类型+白名单 |
| `huawei-bgp-traffic-interruption-troubleshooting-zh` | [BGP 公网流量中断排查](https://info.support.huawei.com/enterprise/zh/doc/EDOC1000052631/25fd81d3) | 排障 | 路由交换 | 待类型+白名单 |
| `huawei-s-series-board-reset-troubleshooting-zh` | [S 系列单板复位排查](https://info.support.huawei.com/enterprise/zh/doc/EDOC1000075592/4079ef29) | 排障 | S 系列 | 待类型+白名单 |

## H3C

官方主机：`www.h3c.com`

| ID | 文档/入口 | 类型 | 版本/产品 | 状态 |
|---|---|---|---|---|
| `h3c-document-center-cn` | [H3C 文档中心](https://www.h3c.com/cn/Service/Document_Software/Document_Center/) | 导航 | 全产品 | 仅发现 |
| `h3c-comware7-ospf-en-existing` | [Comware 7 OSPF 配置](https://www.h3c.com/en/d_201903/1159013_294551_0.htm) | 配置 | Comware 7 | PG 已启用 |
| `h3c-s9825-s9855-ospf-en-existing` | [S9825/S9855 OSPF 配置](https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-19994/07/202410/2284787_294551_0.htm) | 配置 | S9825/S9855 | PG 已启用 |
| `h3c-s6800-s6860-evpn-vxlan-en-existing` | [S6800/S6860 EVPN VXLAN 配置](https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-18642/19/202404/2105879_294551_0.htm) | 配置 | S6800/S6860 | PG 已启用 |
| `h3c-box-switch-typical-config-examples-cn` | [盒式交换机典型配置举例](https://www.h3c.com/cn/Service/Document_Software/Document_Center/Home/Switches/00-Public/Configure/Typical_Configuration_Example/H3C_CE_R6010Pxx_R8307Pxx-25482/00/) | 配置 | R6010Pxx/R8307Pxx | 待白名单 |
| `h3c-config-file-management-command-cn` | [配置文件管理命令参考](https://www.h3c.com/cn/d_202401/2035540_30005_0.htm) | 命令 | Comware | 待白名单 |
| `h3c-switch-general-troubleshooting-2025-cn` | [交换机通用故障排查宝典](https://www.h3c.com/cn/Service/Document_Software/Document_Center/Home/Switches/00-Public/Maintenance/Maintenance_Treasure/H3C-WHBD-Long/02/) | 排障 | 交换机 | 待类型+白名单 |
| `h3c-feature-troubleshooting-2026-cn` | [ARP/DHCP/OSPF/BGP 等特性排障](https://www.h3c.com/cn/d_202603/2776299_30005_0.htm) | 排障 | Comware | 待类型+白名单 |
| `h3c-s6300-troubleshooting-cn` | [S6300 故障处理手册](https://www.h3c.com/cn/Service/Document_Software/Document_Center/Switches/Catalog/S6300/S6300/Maintenance/Troubleshooting/H3C_S6300_TG-6W100/) | 排障 | S6300 | 待类型+白名单 |
| `h3c-s12500g-af-troubleshooting-cn` | [S12500G-AF 故障处理手册](https://www.h3c.com/cn/Service/Document_Software/Document_Center/Switches/Catalog/S12500/S12500G-AF/Maintenance/Troubleshooting/H3C_S12500G-AF_TG-R7595-6W100/) | 排障 | S12500G-AF | 待类型+白名单 |

## Ruijie

官方主机：`www.ruijie.com.cn`

| ID | 文档/入口 | 类型 | 版本/产品 | 状态 |
|---|---|---|---|---|
| `ruijie-document-center-cn` | [锐捷文档中心](https://www.ruijie.com.cn/fw/wd/) | 导航 | 全产品 | 仅发现 |
| `ruijie-support-faq-cn` | [常见问题与故障排查中心](https://www.ruijie.com.cn/fw/wt/) | 导航 | 全产品 | 仅发现 |
| `ruijie-rg-s7600-doc-center-cn` | [RG-S7600 文档中心](https://www.ruijie.com.cn/fw/wd-cp-7600/) | 导航 | RG-S7600 | 仅发现 |
| `ruijie-rg-s5600-doc-center-cn` | [RG-S5600 文档中心](https://www.ruijie.com.cn/fw/wd-cp-s5600/) | 导航 | RG-S5600 | 仅发现 |
| `ruijie-rg-s6220-doc-center-cn` | [RG-S6220 文档中心](https://www.ruijie.com.cn/fw/wd-cp-6220/) | 导航 | RG-S6220 | 仅发现 |
| `ruijie-rg-s4900-doc-center-cn` | [RG-S4900 文档中心](https://www.ruijie.com.cn/fw/wd-cp-4900/) | 导航 | RG-S4900 | 仅发现 |
| `ruijie-internet-deployment-configuration-cn` | [交换机互联网部署配置](https://www.ruijie.com.cn/fw/wt/90122/) | 配置 | RGOS | 待白名单 |
| `ruijie-snmp-configuration-cn` | [交换机 SNMP 配置](https://www.ruijie.com.cn/fw/wt/90882/) | 配置 | RGOS | 待白名单 |
| `ruijie-command-reference-86075-cn` | [RGOS 命令参考 86075](https://www.ruijie.com.cn/fw/wd/86075/) | 命令 | RGOS | 待白名单 |
| `ruijie-command-reference-88538-cn` | [RGOS 命令参考 88538](https://www.ruijie.com.cn/fw/wd/88538/) | 命令 | RGOS | 待白名单 |
| `ruijie-mtu-large-packet-troubleshooting-cn` | [MTU 与大包 Ping 异常排查](https://www.ruijie.com.cn/fw/wt/93440/) | 排障 | RGOS | 待类型+白名单 |
| `ruijie-layer2-connectivity-troubleshooting-cn` | [二层直连不通排查](https://www.ruijie.com.cn/fw/wt/93439/) | 排障 | RGOS | 待类型+白名单 |
| `ruijie-ospf-neighbor-attempt-troubleshooting-cn` | [OSPF 邻居 Attempt 状态排查](https://www.ruijie.com.cn/fw/wt/32970/) | 排障 | RGOS | 待类型+白名单 |
| `ruijie-port-packet-drop-troubleshooting-cn` | [端口丢包排查](https://www.ruijie.com.cn/fw/wt/18792) | 排障 | RGOS | 待类型+白名单 |

## Cisco

官方主机：`www.cisco.com`

| ID | 文档/入口 | 类型 | 版本/产品 | 状态 |
|---|---|---|---|---|
| `cisco-c9300-series-support-zh` | [Catalyst 9300 支持中心](https://www.cisco.com/c/zh_cn/support/switches/catalyst-9300-series-switches/series.html) | 导航 | C9300 | 仅发现 |
| `cisco-c9300-config-guide-index-zh` | [C9300 配置指南索引](https://www.cisco.com/c/zh_cn/support/switches/catalyst-9300-series-switches/products-installation-and-configuration-guides-list.html) | 导航 | C9300 | 仅发现 |
| `cisco-c9300-tech-notes-index-zh` | [C9300 技术说明索引](https://www.cisco.com/c/zh_cn/support/switches/catalyst-9300-series-switches/products-tech-notes-list.html) | 导航 | C9300 | 仅发现 |
| `cisco-c9300-ospf-17-13-en-existing` | [IOS XE 17.13 OSPF 配置](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg/configuring_ospf.html) | 配置 | C9300 | PG 已启用 |
| `cisco-nexus3000-ospf-en-existing` | [Nexus 3000 OSPF 配置](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus3000/sw/unicast/602_u1_1/l3_nx-os/l3_ospf.html) | 配置 | N3K | PG 已启用 |
| `cisco-nexus9000-ospf-en-existing` | [Nexus 9000 OSPF 配置](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/unicast/configuration/guide/l3_cli_nxos/l3_ospf.html) | 配置 | N9K | PG 已启用 |
| `cisco-nexus9000-vxlan-9-2x-en-existing` | [Nexus 9000 VXLAN BGP EVPN 配置](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/92x/vxlan-92x/configuration/guide/b-cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-92x/b_Cisco_Nexus_9000_Series_NX-OS_VXLAN_Configuration_Guide_9x_chapter_0100.html) | 配置 | N9K 9.2(x) | PG 已启用 |
| `cisco-c9300-system-management-17-18-pdf-en` | [IOS XE 17.18 系统管理配置指南](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/configuration_guide/sys_mgmt/b_1718_sys_mgmt_9300_cg.pdf) | 配置 | C9300 | 待注册审核 |
| `cisco-c9300-system-management-command-17-18-en` | [IOS XE 17.18 系统管理命令参考](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/command_reference/b_1718_9300_cr/system_management_commands.html) | 命令 | C9300 | 待注册审核 |
| `cisco-c9300-software-troubleshooting-17-13-en` | [IOS XE 17.13 软件配置排障](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/sys_mgmt/b_1713_sys_mgmt_9300_cg/troubleshooting_the_software_configuration.html) | 排障 | C9300 | 待类型+注册 |
| `cisco-catalyst9000-latency-packet-loss-zh` | [Catalyst 9000 延迟与丢包排障](https://www.cisco.com/c/zh_cn/support/docs/switches/catalyst-9300-series-switches/225617-troubleshooting-network-latency-and.html) | 排障 | C9K | 待类型+白名单 |
| `cisco-nexus9000-troubleshooting-index-en` | [Nexus 9000 排障指南索引](https://www.cisco.com/c/en/us/support/switches/nexus-9000-series-switches/products-troubleshooting-guides-list.html) | 导航 | N9K | 仅发现 |
| `cisco-nexus9000-troubleshooting-9-2x-en` | [Nexus 9000 NX-OS 9.2(x) 排障指南](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/92x/troubleshooting/guide/b-cisco-nexus-9000-nx-os-troubleshooting-guide-92x/b-cisco-nexus-9000-nx-os-troubleshooting-guide-92x_chapter_010.html) | 排障 | N9K 9.2(x) | 待类型+注册 |

## 审核和采集顺序

1. 先扩展 CAT-002：增加 `troubleshooting_guide`，定义必填元数据和分块规则。
2. 以具体 URL 或最小路径前缀扩展 CAT-001，不允许放行整个厂商域名。
3. 第一批选择锐捷 4 篇配置/命令、4 篇排障，以及 H3C 2 篇通用排障；先做条款与可访问性检查。
4. 小批量进入隔离区，完成正文清洗、版本标注、去重和召回测试后再扩大范围。
5. 对已经在 PG 注册的 10 个 URL 只做健康复核，不重复创建来源记录。

## 明确不做的事情

- 不从论坛、博客、网盘、镜像站或培训机构采集正文。
- 不从门户页递归抓取整个站点。
- 不把中文机器翻译结果覆盖英文权威原文。
- 不因本清单存在就绕过来源白名单、版权条款、隔离区或质量门禁。
