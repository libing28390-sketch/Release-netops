import type { RackDeviceVM } from './types';

export type RackProfileCategory =
  | 'network'
  | 'server'
  | 'storage'
  | 'security'
  | 'integrated'
  | 'cabling'
  | 'power'
  | 'transmission';

export type RackProfileId =
  | 'network-core'
  | 'network-aggregation'
  | 'network-access'
  | 'network-leaf-spine'
  | 'network-high-density'
  | 'server'
  | 'storage'
  | 'security'
  | 'integrated'
  | 'cabling'
  | 'power-ups'
  | 'transmission';

export interface RackProfileDefinition {
  id: RackProfileId;
  category: RackProfileCategory;
  labelZh: string;
  labelEn: string;
  descriptionZh: string;
  descriptionEn: string;
  /** Human-readable example only; never used as an installed-device list. */
  recommendedLayoutZh: string[];
  recommendedLayoutEn: string[];
}

/**
 * Reusable rack-purpose catalog.  These are presentation/templates only;
 * authoritative equipment and U positions still come from the CMDB layout.
 */
export const RACK_PROFILE_DEFINITIONS: RackProfileDefinition[] = [
  {
    id: 'network-core',
    category: 'network',
    labelZh: '网络设备柜 · 核心',
    labelEn: 'Network Rack · Core',
    descriptionZh: '核心交换机、路由器与上联光纤配套。',
    descriptionEn: 'Core switches, routers, and optical uplink support.',
    recommendedLayoutZh: ['顶部：ODF/光纤配线架', '中部：核心交换机', '底部：路由器/安全设备'],
    recommendedLayoutEn: ['Top: ODF/fiber panels', 'Middle: core switches', 'Bottom: routers/security'],
  },
  {
    id: 'network-aggregation',
    category: 'network',
    labelZh: '网络设备柜 · 汇聚',
    labelEn: 'Network Rack · Aggregation',
    descriptionZh: '汇聚交换机、边界路由与链路理线。',
    descriptionEn: 'Aggregation switches, edge routing, and cable management.',
    recommendedLayoutZh: ['顶部：光纤配线架/理线架', '中部：汇聚交换机', '底部：边界路由/防火墙'],
    recommendedLayoutEn: ['Top: fiber/cable management', 'Middle: aggregation switches', 'Bottom: edge routing/firewall'],
  },
  {
    id: 'network-access',
    category: 'network',
    labelZh: '网络设备柜 · 接入',
    labelEn: 'Network Rack · Access',
    descriptionZh: '园区接入、PoE 与弱电配线设备。',
    descriptionEn: 'Campus access, PoE, and structured cabling equipment.',
    recommendedLayoutZh: ['顶部：ODF/配线架', '中部：接入/PoE 交换机', '相邻 U：理线架'],
    recommendedLayoutEn: ['Top: ODF/patch panels', 'Middle: access/PoE switches', 'Adjacent U: cable managers'],
  },
  {
    id: 'network-leaf-spine',
    category: 'network',
    labelZh: '网络设备柜 · DC Leaf/Spine',
    labelEn: 'Network Rack · DC Leaf/Spine',
    descriptionZh: '数据中心 Leaf/Spine、OOB 与 Console 设备。',
    descriptionEn: 'Datacenter leaf/spine, OOB management, and console equipment.',
    recommendedLayoutZh: ['顶部：Leaf/Spine 上联', '中部：OOB 管理/Console', '底部：光纤理线'],
    recommendedLayoutEn: ['Top: leaf/spine uplinks', 'Middle: OOB/console', 'Bottom: fiber management'],
  },
  {
    id: 'network-high-density',
    category: 'network',
    labelZh: '网络设备柜 · 高密度交换机',
    labelEn: 'Network Rack · High-density Switching',
    descriptionZh: '一个机柜集中部署多台 1U 交换机，允许几乎全是交换机。',
    descriptionEn: 'A dense 1U switch cabinet; it is valid for nearly every U to be switching gear.',
    recommendedLayoutZh: ['顶部：配线架/理线架（可选）', '主体：多台核心/汇聚/接入交换机', '底部：保留空位或轻型网络设备'],
    recommendedLayoutEn: ['Top: optional patch/cable panels', 'Body: core/aggregation/access switches', 'Bottom: spare U or light network gear'],
  },
  {
    id: 'server',
    category: 'server',
    labelZh: '服务器柜',
    labelEn: 'Server Rack',
    descriptionZh: '以 1U/2U 服务器为主体，顶部通常保留 ToR。',
    descriptionEn: 'Primarily 1U/2U servers, commonly with ToR at the top.',
    recommendedLayoutZh: ['顶部：ToR/管理交换机', '中部：服务器', '底部：重型服务器/存储'],
    recommendedLayoutEn: ['Top: ToR/management', 'Middle: servers', 'Bottom: heavy compute/storage'],
  },
  {
    id: 'storage',
    category: 'storage',
    labelZh: '存储柜',
    labelEn: 'Storage Rack',
    descriptionZh: 'SAN/NAS、磁盘阵列与存储交换机，强调承重。',
    descriptionEn: 'SAN/NAS, disk arrays, and storage switches with load awareness.',
    recommendedLayoutZh: ['顶部：存储交换机', '中部：磁盘阵列', '底部：重型存储/扩展柜'],
    recommendedLayoutEn: ['Top: storage switches', 'Middle: disk arrays', 'Bottom: heavy storage/expansion'],
  },
  {
    id: 'security',
    category: 'security',
    labelZh: '安全设备柜',
    labelEn: 'Security Rack',
    descriptionZh: '防火墙、WAF、IPS、VPN、负载均衡与堡垒机。',
    descriptionEn: 'Firewalls, WAF, IPS, VPN, load balancers, and bastions.',
    recommendedLayoutZh: ['顶部：边界交换/光纤', '中部：防火墙/WAF/IPS', '底部：负载均衡/堡垒机'],
    recommendedLayoutEn: ['Top: edge switching/fiber', 'Middle: firewall/WAF/IPS', 'Bottom: load-balancing/bastion'],
  },
  {
    id: 'integrated',
    category: 'integrated',
    labelZh: '综合网络柜',
    labelEn: 'Integrated Rack',
    descriptionZh: '网络、服务器、存储与 UPS 的综合企业机房机柜。',
    descriptionEn: 'An enterprise mix of network, compute, storage, and UPS.',
    recommendedLayoutZh: ['顶部：光纤配线架/理线架', '中部：交换机、防火墙、服务器', '底部：存储/UPS'],
    recommendedLayoutEn: ['Top: fiber/cable management', 'Middle: switches/firewall/servers', 'Bottom: storage/UPS'],
  },
  {
    id: 'cabling',
    category: 'cabling',
    labelZh: '综合布线柜',
    labelEn: 'Cabling Rack',
    descriptionZh: '配线架、理线架、光纤盒与少量接入交换机。',
    descriptionEn: 'Patch panels, cable managers, fiber boxes, and limited access switching.',
    recommendedLayoutZh: ['主体：铜缆/光纤配线架', '间隔：理线架', '底部：轻型接入交换机'],
    recommendedLayoutEn: ['Body: copper/fiber panels', 'Intervals: cable managers', 'Bottom: light access switches'],
  },
  {
    id: 'power-ups',
    category: 'power',
    labelZh: 'UPS / 电源柜',
    labelEn: 'Power / UPS Rack',
    descriptionZh: 'UPS、电池、PDU、ATS 等重型电源设备。',
    descriptionEn: 'UPS, batteries, PDU, ATS, and other heavy power equipment.',
    recommendedLayoutZh: ['顶部：PDU/ATS', '中部：UPS', '底部：电池/重型设备'],
    recommendedLayoutEn: ['Top: PDU/ATS', 'Middle: UPS', 'Bottom: batteries/heavy equipment'],
  },
  {
    id: 'transmission',
    category: 'transmission',
    labelZh: '传输 / 光通信柜',
    labelEn: 'Transmission / Optical Rack',
    descriptionZh: 'ODF、DWDM、OTN、MSTP 与光放大设备。',
    descriptionEn: 'ODF, DWDM, OTN, MSTP, and optical amplification equipment.',
    recommendedLayoutZh: ['顶部：ODF', '中部：DWDM/OTN', '底部：电源与光放大'],
    recommendedLayoutEn: ['Top: ODF', 'Middle: DWDM/OTN', 'Bottom: power/optical amplification'],
  },
];

const PROFILE_BY_ID = new Map(RACK_PROFILE_DEFINITIONS.map(profile => [profile.id, profile]));

export function getRackProfile(id: RackProfileId): RackProfileDefinition {
  return PROFILE_BY_ID.get(id) || PROFILE_BY_ID.get('network-high-density')!;
}

function normalizedRole(device: Pick<RackDeviceVM, 'role' | 'model' | 'vendor'>): string {
  return `${device.role || ''} ${device.model || ''} ${device.vendor || ''}`.toLowerCase();
}

/** Infer a presentation profile without changing the authoritative rack data. */
export function inferRackProfile(devices: Array<Pick<RackDeviceVM, 'role' | 'model' | 'vendor'>>): RackProfileDefinition {
  if (devices.length === 0) return getRackProfile('integrated');

  const counts = {
    network: 0,
    security: 0,
    server: 0,
    storage: 0,
    cabling: 0,
    power: 0,
    transmission: 0,
  };
  devices.forEach(device => {
    const value = normalizedRole(device);
    if (/(patch.?panel|cabling|配线|理线|odf|fiber.?panel|光纤)/i.test(value)) counts.cabling += 1;
    else if (/(ups?|pdu|ats|battery|电源|电池)/i.test(value)) counts.power += 1;
    else if (/(dwdm|otn|mstp|传输|波分|光放)/i.test(value)) counts.transmission += 1;
    else if (/(server|服务器)/i.test(value)) counts.server += 1;
    else if (/(storage|nas|san|存储|磁盘)/i.test(value)) counts.storage += 1;
    else if (/(firewall|waf|ips|vpn|堡垒|安全)/i.test(value)) counts.security += 1;
    else if (/(switch|router|交换|路由|tor|leaf|spine|network)/i.test(value)) counts.network += 1;
  });

  const total = devices.length;
  if (counts.power / total >= 0.6) return getRackProfile('power-ups');
  if (counts.transmission / total >= 0.5) return getRackProfile('transmission');
  if (counts.storage / total >= 0.6) return getRackProfile('storage');
  if (counts.server / total >= 0.6) return getRackProfile('server');
  if (counts.cabling / total >= 0.6) return getRackProfile('cabling');
  if (counts.security / total >= 0.6) return getRackProfile('security');
  if (counts.network / total >= 0.65) return getRackProfile('network-high-density');
  return getRackProfile('integrated');
}
