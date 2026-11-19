import { canonicalTopologyRole } from './topologyRoles';

export const TOPOLOGY_ICON_TYPES = [
  'switch', 'firewall', 'router', 'load_balancer', 'waf', 'vpn_gateway', 'server',
  'wireless_ap', 'wireless_controller', 'wireless', 'generic',
] as const;

export type TopologyIconType = typeof TOPOLOGY_ICON_TYPES[number];

const labels: Record<TopologyIconType, readonly [string, string]> = {
  switch: ['交换机', 'Switch'],
  firewall: ['防火墙', 'Firewall'],
  router: ['路由器', 'Router'],
  load_balancer: ['负载均衡', 'Load balancer'],
  waf: ['Web 应用防火墙', 'Web application firewall'],
  vpn_gateway: ['VPN 网关', 'VPN gateway'],
  server: ['服务器', 'Server'],
  wireless_ap: ['无线接入点', 'Wireless access point'],
  wireless_controller: ['无线控制器', 'Wireless controller'],
  wireless: ['其他无线设备', 'Other wireless device'],
  generic: ['通用设备', 'Generic device'],
};

export const topologyIconTypeLabel = (type: TopologyIconType, language = 'zh') => labels[type][language === 'zh' ? 0 : 1];

type IconDevice = {
  hostname?: string;
  role?: string;
  role_identity?: string;
  device_category?: string;
  platform?: string;
  model?: string;
};

const explicitTypes = new Set<string>(TOPOLOGY_ICON_TYPES.filter((type) => type !== 'generic'));
const switchRoles = new Set(['core', 'distribution', 'access', 'oob_switch']);

export const getTopologyDeviceIconType = (device: IconDevice): TopologyIconType => {
  const roles = [device.role_identity, device.role].map(canonicalTopologyRole);
  const specializedRole = roles.find((role) => explicitTypes.has(role) && role !== 'switch' && role !== 'wireless');
  if (specializedRole) return specializedRole as TopologyIconType;

  const category = canonicalTopologyRole(device.device_category);
  if (explicitTypes.has(category)) return category as TopologyIconType;
  if (category === '服务器') return 'server';
  if (roles.some((role) => role === 'switch' || switchRoles.has(role))) return 'switch';

  const fingerprint = [device.role_identity, device.role, device.device_category, device.platform, device.model, device.hostname]
    .map((value) => String(value || '').toLowerCase())
    .join(' ');
  if (/(waf|web application firewall|web防火墙)/.test(fingerprint)) return 'waf';
  if (/(load[-_ ]?balanc|\blb\b|f5|big[-_ ]?ip|adc\b|netscaler|citrix adc|haproxy|nginx plus)/.test(fingerprint)) return 'load_balancer';
  if (/(vpn|ipsec gateway|ssl vpn|远程接入网关)/.test(fingerprint)) return 'vpn_gateway';
  if (/(firewall|fortigate|forti|palo|pan-|checkpoint|srx|asa|ftd|fw\b)/.test(fingerprint)) return 'firewall';
  if (/(wireless[_ -]?controller|无线控制器|\bwlc\b)/.test(fingerprint)) return 'wireless_controller';
  if (/(wireless[_ -]?ap|access point|无线接入点|\bap\b|aironet)/.test(fingerprint)) return 'wireless_ap';
  if (/(wireless|wi-fi|wifi|aruba|unifi)/.test(fingerprint)) return 'wireless';
  if (/(router|gateway|wan|edge router|isr|asr|mx\b)/.test(fingerprint)) return 'router';
  if (/(switch|\bsw\d+|core|distribution|access|leaf|spine|nexus|catalyst)/.test(fingerprint)) return 'switch';
  if (/(server|compute|hypervisor|vmware|esxi|linux|windows server|unix)/.test(fingerprint)) return 'server';
  return 'generic';
};

const assets = import.meta.glob('../assets/topology/devices/**/*.svg', { eager: true, import: 'default', query: '?url' }) as Record<string, string>;

const assetCategories = {
  switch: 'switches', firewall: 'firewalls', router: 'routers', load_balancer: 'firewalls', waf: 'firewalls',
  vpn_gateway: 'firewalls', server: 'servers', wireless: 'wireless',
};

const preferredNames: Record<keyof typeof assetCategories, string[]> = {
  switch: ['switch.svg', 'cisco-switch-l3-480x480.svg', 'cisco-switch-l3-240x240.svg', 'cisco-switch-l3-144x144.svg'],
  router: ['router.svg'],
  firewall: ['firewall.svg'],
  load_balancer: ['load-balancer.svg', 'f5.svg', 'adc.svg', 'firewall.svg'],
  waf: ['waf.svg', 'web-application-firewall.svg', 'firewall.svg'],
  vpn_gateway: ['vpn-gateway.svg', 'vpn.svg', 'firewall.svg'],
  server: ['server.svg', 'server-linux.svg', 'server-windows.svg'],
  wireless: ['wireless.svg', 'access-point.svg', 'wifi-ap.svg'],
};

const builtinIcons = Object.fromEntries(Object.entries(assetCategories).map(([key, category]) => {
  const type = key as keyof typeof assetCategories;
  const matches = Object.entries(assets).filter(([path]) => path.includes(`/devices/${category}/`));
  const preferred = preferredNames[type].map((name) => matches.find(([path]) => path.endsWith(`/${name}`))?.[1]).find(Boolean);
  return [type, preferred || matches[0]?.[1]];
}));

export const getBuiltInTopologyIconUrl = (type: TopologyIconType) => (
  builtinIcons[type === 'wireless_ap' || type === 'wireless_controller' ? 'wireless' : type]
);

export const getTopologyIconDimensions = (type: TopologyIconType) => {
  if (type === 'load_balancer') return { width: 52, height: 60 };
  if (type === 'firewall' || type === 'waf' || type === 'vpn_gateway') return { width: 50, height: 60 };
  return { width: 58, height: 58 };
};
