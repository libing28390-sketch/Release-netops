export const DEVICE_TYPES = [
  { value: '', label: { zh: '未分类', en: 'Unclassified' }, icon: '—', color: 'text-black/40' },
  { value: 'server', label: { zh: '服务器', en: 'Server' }, icon: 'S', color: 'text-violet-600 bg-violet-50' },
  { value: 'switch', label: { zh: '交换机', en: 'Switch' }, icon: 'SW', color: 'text-blue-600 bg-blue-50' },
  { value: 'router', label: { zh: '路由器', en: 'Router' }, icon: 'R', color: 'text-emerald-600 bg-emerald-50' },
  { value: 'firewall', label: { zh: '防火墙', en: 'Firewall' }, icon: 'FW', color: 'text-red-600 bg-red-50' },
  { value: 'ap', label: { zh: 'AP', en: 'AP' }, icon: 'AP', color: 'text-cyan-600 bg-cyan-50' },
  { value: 'other', label: { zh: '其他', en: 'Other' }, icon: '?', color: 'text-gray-600 bg-gray-50' },
] as const;

export const COMMON_PREFIXES_V6 = [
  { prefix: 48, desc: '/48 — 65,536 /64' },
  { prefix: 64, desc: '/64 — LAN (18×10¹⁸)' },
  { prefix: 112, desc: '/112 — 65,534' },
  { prefix: 126, desc: '/126 — P2P (2)' },
  { prefix: 128, desc: '/128 — Host' },
] as const;

export const COMMON_PREFIXES_V4 = [
  { prefix: 8, desc: '/8 — 16,777,214 A' },
  { prefix: 16, desc: '/16 — 65,534 B' },
  { prefix: 24, desc: '/24 — 254 C' },
  { prefix: 25, desc: '/25 — 126' },
  { prefix: 26, desc: '/26 — 62' },
  { prefix: 27, desc: '/27 — 30' },
  { prefix: 28, desc: '/28 — 14' },
  { prefix: 29, desc: '/29 — 6' },
  { prefix: 30, desc: '/30 — 2 P2P' },
  { prefix: 32, desc: '/32 — Host' },
] as const;
