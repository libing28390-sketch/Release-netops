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
  hostname: '', datacenter: '', rack: '', rack_unit: '', u_height: '1', planned_start_u: '', management_ip: '',
  business_ip: '', device_role: '', vlan: '', uplink_switch: '', uplink_port: '',
  status: 'active', lifecycle_status: 'staging', purchase_date: '', warranty_expiry: '', department: '', notes: '',
  platform: '', connection_method: 'ssh', 
  username: '', password: '',
  normal_username: '', normal_password: '',
  admin_username: '', admin_password: '',
  enable_password: '',   
  auth_model: 'dual',
  snmp_community: 'public', snmp_port: '161',
  management_port: '22',
  device_category: '',   
  power_watts: '',       
};

export const VENDOR_PLATFORMS: Record<string, { value: string; label: string }[]> = {
  Cisco:      [{ value: 'cisco_ios', label: 'Cisco IOS' }, { value: 'cisco_nxos', label: 'Cisco NX-OS' }, { value: 'cisco_xe', label: 'Cisco IOS-XE' }],
  Huawei:     [{ value: 'huawei_vrp', label: 'Huawei VRP' }],
  H3C:        [{ value: 'hp_comware', label: 'H3C Comware' }],
  Arista:     [{ value: 'arista_eos', label: 'Arista EOS' }],
  Juniper:    [{ value: 'juniper_junos', label: 'Juniper JunOS' }],
  Ruijie:     [{ value: 'ruijie_os', label: 'Ruijie RGOS' }],
  Fortinet:   [{ value: 'fortinet', label: 'FortiOS' }],
  'Palo Alto':[{ value: 'paloalto_panos', label: 'PAN-OS' }],
  ZTE:        [{ value: 'zte_zxros', label: 'ZTE ZXROS' }],
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

export const ALL_PLATFORMS = [...Object.values(VENDOR_PLATFORMS).flat(), ...SERVER_PLATFORMS];

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
  '数据中心': 'datacenter', 'Datacenter': 'datacenter', 'DC': 'datacenter', 'datacenter': 'datacenter',
  '机柜': 'rack', 'Rack': 'rack', 'rack': 'rack',
  'U位': 'rack_unit', 'Rack Unit': 'rack_unit', 'rack_unit': 'rack_unit',
  '部门': 'department', 'Department': 'department', 'Dept': 'department', 'department': 'department',
  '购买日期': 'purchase_date', 'Purchase Date': 'purchase_date', 'purchase_date': 'purchase_date',
  '保修到期': 'warranty_expiry', 'Warranty Expiry': 'warranty_expiry', 'warranty_expiry': 'warranty_expiry',
  '备注': 'notes', 'Notes': 'notes', 'notes': 'notes',
  'VLAN': 'vlan', 'vlan': 'vlan',
  '上联交换机': 'uplink_switch', 'Uplink Switch': 'uplink_switch', 'uplink_switch': 'uplink_switch',
  '上联端口': 'uplink_port', 'Uplink Port': 'uplink_port', 'uplink_port': 'uplink_port',
};
