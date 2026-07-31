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
  power_watts: '',       
  credential_id: '',
  admin_credential_id: '',
  snmp_credential_id: '',
  tag_ids: [] as string[],
};

export const VENDOR_PLATFORMS: Record<string, { value: string; label: string }[]> = {
  Cisco:      [{ value: 'cisco_ios', label: 'Cisco IOS' }, { value: 'cisco_nxos', label: 'Cisco NX-OS' }, { value: 'cisco_xe', label: 'Cisco IOS-XE' }],
  Huawei:     [{ value: 'huawei_vrp', label: 'Huawei VRPv5' }, { value: 'huawei_vrpv8', label: 'Huawei VRPv8' }],
  H3C:        [
    { value: 'hp_comware', label: 'H3C Comware V5' },
    { value: 'h3c_comware', label: 'H3C Comware V7' },
    { value: 'h3c_comware9', label: 'H3C Comware V9' },
  ],
  Arista:     [{ value: 'arista_eos', label: 'Arista EOS' }],
  Juniper:    [{ value: 'juniper_junos', label: 'Juniper JunOS' }],
  Ruijie:     [{ value: 'ruijie_rgos', label: 'Ruijie RGOS' }],
  Fortinet:   [{ value: 'fortinet', label: 'FortiOS' }],
  'Palo Alto':[{ value: 'paloalto_panos', label: 'PAN-OS' }],
  ZTE:        [{ value: 'zte_zxros', label: 'ZTE ZXROS' }],
  Maipu:      [{ value: 'maipu', label: 'Maipu Network OS' }],
  DPtech:     [
    { value: 'dptech_conplat', label: 'DPTech Conplat (Switch)' },
    { value: 'dptech_conplat_fw', label: 'DPTech Conplat FW (Firewall)' },
  ],
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
  '类型': 'asset_type', 'Type': 'asset_type', 'asset_type': 'asset_type',
  '厂商': 'vendor', 'Vendor': 'vendor', 'vendor': 'vendor',
  '型号': 'model', 'Model': 'model', 'model': 'model',
  '管理IP': 'management_ip', 'Mgmt IP': 'management_ip', 'management_ip': 'management_ip',
  '业务IP': 'business_ip', 'Business IP': 'business_ip', 'business_ip': 'business_ip',
  '状态': 'status', 'Status': 'status', 'status': 'status',
  '角色': 'device_role', 'Role': 'device_role', 'device_role': 'device_role',
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
    '思科': 'Cisco', '华为': 'Huawei', '华三': 'H3C', '阿里斯塔': 'Arista',
    '瞻博': 'Juniper', '锐捷': 'Ruijie', '飞塔': 'Fortinet', '帕洛阿尔托': 'Palo Alto',
    '中兴': 'ZTE', '迈普': 'Maipu', '迪普': 'DPtech', '迪普科技': 'DPtech', 'DPTech': 'DPtech', 'DPtech': 'DPtech', 'dptech': 'DPtech',
    '戴尔': 'Dell', '惠普': 'HP', '联想': 'Lenovo',
    '浪潮': 'Inspur', '通用服务器': 'Generic Server',
  },
  device_role: {
    '核心交换机': 'core', '汇聚交换机': 'distribution', '接入交换机': 'access', '边缘设备': 'edge',
    '交换机': 'switch', '路由器': 'router', '防火墙': 'firewall', '无线控制器': 'wireless_controller',
    '无线接入点': 'wireless_ap', '负载均衡': 'load_balancer', 'VPN网关': 'vpn_gateway', 'SD-WAN边缘': 'sdwan_edge', '其他网络设备': 'other_network',
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
  },
  platform: {
    '思科 IOS': 'cisco_ios', '思科 NX-OS': 'cisco_nxos', '思科 IOS-XE': 'cisco_xe',
    '华为 VRPv5': 'huawei_vrp', '华为 VRPv8': 'huawei_vrpv8',
    '华三 Comware V5': 'hp_comware', '华三 Comware V7': 'h3c_comware', '华三 Comware V9': 'h3c_comware9',
    '阿里斯塔 EOS': 'arista_eos', '瞻博 JunOS': 'juniper_junos', '锐捷 RGOS': 'ruijie_rgos',
    '飞塔 FortiOS': 'fortinet', '帕洛阿尔托 PAN-OS': 'paloalto_panos', '中兴 ZXROS': 'zte_zxros', '迈普网络系统': 'maipu',
    '迪普 Conplat': 'dptech_conplat', '迪普 Conplat FW': 'dptech_conplat_fw',
    '迪普交换机': 'dptech_conplat', '迪普防火墙': 'dptech_conplat_fw',
    'DPTech Conplat (Switch)': 'dptech_conplat', 'DPTech Conplat FW (Firewall)': 'dptech_conplat_fw',
    'DPTech Conplat': 'dptech_conplat', 'DPTech Conplat FW': 'dptech_conplat_fw',
    dptech_conplat: 'dptech_conplat', dptech_conplat_fw: 'dptech_conplat_fw', dptech_ios: 'dptech_conplat',
    'Linux（通用）': 'linux', '红帽 RHEL': 'redhat', 'Windows服务器': 'windows', 'VMware ESXi（虚拟化）': 'esxi',
    Ubuntu: 'ubuntu', CentOS: 'centos', Debian: 'debian',
    'Cisco IOS': 'cisco_ios', 'Cisco NX-OS': 'cisco_nxos', 'Cisco IOS-XE': 'cisco_xe',
    'Huawei VRPv5': 'huawei_vrp', 'Huawei VRPv8': 'huawei_vrpv8',
    'H3C Comware': 'hp_comware', 'H3C Comware V5': 'hp_comware', 'H3C Comware V7': 'h3c_comware', 'H3C Comware V9': 'h3c_comware9',
    'Juniper JunOS': 'juniper_junos', 'Arista EOS': 'arista_eos', 'Ruijie RGOS': 'ruijie_rgos',
    FortiOS: 'fortinet', 'ZTE ZXROS': 'zte_zxros', 'Maipu Network OS': 'maipu',
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
