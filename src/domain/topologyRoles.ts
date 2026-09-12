export const NETWORK_TOPOLOGY_ROLE_OPTIONS = [
  { value: 'core', label: { zh: '核心层', en: 'Core' } },
  { value: 'distribution', label: { zh: '汇聚层', en: 'Distribution' } },
  { value: 'access', label: { zh: '接入层', en: 'Access' } },
  { value: 'edge', label: { zh: '边缘设备', en: 'Edge' } },
  { value: 'switch', label: { zh: '交换机', en: 'Switch' } },
  { value: 'router', label: { zh: '路由器', en: 'Router' } },
  { value: 'firewall', label: { zh: '防火墙', en: 'Firewall' } },
  { value: 'wireless_controller', label: { zh: '无线控制器', en: 'Wireless Controller' } },
  { value: 'wireless_ap', label: { zh: '无线接入点', en: 'Wireless AP' } },
  { value: 'load_balancer', label: { zh: '负载均衡', en: 'Load Balancer' } },
  { value: 'waf', label: { zh: 'WAF', en: 'WAF' } },
  { value: 'vpn_gateway', label: { zh: 'VPN 网关', en: 'VPN Gateway' } },
  { value: 'sdwan_edge', label: { zh: 'SD-WAN 边缘', en: 'SD-WAN Edge' } },
  { value: 'oob_switch', label: { zh: 'OOB 管理交换机', en: 'OOB Switch' } },
  { value: 'other_network', label: { zh: '其他网络设备', en: 'Other Network Device' } },
  { value: 'unknown', label: { zh: '未知', en: 'Unknown' } },
] as const;

export const NETWORK_TOPOLOGY_ROLE_VALUES: string[] = NETWORK_TOPOLOGY_ROLE_OPTIONS.map(option => option.value);

/**
 * Visual tiers define the presentation order for imported topology roles.
 * They must not be written back as evidence-derived `topology_rank` values;
 * relationship ranks remain semantic data and the layout can fall back to
 * them when role information is unavailable.
 *
 * The import/API contract uses the canonical English keys, but accepting the
 * previous Chinese labels and legacy keys here keeps already imported assets
 * renderable while the data is being migrated.
 */
const TOPOLOGY_ROLE_ALIASES: Record<string, string> = {
  core: 'core',
  核心: 'core',
  核心层: 'core',
  核心交换机: 'core',
  core_switch: 'core',
  distribution: 'distribution',
  汇聚: 'distribution',
  汇聚层: 'distribution',
  汇聚交换机: 'distribution',
  aggregation: 'distribution',
  aggregation_switch: 'distribution',
  access: 'access',
  接入: 'access',
  接入层: 'access',
  接入交换机: 'access',
  access_switch: 'access',
  edge: 'edge',
  边缘: 'edge',
  边缘设备: 'edge',
  edge_device: 'edge',
  switch: 'switch',
  交换机: 'switch',
  router: 'router',
  路由器: 'router',
  firewall: 'firewall',
  防火墙: 'firewall',
  wireless_controller: 'wireless_controller',
  wireless_ac: 'wireless_controller',
  无线控制器: 'wireless_controller',
  wireless_ap: 'wireless_ap',
  ap: 'wireless_ap',
  无线ap: 'wireless_ap',
  无线接入点: 'wireless_ap',
  load_balancer: 'load_balancer',
  负载均衡: 'load_balancer',
  waf: 'waf',
  vpn_gateway: 'vpn_gateway',
  vpn网关: 'vpn_gateway',
  sdwan_edge: 'sdwan_edge',
  sd_wan_edge: 'sdwan_edge',
  sdwan边缘: 'sdwan_edge',
  oob_switch: 'oob_switch',
  oob管理交换机: 'oob_switch',
  other_network: 'other_network',
  other: 'other_network',
  其他网络设备: 'other_network',
  unknown: 'unknown',
  未知: 'unknown',
};

const TOPOLOGY_ROLE_VISUAL_TIERS: Record<string, number> = {
  firewall: 0,
  waf: 0,
  vpn_gateway: 0,
  load_balancer: 0,
  router: 0,
  edge: 0,
  sdwan_edge: 0,
  core: 1,
  distribution: 2,
  access: 3,
  switch: 3,
  wireless_controller: 3,
  wireless_ap: 4,
  oob_switch: 4,
  other_network: 4,
  unknown: 4,
};

const normalizeTopologyRoleToken = (value: unknown): string => String(value || '')
  .trim()
  .toLowerCase()
  .replace(/[\s-]+/g, '_');

export const canonicalTopologyRole = (value: unknown): string => {
  const normalized = normalizeTopologyRoleToken(value);
  return TOPOLOGY_ROLE_ALIASES[normalized] || normalized;
};

export const topologyRoleVisualTier = (value: unknown): number | null => {
  const key = canonicalTopologyRole(value);
  const tier = TOPOLOGY_ROLE_VISUAL_TIERS[key];
  return Number.isFinite(tier) ? tier : null;
};

export const topologyRoleLabel = (role: string, language: string): string => {
  const option = NETWORK_TOPOLOGY_ROLE_OPTIONS.find(item => item.value === role);
  return option ? option.label[language === 'zh' ? 'zh' : 'en'] : role;
};
