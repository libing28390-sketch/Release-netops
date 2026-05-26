import type { Device } from '../../types';
import type { ScenarioVariable } from './types';
import { VENDOR_MAP } from './constants';

export const getVendor = (p: string) => VENDOR_MAP[p] || 'Other';

export const getDeviceCategory = (d: Device): 'network' | 'server' => {
  const p = (d.platform || '').toLowerCase();
  const serverKeywords = ['linux', 'ubuntu', 'centos', 'windows', 'debian', 'redhat', 'esxi', 'docker', 'alma', 'rocky', 'oracle', 'server', 'service'];
  const r = (d.role || '').toLowerCase();
  if (serverKeywords.some(kw => p.includes(kw)) || serverKeywords.some(kw => r.includes(kw))) {
    return 'server';
  }
  return 'network';
};

export const classifyVarGroup = (v: ScenarioVariable) => {
  const text = `${v?.key || ''} ${v?.label || ''}`.toLowerCase();
  if (/ip|prefix|mask|gateway|network|neighbor|next_hop|peer/.test(text)) return 'address';
  if (/interface|port|intf|vlan/.test(text)) return 'interface';
  if (/asn|as\b|route|bgp|ospf|policy|metric|community/.test(text)) return 'routing';
  return 'general';
};
