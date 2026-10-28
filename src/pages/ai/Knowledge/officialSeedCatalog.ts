export type OfficialSeedVendor = 'Huawei' | 'H3C' | 'Cisco' | 'Ruijie';

export interface OfficialSeedCatalogItem {
  id: string;
  vendor: OfficialSeedVendor;
  title: string;
  url: string;
  sourceKind: 'configuration_guide' | 'command_reference' | 'troubleshooting_guide';
  productFamily: string;
  versionScope: { primary: string; compatibility: string };
  language: 'zh-CN' | 'en-US';
  directIngestion: boolean;
}

/**
 * Small, reviewed seed list for the UI. The backend allowlist and robots/
 * terms checks remain authoritative when a batch is submitted.
 */
export const OFFICIAL_SEED_CATALOG_REVISION = 'official-document-source-catalog-2026-08-28';

export const OFFICIAL_SEED_CATALOG: OfficialSeedCatalogItem[] = [
  {
    id: 'huawei-s5700-s6700-ospf-en-existing',
    vendor: 'Huawei',
    title: 'S5700/S6700 OSPF 不同网络类型配置',
    url: 'https://support.huawei.com/enterprise/en/doc/EDOC1100459443/d770f3cd/configuring-ospf-attributes-on-different-types-of-networks',
    sourceKind: 'configuration_guide',
    productFamily: 'S5700/S6700',
    versionScope: { primary: 'document-defined', compatibility: 'S5700/S6700' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'huawei-ce6800-vxlan-bgp-evpn-en-existing',
    vendor: 'Huawei',
    title: 'CE6800 分布式网关 BGP EVPN VXLAN 配置',
    url: 'https://support.huawei.com/enterprise/en/doc/EDOC1100463796/5d103d4d/establishing-vxlan-tunnels-in-bgp-evpn-mode-distributed-vxlan-gateway',
    sourceKind: 'configuration_guide',
    productFamily: 'CE6800',
    versionScope: { primary: 'document-defined', compatibility: 'CE6800' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'h3c-comware7-ospf-en-existing',
    vendor: 'H3C',
    title: 'H3C Comware 7 OSPF 配置',
    url: 'https://www.h3c.com/en/d_201903/1159013_294551_0.htm',
    sourceKind: 'configuration_guide',
    productFamily: 'Comware 7',
    versionScope: { primary: 'document-defined', compatibility: 'CMW710' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'h3c-s9825-s9855-ospf-en-existing',
    vendor: 'H3C',
    title: 'H3C S9825/S9855 OSPF 配置',
    url: 'https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-19994/07/202410/2284787_294551_0.htm',
    sourceKind: 'configuration_guide',
    productFamily: 'S9825/S9855',
    versionScope: { primary: 'document-defined', compatibility: 'S9825/S9855' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'h3c-s6800-s6860-evpn-vxlan-en-existing',
    vendor: 'H3C',
    title: 'H3C S6800/S6860 EVPN VXLAN 配置',
    url: 'https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-18642/19/202404/2105879_294551_0.htm',
    sourceKind: 'configuration_guide',
    productFamily: 'S6800/S6860',
    versionScope: { primary: 'document-defined', compatibility: 'S6800/S6860' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'cisco-c9300-ospf-17-13-en-existing',
    vendor: 'Cisco',
    title: 'Catalyst 9300 IOS XE 17.13 OSPF 配置',
    url: 'https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg/configuring_ospf.html',
    sourceKind: 'configuration_guide',
    productFamily: 'Catalyst 9300',
    versionScope: { primary: 'IOS XE 17.13', compatibility: 'IOS XE 17.13' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'cisco-nexus3000-ospf-en-existing',
    vendor: 'Cisco',
    title: 'Nexus 3000 NX-OS OSPF 配置',
    url: 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus3000/sw/unicast/602_u1_1/l3_nx-os/l3_ospf.html',
    sourceKind: 'configuration_guide',
    productFamily: 'Nexus 3000',
    versionScope: { primary: 'NX-OS 6.0(2)U1(1)', compatibility: 'NX-OS 6.x' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'cisco-nexus9000-ospf-en-existing',
    vendor: 'Cisco',
    title: 'Nexus 9000 NX-OS OSPF 配置',
    url: 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/unicast/configuration/guide/l3_cli_nxos/l3_ospf.html',
    sourceKind: 'configuration_guide',
    productFamily: 'Nexus 9000',
    versionScope: { primary: 'NX-OS 6.x', compatibility: 'NX-OS 9.x' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'cisco-nexus9000-vxlan-9-2x-en-existing',
    vendor: 'Cisco',
    title: 'Nexus 9000 NX-OS 9.2(x) VXLAN BGP EVPN 配置',
    url: 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/92x/vxlan-92x/configuration/guide/b-cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-92x/b_Cisco_Nexus_9000_Series_NX-OS_VXLAN_Configuration_Guide_9x_chapter_0100.html',
    sourceKind: 'configuration_guide',
    productFamily: 'Nexus 9000',
    versionScope: { primary: 'NX-OS 9.2(x)', compatibility: 'NX-OS 9.x' },
    language: 'en-US',
    directIngestion: true,
  },
  {
    id: 'ruijie-internet-deployment-configuration-cn',
    vendor: 'Ruijie',
    title: '锐捷交换机互联网部署配置',
    url: 'https://www.ruijie.com.cn/fw/wt/90122/',
    sourceKind: 'configuration_guide',
    productFamily: 'RGOS-switches',
    versionScope: { primary: 'document-defined', compatibility: 'RGOS-switches' },
    language: 'zh-CN',
    directIngestion: false,
  },
  {
    id: 'ruijie-snmp-configuration-cn',
    vendor: 'Ruijie',
    title: '锐捷交换机 SNMP 配置',
    url: 'https://www.ruijie.com.cn/fw/wt/90882/',
    sourceKind: 'configuration_guide',
    productFamily: 'RGOS-switches',
    versionScope: { primary: 'document-defined', compatibility: 'RGOS-switches' },
    language: 'zh-CN',
    directIngestion: false,
  },
  {
    id: 'ruijie-command-reference-86075-cn',
    vendor: 'Ruijie',
    title: '锐捷 RGOS 命令参考候选文档 86075',
    url: 'https://www.ruijie.com.cn/fw/wd/86075/',
    sourceKind: 'command_reference',
    productFamily: 'RGOS-switches',
    versionScope: { primary: 'document-defined', compatibility: 'RGOS-switches' },
    language: 'zh-CN',
    directIngestion: false,
  },
  {
    id: 'ruijie-layer2-connectivity-troubleshooting-cn',
    vendor: 'Ruijie',
    title: '锐捷二层直连不通故障排查',
    url: 'https://www.ruijie.com.cn/fw/wt/93439/',
    sourceKind: 'troubleshooting_guide',
    productFamily: 'RGOS-switches',
    versionScope: { primary: 'document-defined', compatibility: 'RGOS-switches' },
    language: 'zh-CN',
    directIngestion: false,
  },
];
