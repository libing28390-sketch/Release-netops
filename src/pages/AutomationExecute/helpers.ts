import type { Device } from '../../types';
import type { ScenarioVariable } from './types';
import { VENDOR_MAP } from './constants';

export const normalizeAutomationPlatform = (platform?: string | null): string => {
  const p = String(platform || '').toLowerCase().trim();
  const aliases: Record<string, string> = {
    cisco: 'cisco_ios',
    ios: 'cisco_ios',
    iosxe: 'cisco_ios',
    cisco_iosxe: 'cisco_ios',
    nxos: 'cisco_nxos',
    nexus: 'cisco_nxos',
    huawei: 'huawei_vrp',
    huawei_vrpv8: 'huawei_vrpv8',
    vrp: 'huawei_vrp',
    ce: 'huawei_vrp',
    ce_vrp: 'huawei_vrp',
    ne: 'huawei_vrp',
    h3c: 'h3c_comware',
    comware: 'h3c_comware',
    hp_comware: 'hp_comware',
    h3c_comware9: 'h3c_comware9',
    juniper: 'juniper_junos',
    junos: 'juniper_junos',
    arista: 'arista_eos',
    eos: 'arista_eos',
    ruijie: 'ruijie_rgos',
    rgos: 'ruijie_rgos',
  };
  return aliases[p] || p;
};

const platformFallbacks: Record<string, string[]> = {
  cisco_xe: ['cisco_ios'],
  huawei_vrpv8: ['huawei_vrp'],
  hp_comware: ['h3c_comware'],
  h3c_comware9: ['h3c_comware'],
};

/** A scenario may define a family phase while assets keep a precise parser key. */
export const isAutomationPlatformSupported = (
  platform: string | null | undefined,
  supportedPlatforms: string[] | null | undefined,
): boolean => {
  if (!supportedPlatforms || supportedPlatforms.length === 0) return true;
  const normalized = normalizeAutomationPlatform(platform);
  const candidates = [normalized, ...(platformFallbacks[normalized] || [])];
  return supportedPlatforms.some((item) => candidates.includes(normalizeAutomationPlatform(item)));
};

export const getVendor = (d: Device | string) => {
  if (typeof d === 'string') {
    return VENDOR_MAP[normalizeAutomationPlatform(d)] || VENDOR_MAP[d] || 'Other';
  }
  return d.vendor || VENDOR_MAP[normalizeAutomationPlatform(d.platform)] || VENDOR_MAP[d.platform || ''] || 'Other';
};

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
