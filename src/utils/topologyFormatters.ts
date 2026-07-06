import type { TopologyOperationalState } from './topologyCore';

export const formatTopologyPort = (value: string | undefined, language: string) => {
  const raw = String(value || '').trim();
  if (!raw) return language === 'zh' ? '未知接口' : 'Unknown Port';
  return raw
    .replace(/^GigabitEthernet/i, 'Gi')
    .replace(/^TenGigabitEthernet/i, 'Te')
    .replace(/^TwentyFiveGigE/i, 'Tw')
    .replace(/^FortyGigabitEthernet/i, 'Fo')
    .replace(/^HundredGigabitEthernet/i, 'Hu')
    .replace(/^Ethernet/i, 'Eth')
    .replace(/^Port-channel/i, 'Po')
    .replace(/^Loopback/i, 'Lo');
};

export const formatTopologyEvidenceLabel = (value: string, language: string) => {
  const normalized = String(value || '').trim().toLowerCase();
  if (!normalized) return language === 'zh' ? '未知来源' : 'Unknown Source';
  if (normalized === 'lldp') return 'LLDP';
  if (normalized === 'cdp') return 'CDP';
  if (normalized === 'snmp') return 'SNMP';
  if (normalized === 'arp') return 'ARP';
  if (normalized === 'mac') return 'MAC';
  return normalized.toUpperCase();
};

export const formatTopologyOperationalState = (state: TopologyOperationalState | undefined, language: string) => {
  if (language === 'zh') {
    if (state === 'up') return '正常';
    if (state === 'degraded') return '退化';
    if (state === 'down') return '中断';
    if (state === 'stale') return '陈旧';
    return '未知';
  }
  if (state === 'up') return 'Up';
  if (state === 'degraded') return 'Degraded';
  if (state === 'down') return 'Down';
  if (state === 'stale') return 'Stale';
  return 'Unknown';
};

export const formatTopologyLastSeen = (value: string | undefined, language: string) => {
  if (!value) return language === 'zh' ? '未知' : 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return language === 'zh' ? '未知' : 'Unknown';
  return date.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false });
};
