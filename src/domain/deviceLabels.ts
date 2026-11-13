import { canonicalTopologyRole, NETWORK_TOPOLOGY_ROLE_OPTIONS } from './topologyRoles';

export type DeviceLabelLanguage = 'zh' | 'en';

type BilingualLabel = { zh: string; en: string };

export const DEVICE_CATEGORY_LABELS: Record<string, BilingualLabel> = {
  network_device: { zh: '网络设备', en: 'Network device' },
  server: { zh: '服务器', en: 'Server' },
  switch: { zh: '交换机', en: 'Switch' },
  router: { zh: '路由器', en: 'Router' },
  firewall: { zh: '防火墙', en: 'Firewall' },
  load_balancer: { zh: '负载均衡', en: 'Load balancer' },
  wireless_controller: { zh: '无线控制器', en: 'Wireless controller' },
  wireless_ap: { zh: '无线接入点', en: 'Wireless AP' },
  sdwan_edge: { zh: 'SD-WAN 边缘设备', en: 'SD-WAN edge' },
  vpn_gateway: { zh: 'VPN 网关', en: 'VPN gateway' },
  oob_switch: { zh: '带外管理交换机', en: 'OOB switch' },
  other_network: { zh: '其他网络设备', en: 'Other network device' },
  rack_server: { zh: '机架式服务器', en: 'Rack server' },
  blade_server: { zh: '刀片服务器', en: 'Blade server' },
  tower_server: { zh: '塔式服务器', en: 'Tower server' },
  high_density: { zh: '高密度服务器', en: 'High-density server' },
  gpu_server: { zh: 'GPU 服务器', en: 'GPU server' },
  storage_server: { zh: '存储服务器', en: 'Storage server' },
  storage: { zh: '存储设备', en: 'Storage' },
  virtual_host: { zh: '虚拟/物理宿主机', en: 'Virtual host' },
  other_server: { zh: '其他服务器', en: 'Other server' },
  other: { zh: '其他', en: 'Other' },
  unknown: { zh: '未知', en: 'Unknown' },
};

const DEVICE_CATEGORY_ALIASES: Record<string, string> = {
  network: 'network_device',
  wireless_ac: 'wireless_controller',
  wireless: 'wireless_controller',
  ap: 'wireless_ap',
  sd_wan_edge: 'sdwan_edge',
  'sd-wan_edge': 'sdwan_edge',
  other_device: 'other',
};

const DEVICE_ROLE_LABELS: Record<string, BilingualLabel> = {
  server: { zh: '服务器', en: 'Server' },
  application_server: { zh: '应用服务器', en: 'Application server' },
  database_server: { zh: '数据库服务器', en: 'Database server' },
  web_server: { zh: 'Web 服务器', en: 'Web server' },
  web: { zh: 'Web 服务器', en: 'Web server' },
  app: { zh: '应用服务器', en: 'Application server' },
  database: { zh: '数据库服务器', en: 'Database server' },
  db: { zh: '数据库服务器', en: 'Database server' },
  file_server: { zh: '文件服务器', en: 'File server' },
  file: { zh: '文件服务器', en: 'File server' },
  middleware_server: { zh: '中间件服务器', en: 'Middleware server' },
  backup_server: { zh: '备份服务器', en: 'Backup server' },
  backup: { zh: '备份服务器', en: 'Backup server' },
  other_server: { zh: '其他服务器', en: 'Other server' },
  server_switch: { zh: '服务器交换机', en: 'Server switch' },
  storage: { zh: '存储设备', en: 'Storage' },
  patch_panel: { zh: '配线架', en: 'Patch panel' },
  pdu: { zh: 'PDU', en: 'PDU' },
  ups: { zh: 'UPS', en: 'UPS' },
  unassigned: { zh: '未分配', en: 'Unassigned' },
  unclassified: { zh: '未分类', en: 'Unclassified' },
  other: { zh: '其他', en: 'Other' },
  test: { zh: '测试设备', en: 'Test device' },
};

const LEGACY_ROLE_ALIASES: Record<string, string> = {
  'core switch': 'core',
  aggregation_switch: 'distribution',
  'aggregation switch': 'distribution',
  'access switch': 'access',
  'wireless ac': 'wireless_controller',
  vpn: 'vpn_gateway',
  unknown: 'unknown',
};

const normalizeKey = (value: unknown): string => String(value ?? '')
  .trim()
  .toLowerCase()
  .replace(/[\s-]+/g, '_');

export function deviceCategoryLabel(value: unknown, language: DeviceLabelLanguage): string {
  const raw = String(value ?? '').trim();
  if (!raw) return language === 'zh' ? '未分类' : 'Unclassified';
  const key = normalizeKey(raw);
  const categoryKey = DEVICE_CATEGORY_ALIASES[key] || key;
  return DEVICE_CATEGORY_LABELS[categoryKey]?.[language] || raw;
}

export function deviceRoleLabel(value: unknown, language: DeviceLabelLanguage): string {
  const raw = String(value ?? '').trim();
  if (!raw) return language === 'zh' ? '未分配' : 'Unassigned';

  const explicitLabel = DEVICE_ROLE_LABELS[normalizeKey(raw)];
  if (explicitLabel) return explicitLabel[language];

  const normalized = raw.toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  const roleKey = LEGACY_ROLE_ALIASES[normalized] || LEGACY_ROLE_ALIASES[normalizeKey(raw)] || canonicalTopologyRole(raw);
  const topologyRole = NETWORK_TOPOLOGY_ROLE_OPTIONS.find(option => option.value === roleKey);
  if (topologyRole) return topologyRole.label[language];
  return raw;
}
