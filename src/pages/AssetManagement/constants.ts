import { Server, Router } from 'lucide-react';

export const STATUSES = [
  { value: 'active',         label: { zh: '在用', en: 'In Use' },        dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700', text: 'text-emerald-600' },
  { value: 'inactive',       label: { zh: '闲置', en: 'Idle' },          dot: 'bg-sky-400',     badge: 'bg-sky-50 text-sky-600',         text: 'text-sky-500' },
  { value: 'in_storage',     label: { zh: '库存中', en: 'In Storage' },  dot: 'bg-blue-400',    badge: 'bg-blue-50 text-blue-600',       text: 'text-blue-500' },
  { value: 'maintenance',    label: { zh: '维护中', en: 'Maintenance' }, dot: 'bg-amber-500',   badge: 'bg-amber-50 text-amber-700',     text: 'text-amber-600' },
  { value: 'decommissioned', label: { zh: '已退役', en: 'Retired' },     dot: 'bg-slate-400',   badge: 'bg-slate-100 text-slate-500',    text: 'text-slate-400' },
] as const;

export const TYPES = [
  { value: 'server',         label: { zh: '服务器', en: 'Server' },    icon: Server },
  { value: 'network_device', label: { zh: '网络设备', en: 'Network' }, icon: Router },
] as const;

export const LIFECYCLE_STATUSES = [
  { value: 'staging',        label: { zh: '待投产', en: 'Staging' } },
  { value: 'production',     label: { zh: '已投产', en: 'Production' } },
  { value: 'maintenance',    label: { zh: '维护中', en: 'Maintenance' } },
  { value: 'decommissioned', label: { zh: '已退役', en: 'Decommissioned' } },
] as const;

export const EMPTY_FORM = {
  asset_type: 'server', asset_tag: '', serial_number: '', vendor: '', model: '',
  hostname: '', site_id: '', rack: '', rack_unit: '', u_height: '1', planned_start_u: '', management_ip: '',
  business_ip: '', device_role: '', vlan: '', uplink_switch: '', uplink_port: '',
  status: 'active', lifecycle_status: 'staging', asset_origin: 'new', takeover_exempt_reason: '', purchase_date: '', warranty_expiry: '', department: '', notes: '',
  platform: '', connection_method: 'ssh', 
  username: '', password: '',
  normal_username: '', normal_password: '',
  admin_username: '', admin_password: '',
  enable_password: '',   
  auth_model: 'dual',
  snmp_community: '', snmp_community_set: false, snmp_port: '161',
  management_port: '22',
  device_category: '',
  function: '',
  zone: 'Unknown',
  power_watts: '',       
  credential_id: '',
  admin_credential_id: '',
  snmp_credential_id: '',
  tag_ids: [] as string[],
  web_profiles: [] as Array<{
    id?: string;
    profile_name: string;
    scheme: 'http' | 'https';
    port: string;
    path: string;
    enabled: boolean;
    credential_mode?: 'inherit_asset' | 'independent';
    normal_username?: string;
    normal_password?: string;
    admin_username?: string;
    admin_password?: string;
    credential_id?: string;
    admin_credential_id?: string;
  }>,
};

export {
  NETWORK_TOPOLOGY_ROLE_OPTIONS,
  NETWORK_TOPOLOGY_ROLE_VALUES,
  topologyRoleLabel,
} from '../../domain/topologyRoles';

export const TOPOLOGY_FUNCTION_OPTIONS = [
  { value: 'Internet Edge', label: { zh: '互联网边界', en: 'Internet Edge' } },
  { value: 'Campus Core', label: { zh: '园区核心', en: 'Campus Core' } },
  { value: 'Business Aggregation', label: { zh: '业务汇聚', en: 'Business Aggregation' } },
  { value: 'Terminal Access', label: { zh: '终端接入', en: 'Terminal Access' } },
  { value: 'DMZ Security', label: { zh: 'DMZ 安全', en: 'DMZ Security' } },
  { value: 'Server Access', label: { zh: '服务器接入', en: 'Server Access' } },
  { value: 'Business Application', label: { zh: '业务应用', en: 'Business Application' } },
  { value: 'OOB Management', label: { zh: '带外管理', en: 'OOB Management' } },
  { value: 'Wireless Controller', label: { zh: '无线控制', en: 'Wireless Controller' } },
  { value: 'WAN Edge', label: { zh: 'WAN 边界', en: 'WAN Edge' } },
  { value: 'Site Interconnect', label: { zh: '站点互联', en: 'Site Interconnect' } },
  { value: 'Other', label: { zh: '其他', en: 'Other' } },
  { value: 'Unknown', label: { zh: '未知', en: 'Unknown' } },
] as const;

export const TOPOLOGY_ZONE_OPTIONS = [
  { value: 'Production', label: { zh: '生产区', en: 'Production' } },
  { value: 'Management', label: { zh: '管理区', en: 'Management' } },
  { value: 'OOB', label: { zh: '带外管理区', en: 'OOB' } },
  { value: 'LAN', label: { zh: '内网区', en: 'LAN' } },
  { value: 'WAN', label: { zh: '广域网区', en: 'WAN' } },
  { value: 'DMZ', label: { zh: 'DMZ 区', en: 'DMZ' } },
  { value: 'Internet', label: { zh: '互联网区', en: 'Internet' } },
  { value: 'Wireless', label: { zh: '无线区', en: 'Wireless' } },
  { value: 'Server', label: { zh: '服务器区', en: 'Server' } },
  { value: 'Office', label: { zh: '办公区', en: 'Office' } },
  { value: 'Other', label: { zh: '其他', en: 'Other' } },
  { value: 'Unknown', label: { zh: '未知', en: 'Unknown' } },
] as const;

/**
 * Canonical asset vendor catalog.  Keep this list broader than the current
 * driver registry: selecting a vendor records the asset identity, while the
 * concrete automation/parser support is still determined by the platform
 * profile selected below it.
 */
export const NETWORK_VENDOR_NAMES = [
  'Cisco', 'Huawei', 'H3C', 'Arista', 'Juniper', 'Ruijie', 'ZTE', 'Raisecom', 'Maipu',
  'DPtech', 'DCN', 'FiberHome', 'Nokia', 'Aruba', 'Extreme Networks',
  'Ruckus', 'MikroTik', 'Ubiquiti', 'D-Link', 'TP-Link', 'Dell', 'Brocade',
  'Ciena', 'Alcatel-Lucent Enterprise', 'Allied Telesis', 'Edgecore',
] as const;

export const SECURITY_VENDOR_NAMES = [
  'Fortinet', 'Palo Alto', 'Hillstone', 'Sangfor', 'Check Point', 'Sophos',
  'SonicWall', 'WatchGuard', 'F5', 'A10 Networks', 'Barracuda', 'Venustech',
  'NSFOCUS', 'Topsec', 'Qi An Xin',
] as const;

export const NETWORK_VENDOR_GROUPS = [
  { key: 'network', labelZh: '网络设备厂商', labelEn: 'Network vendors', vendors: NETWORK_VENDOR_NAMES },
  { key: 'security', labelZh: '网络安全厂商', labelEn: 'Security vendors', vendors: SECURITY_VENDOR_NAMES },
] as const;

export const ALL_VENDOR_NAMES = [...NETWORK_VENDOR_NAMES, ...SECURITY_VENDOR_NAMES] as const;

/**
 * Import aliases keep the human-friendly values used in Excel templates
 * compatible with the canonical vendor names stored by the asset API.
 */
export const VENDOR_IMPORT_ALIASES: Record<string, string> = {
  '思科': 'Cisco',
  '华为': 'Huawei',
  '华三': 'H3C',
  '阿里斯塔': 'Arista',
  '瞻博': 'Juniper',
  '锐捷': 'Ruijie',
  '中兴': 'ZTE',
  '瑞斯康达': 'Raisecom',
  '瑞斯康达通信': 'Raisecom',
  '迈普': 'Maipu',
  '迪普': 'DPtech',
  '神州数码': 'DCN',
  '烽火': 'FiberHome',
  '诺基亚': 'Nokia',
  '极进': 'Extreme Networks',
  '山石': 'Hillstone',
  '深信服': 'Sangfor',
  '检查点': 'Check Point',
  '奇安信': 'Qi An Xin',
  '天融信': 'Topsec',
  '绿盟': 'NSFOCUS',
  '启明星辰': 'Venustech',
  '飞塔': 'Fortinet',
  '帕洛阿尔托': 'Palo Alto',
};

export const VENDOR_PLATFORMS: Record<string, { value: string; label: string }[]> = {
  Cisco:      [{ value: 'cisco_ios', label: 'Cisco IOS' }, { value: 'cisco_nxos', label: 'Cisco NX-OS' }, { value: 'cisco_xe', label: 'Cisco IOS-XE' }, { value: 'cisco_iosxr', label: 'Cisco IOS-XR' }, { value: 'cisco_asa', label: 'Cisco ASA/Firepower' }],
  Huawei:     [{ value: 'huawei_vrp', label: 'Huawei VRPv5' }, { value: 'huawei_vrpv8', label: 'Huawei VRPv8' }, { value: 'huawei_smartax', label: 'Huawei SmartAX' }, { value: 'huawei_usg', label: 'Huawei USG' }],
  H3C:        [
    { value: 'h3c_comware', label: 'H3C Comware' },
  ],
  Arista:     [{ value: 'arista_eos', label: 'Arista EOS' }],
  Juniper:    [{ value: 'juniper_junos', label: 'Juniper JunOS' }, { value: 'juniper_srx', label: 'Juniper SRX' }],
  Ruijie:     [{ value: 'ruijie_rgos', label: 'Ruijie RGOS' }, { value: 'ruijie_os', label: 'Ruijie OS' }],
  Fortinet:   [{ value: 'fortinet', label: 'FortiOS' }],
  'Palo Alto':[{ value: 'paloalto_panos', label: 'PAN-OS' }],
  Hillstone:  [{ value: 'hillstone_stoneos', label: 'Hillstone StoneOS' }],
  Sangfor:    [{ value: 'sangfor_ngaf', label: 'Sangfor NGAF / Network Secure' }],
  'Check Point': [{ value: 'check_point_gaia', label: 'Check Point Gaia' }],
  Sophos:     [{ value: 'sophos_firewall', label: 'Sophos Firewall' }],
  SonicWall:  [{ value: 'sonicwall_sonicos', label: 'SonicOS' }],
  WatchGuard: [{ value: 'watchguard_fireware', label: 'WatchGuard Fireware' }],
  F5:         [{ value: 'f5_bigip', label: 'F5 BIG-IP' }],
  'A10 Networks': [{ value: 'a10_acos', label: 'A10 ACOS' }],
  Barracuda:  [{ value: 'barracuda_cloudgen', label: 'Barracuda CloudGen Firewall' }],
  Venustech:  [{ value: 'venustech_usg', label: 'Venustech USG' }],
  NSFOCUS:    [{ value: 'nsfocus_firewall', label: 'NSFOCUS Firewall/WAF' }],
  Topsec:     [{ value: 'topsec_firewall', label: 'Topsec Firewall' }],
  'Qi An Xin': [{ value: 'qianxin_firewall', label: 'Qi An Xin Firewall' }],
  ZTE:        [{ value: 'zte_zxros', label: 'ZTE ZXROS' }],
  Raisecom:   [{ value: 'raisecom_ros', label: 'Raisecom ROS' }],
  Maipu:      [{ value: 'maipu', label: 'Maipu Network OS' }],
  DPtech:     [
    { value: 'dptech_conplat', label: 'DPTech Conplat (Switch)' },
    { value: 'dptech_conplat_fw', label: 'DPTech Conplat FW (Firewall)' },
  ],
  DCN:        [{ value: 'dcn_network', label: 'DCN Network OS' }],
  FiberHome:  [{ value: 'fiberhome_fengine', label: 'FiberHome Fengine' }],
  Nokia:      [{ value: 'nokia_sros', label: 'Nokia SR OS' }],
  Aruba:      [{ value: 'aruba_aos_cx', label: 'Aruba AOS-CX' }, { value: 'aruba_aos', label: 'Aruba AOS' }],
  'Extreme Networks': [{ value: 'extreme_exos', label: 'Extreme EXOS' }, { value: 'extreme_voss', label: 'Extreme VOSS' }],
  Ruckus:     [{ value: 'ruckus_fastiron', label: 'Ruckus FastIron' }],
  MikroTik:   [{ value: 'mikrotik_routeros', label: 'MikroTik RouterOS' }],
  Ubiquiti:   [{ value: 'ubiquiti_edgeswitch', label: 'Ubiquiti EdgeOS/EdgeSwitch' }, { value: 'ubiquiti_unifi', label: 'Ubiquiti UniFi' }],
  'D-Link':   [{ value: 'dlink_network', label: 'D-Link Network' }],
  'TP-Link':  [{ value: 'tplink_omada', label: 'TP-Link Omada' }],
  Dell:       [{ value: 'dell_os10', label: 'Dell OS10' }],
  Brocade:    [{ value: 'brocade_fastiron', label: 'Brocade FastIron' }],
  Ciena:      [{ value: 'ciena_saos', label: 'Ciena SAOS' }],
  'Alcatel-Lucent Enterprise': [{ value: 'ale_aos', label: 'ALE AOS' }],
  'Allied Telesis': [{ value: 'allied_telesis_awplus', label: 'AlliedWare Plus' }],
  Edgecore:   [{ value: 'edgecore_ocnos', label: 'Edgecore OcNOS' }],
};

export const SERVER_PLATFORMS = [
  { value: 'linux',   label: 'Linux (Generic)' },
  { value: 'ubuntu',  label: 'Ubuntu' },
  { value: 'centos',  label: 'CentOS' },
  { value: 'debian',  label: 'Debian' },
  { value: 'redhat',  label: 'Red Hat (RHEL)' },
  { value: 'windows', label: 'Windows Server' },
  { value: 'esxi',    label: 'VMware ESXi' },
];

export const uniquePlatforms = (items: { value: string; label: string }[]) => {
  const seen = new Set<string>();
  return items.filter(item => {
    if (seen.has(item.value)) return false;
    seen.add(item.value);
    return true;
  });
};

export const ALL_PLATFORMS = uniquePlatforms([...Object.values(VENDOR_PLATFORMS).flat(), ...SERVER_PLATFORMS]);

export const NETWORK_PLATFORM_PLATFORMS = uniquePlatforms(
  [...NETWORK_VENDOR_NAMES, ...SECURITY_VENDOR_NAMES].flatMap(vendor => VENDOR_PLATFORMS[vendor] || []),
);

export const getPlatformsForVendor = (vendor?: string) => {
  if (!vendor) return ALL_PLATFORMS;
  const v = vendor.trim().toLowerCase();
  const matchedKey = Object.keys(VENDOR_PLATFORMS).find(k => k.toLowerCase() === v || (v === '迪普' && k.toLowerCase() === 'dptech'));
  if (matchedKey && VENDOR_PLATFORMS[matchedKey]) {
    return uniquePlatforms(VENDOR_PLATFORMS[matchedKey]);
  }
  return ALL_PLATFORMS;
};

export const COL_MAP: Record<string, string> = {
  '主机名': 'hostname', 'Hostname': 'hostname', 'hostname': 'hostname',
  '资产编号': 'asset_tag', 'Asset Tag': 'asset_tag', 'asset_tag': 'asset_tag', 'Tag': 'asset_tag',
  '序列号': 'serial_number', 'Serial Number': 'serial_number', 'serial_number': 'serial_number',
  '资产类型': 'asset_type', '类型': 'asset_type', 'Asset Type': 'asset_type', 'Type': 'asset_type', 'asset_type': 'asset_type',
  '厂商': 'vendor', 'Vendor': 'vendor', 'vendor': 'vendor',
  '型号': 'model', 'Model': 'model', 'model': 'model',
  '管理IP': 'management_ip', 'Mgmt IP': 'management_ip', 'management_ip': 'management_ip',
  '业务IP': 'business_ip', 'Business IP': 'business_ip', 'business_ip': 'business_ip',
  '状态': 'status', 'Status': 'status', 'status': 'status',
  '角色': 'device_role', '拓扑角色': 'device_role', 'Role': 'device_role', 'Topology Role': 'device_role', 'role': 'device_role', 'device_role': 'device_role',
  '功能': 'function', 'Function': 'function', 'function': 'function',
  '区域': 'zone', 'Zone': 'zone', 'zone': 'zone', '网络区域': 'zone', 'Network Zone': 'zone',
  '站点': 'site_id', 'Site': 'site_id', 'site_id': 'site_id',
  '数据中心': 'site_id', 'Datacenter': 'site_id', 'DC': 'site_id', 'datacenter': 'site_id',
  '机柜': 'rack', 'Rack': 'rack', 'rack': 'rack',
  'U位': 'rack_unit', 'Rack Unit': 'rack_unit', 'rack_unit': 'rack_unit',
  '部门': 'department', 'Department': 'department', 'Dept': 'department', 'department': 'department',
  '购买日期': 'purchase_date', 'Purchase Date': 'purchase_date', 'purchase_date': 'purchase_date',
  '保修到期': 'warranty_expiry', 'Warranty Expiry': 'warranty_expiry', 'warranty_expiry': 'warranty_expiry',
  '备注': 'notes', 'Notes': 'notes', 'notes': 'notes',
  'VLAN': 'vlan', 'vlan': 'vlan',
  '上联交换机': 'uplink_switch', 'Uplink Switch': 'uplink_switch', 'uplink_switch': 'uplink_switch',
  '上联端口': 'uplink_port', 'Uplink Port': 'uplink_port', 'uplink_port': 'uplink_port',
  '平台': 'platform', 'Platform': 'platform', 'platform': 'platform',
  '管理端口': 'management_port', 'SSH端口': 'management_port', 'SSH 端口': 'management_port',
  'SSH管理端口': 'management_port', '端口 (SSH/Mgmt)': 'management_port', '端口(SSH/Mgmt)': 'management_port',
  'Mgmt Port': 'management_port', 'SSH Port': 'management_port', 'management_port': 'management_port', 'ssh_port': 'management_port',
  '设备分类': 'device_category', 'Device Category': 'device_category', 'device_category': 'device_category',
  '连接方式': 'connection_method', 'Connection': 'connection_method', 'connection_method': 'connection_method',
  'SNMP社区名': 'snmp_community', 'SNMP Community': 'snmp_community', 'snmp_community': 'snmp_community',
  'SNMP端口': 'snmp_port', 'SNMP Port': 'snmp_port', 'snmp_port': 'snmp_port',
  'U高度': 'u_height', 'U Height': 'u_height', 'u_height': 'u_height',
  '规划起始U': 'planned_start_u', 'Planned Start U': 'planned_start_u', 'planned_start_u': 'planned_start_u',
  '功耗(W)': 'power_watts', 'Power(W)': 'power_watts', 'power_watts': 'power_watts',
  '投产状态': 'lifecycle_status', 'Lifecycle': 'lifecycle_status', 'lifecycle_status': 'lifecycle_status',
  '普通用户': 'normal_username', 'Normal User': 'normal_username', 'normal_username': 'normal_username',
  '特权用户': 'admin_username', 'Admin User': 'admin_username', 'admin_username': 'admin_username',
  '用户名': 'username', 'Username': 'username', 'username': 'username',
  '密码': 'password', 'Password': 'password', 'password': 'password',
  '普通密码': 'normal_password', 'Normal Password': 'normal_password', 'normal_password': 'normal_password',
  '特权密码': 'admin_password', 'Admin Password': 'admin_password', 'admin_password': 'admin_password',
  'Enable密码': 'enable_password', 'Enable Secret': 'enable_password', 'enable_password': 'enable_password',
  '设备来源': 'asset_origin', 'Asset Origin': 'asset_origin', 'asset_origin': 'asset_origin',
  '录入来源': 'asset_origin', '初始设备来源': 'asset_origin',
  '设备来源（必填：new=新设备，legacy=存量设备）': 'asset_origin',
  '录入来源（必填：新设备或存量设备）': 'asset_origin',
  'Asset Origin (Required: new or legacy)': 'asset_origin',
  '绑定凭据': 'credential_id', '凭据名称': 'credential_id', '凭据ID': 'credential_id', 'Credential': 'credential_id', 'credential_id': 'credential_id',
  '绑定特权凭据': 'admin_credential_id', '特权凭据': 'admin_credential_id', 'Admin Credential': 'admin_credential_id', 'admin_credential_id': 'admin_credential_id',
  '标签': 'tag_codes', '标签代码': 'tag_codes', 'Tags': 'tag_codes', 'Tag Codes': 'tag_codes', 'tag_codes': 'tag_codes',
  '免上收投产原因': 'takeover_exempt_reason', 'Takeover Exemption Reason': 'takeover_exempt_reason', 'takeover_exempt_reason': 'takeover_exempt_reason',
};

export const IMPORT_VALUE_MAP: Record<string, Record<string, string>> = {
  vendor: {
    ...VENDOR_IMPORT_ALIASES,
    '思科': 'Cisco', '华为': 'Huawei', '华三': 'H3C', '阿里斯塔': 'Arista',
    '瞻博': 'Juniper', '锐捷': 'Ruijie', '飞塔': 'Fortinet', '帕洛阿尔托': 'Palo Alto',
    '中兴': 'ZTE', '迈普': 'Maipu', '迪普': 'DPtech', '迪普科技': 'DPtech', 'DPTech': 'DPtech', 'DPtech': 'DPtech', 'dptech': 'DPtech',
    '神州数码': 'DCN', '烽火': 'FiberHome', '诺基亚': 'Nokia', '极进': 'Extreme Networks',
    '山石': 'Hillstone', '深信服': 'Sangfor', '检查点': 'Check Point', '奇安信': 'Qi An Xin',
    '天融信': 'Topsec', '绿盟': 'NSFOCUS', '启明星辰': 'Venustech', '飞塔科技': 'Fortinet',
    '戴尔': 'Dell', '惠普': 'HP', '联想': 'Lenovo',
    '浪潮': 'Inspur', '通用服务器': 'Generic Server',
  },
  device_role: {
    '核心层': 'core', '汇聚层': 'distribution', '接入层': 'access', '边缘设备': 'edge',
    '交换机': 'switch', '路由器': 'router', '防火墙': 'firewall', '无线控制器': 'wireless_controller',
    '无线接入点': 'wireless_ap', '负载均衡': 'load_balancer', 'VPN 网关': 'vpn_gateway', 'SD-WAN 边缘': 'sdwan_edge', '其他网络设备': 'other_network',
    'WAF': 'waf', 'OOB 管理交换机': 'oob_switch', '未知': 'unknown',
    '业务服务器': 'application_server', '应用服务器': 'application_server', '数据库服务器': 'database_server', 'Web服务器': 'web_server',
    '文件服务器': 'file_server', '中间件服务器': 'middleware_server', '虚拟化宿主机': 'virtual_host', '存储服务器': 'storage',
    '备份服务器': 'backup_server', '其他服务器': 'other_server', '服务器': 'server', '存储设备': 'storage', '其他': 'other',
    core: 'core', distribution: 'distribution', access: 'access', edge: 'edge', switch: 'switch',
    router: 'router', firewall: 'firewall', wireless_controller: 'wireless_controller', wireless_ap: 'wireless_ap',
    load_balancer: 'load_balancer', vpn_gateway: 'vpn_gateway', sdwan_edge: 'sdwan_edge', other_network: 'other_network',
    application_server: 'application_server', database_server: 'database_server', web_server: 'web_server', file_server: 'file_server',
    middleware_server: 'middleware_server', virtual_host: 'virtual_host', backup_server: 'backup_server', other_server: 'other_server',
    server: 'server', storage: 'storage', other: 'other',
  },
  function: {
    '核心路由/交换': 'Campus Core', '园区核心': 'Campus Core',
    '汇聚路由/交换': 'Business Aggregation', '业务汇聚': 'Business Aggregation',
    '接入交换': 'Terminal Access', '终端接入': 'Terminal Access',
    '互联网边界': 'Internet Edge', 'DMZ 安全': 'DMZ Security',
    '服务器接入': 'Server Access', '业务应用': 'Business Application',
    '带外管理': 'OOB Management', '无线控制': 'Wireless Controller',
    'WAN 边界': 'WAN Edge', '站点互联': 'Site Interconnect', '其他': 'Other', '未知': 'Unknown',
  },
  zone: {
    '生产区': 'Production', '管理区': 'Management', '带外管理区': 'OOB',
    '内网区': 'LAN', '广域网区': 'WAN', 'DMZ 区': 'DMZ',
    '互联网区': 'Internet', '无线区': 'Wireless', '服务器区': 'Server',
    '办公区': 'Office', '其他': 'Other', '未知': 'Unknown',
  },
  asset_origin: {
    '新设备': 'new', '新设备录入': 'new', new: 'new',
    '存量设备': 'legacy', '存量设备补录': 'legacy', legacy: 'legacy',
  },
  lifecycle_status: {
    '待投产': 'staging', staging: 'staging',
    '已投产': 'production', production: 'production',
    '维护中': 'maintenance', maintenance: 'maintenance',
    '已退役': 'decommissioned', decommissioned: 'decommissioned',
  },
  status: {
    '在用': 'active', active: 'active',
    '闲置': 'inactive', inactive: 'inactive',
    '库存中': 'in_storage', in_storage: 'in_storage',
    '维护中': 'maintenance', maintenance: 'maintenance',
    '已退役': 'decommissioned', decommissioned: 'decommissioned',
  },
  connection_method: {
    'SSH（安全外壳）': 'ssh', SSH: 'ssh', ssh: 'ssh',
    'NETCONF（网络配置协议）': 'netconf', NETCONF: 'netconf', netconf: 'netconf',
    '仅 Web（HTTP/HTTPS）': 'web', 'Web only': 'web', web: 'web',
    '无登录通道': 'none', 'No login channel': 'none', none: 'none',
  },
  platform: {
    '思科 IOS': 'cisco_ios', '思科 NX-OS': 'cisco_nxos', '思科 IOS-XE': 'cisco_xe',
    '华为 VRPv5': 'huawei_vrp', '华为 VRPv8': 'huawei_vrpv8',
    '华三 Comware V5': 'h3c_comware', '华三 Comware V7': 'h3c_comware', '华三 Comware V9': 'h3c_comware',
    '阿里斯塔 EOS': 'arista_eos', '瞻博 JunOS': 'juniper_junos', '锐捷 RGOS': 'ruijie_rgos',
    '飞塔 FortiOS': 'fortinet', '帕洛阿尔托 PAN-OS': 'paloalto_panos', '中兴 ZXROS': 'zte_zxros', '瑞斯康达 ROS': 'raisecom_ros', '迈普网络系统': 'maipu',
    '迪普 Conplat': 'dptech_conplat', '迪普 Conplat FW': 'dptech_conplat_fw',
    '迪普交换机': 'dptech_conplat', '迪普防火墙': 'dptech_conplat_fw',
    'DPTech Conplat (Switch)': 'dptech_conplat', 'DPTech Conplat FW (Firewall)': 'dptech_conplat_fw',
    'DPTech Conplat': 'dptech_conplat', 'DPTech Conplat FW': 'dptech_conplat_fw',
    dptech_conplat: 'dptech_conplat', dptech_conplat_fw: 'dptech_conplat_fw', dptech_ios: 'dptech_conplat',
    'Linux（通用）': 'linux', '红帽 RHEL': 'redhat', 'Windows服务器': 'windows', 'VMware ESXi（虚拟化）': 'esxi',
    Ubuntu: 'ubuntu', CentOS: 'centos', Debian: 'debian',
    'Cisco IOS': 'cisco_ios', 'Cisco NX-OS': 'cisco_nxos', 'Cisco IOS-XE': 'cisco_xe',
    'Huawei VRPv5': 'huawei_vrp', 'Huawei VRPv8': 'huawei_vrpv8',
    'H3C Comware': 'h3c_comware', 'H3C Comware V5': 'h3c_comware', 'H3C Comware V7': 'h3c_comware', 'H3C Comware V9': 'h3c_comware',
    'Juniper JunOS': 'juniper_junos', 'Arista EOS': 'arista_eos', 'Ruijie RGOS': 'ruijie_rgos',
    FortiOS: 'fortinet', 'ZTE ZXROS': 'zte_zxros', 'Raisecom ROS': 'raisecom_ros', 'Maipu Network OS': 'maipu',
    'Windows Server': 'windows', 'VMware ESXi': 'esxi',
  },
  device_category: {
    '机架式服务器': 'rack_server', '刀片服务器': 'blade_server', '塔式服务器': 'tower_server',
    '高密度服务器': 'high_density', 'GPU服务器': 'gpu_server', '存储服务器': 'storage_server',
    '虚拟化宿主机': 'virtual_host', '其他服务器': 'other_server', '交换机': 'switch', '路由器': 'router',
    '防火墙': 'firewall', '负载均衡': 'load_balancer', '无线控制器': 'wireless_controller', '无线AP': 'wireless_ap',
    'SD-WAN边缘': 'sdwan_edge', 'VPN网关': 'vpn_gateway', '其他网络设备': 'other_network', '其他': 'other',
  },
};

// Accept both the canonical platform code and the display label shown in the
// platform catalog. This keeps imports forward-compatible as new vendors are
// added to VENDOR_PLATFORMS.
for (const platform of ALL_PLATFORMS) {
  IMPORT_VALUE_MAP.platform[platform.value] = platform.value;
  IMPORT_VALUE_MAP.platform[platform.label] = platform.value;
}

export const NETWORK_IMPORT_VENDOR_VALUES = Array.from(new Set([
  ...NETWORK_VENDOR_NAMES,
  ...SECURITY_VENDOR_NAMES,
  ...Object.keys(VENDOR_IMPORT_ALIASES),
]));

const networkPlatformCodes = new Set(NETWORK_PLATFORM_PLATFORMS.map(platform => platform.value));
export const NETWORK_IMPORT_PLATFORM_VALUES = Array.from(new Set([
  ...NETWORK_PLATFORM_PLATFORMS.flatMap(platform => [platform.value, platform.label]),
  ...Object.entries(IMPORT_VALUE_MAP.platform)
    .filter(([, value]) => networkPlatformCodes.has(value))
    .map(([label]) => label),
]));

export const isValidIpAddress = (ip: string): boolean => {
  if (!ip || !ip.trim()) return false;
  const trimmed = ip.trim();
  const parts = trimmed.split('.');
  if (parts.length === 4) {
    return parts.every(part => {
      if (!/^\d+$/.test(part)) return false;
      const n = parseInt(part, 10);
      return n >= 0 && n <= 255 && (part === '0' || !part.startsWith('0'));
    });
  }
  const ipv6Regex = /^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|^(([0-9a-fA-F]{1,4}:){1,7}|:):((:[0-9a-fA-F]{1,4}){1,7}|:)$/;
  return ipv6Regex.test(trimmed);
};
