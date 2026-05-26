import { COMMON_PREFIXES_V4, COMMON_PREFIXES_V6 } from './constants';

export const isValidIPv4 = (ip: string): boolean => {
  const parts = ip.split('.');
  if (parts.length !== 4) return false;
  return parts.every(p => {
    const n = Number(p);
    return Number.isInteger(n) && n >= 0 && n <= 255 && p === String(n);
  });
};

export const isValidIPv6 = (ip: string): boolean => {
  if (!ip || ip.length > 45) return false;
  const dblColon = ip.split('::');
  if (dblColon.length > 2) return false;
  const parts = ip.split(':');
  if (dblColon.length === 2) {
    const left = dblColon[0] ? dblColon[0].split(':') : [];
    const right = dblColon[1] ? dblColon[1].split(':') : [];
    if (left.length + right.length > 7) return false;
    return [...left, ...right].every(g => /^[0-9a-fA-F]{1,4}$/.test(g));
  }
  return parts.length === 8 && parts.every(g => /^[0-9a-fA-F]{1,4}$/.test(g));
};

export const isValidIP = (ip: string): boolean => isValidIPv4(ip) || isValidIPv6(ip);

export const detectIPVersion = (ip: string): 4 | 6 | 0 => isValidIPv4(ip) ? 4 : isValidIPv6(ip) ? 6 : 0;

export const toNum = (a: string): number => a.split('.').reduce((acc, o) => (acc << 8) + Number(o), 0) >>> 0;

export const ipInSubnet = (ip: string, network: string, prefixLen: number): boolean => {
  if (isValidIPv4(ip) && isValidIPv4(network)) {
    const mask = prefixLen === 0 ? 0 : (0xFFFFFFFF << (32 - prefixLen)) >>> 0;
    return (toNum(ip) & mask) === (toNum(network) & mask);
  }
  if (isValidIPv6(ip) && isValidIPv6(network)) {
    const expand = (v6: string): string => {
      const halves = v6.split('::');
      let groups: string[];
      if (halves.length === 2) {
        const left = halves[0] ? halves[0].split(':') : [];
        const right = halves[1] ? halves[1].split(':') : [];
        const fill = 8 - left.length - right.length;
        groups = [...left, ...Array(fill).fill('0'), ...right];
      } else {
        groups = v6.split(':');
      }
      return groups.map(g => g.padStart(4, '0')).join('');
    };
    const ipHex = expand(ip);
    const netHex = expand(network);
    const fullBits = ipHex.length * 4; // 128
    if (prefixLen < 0 || prefixLen > fullBits) return false;
    const ipBin = BigInt('0x' + ipHex);
    const netBin = BigInt('0x' + netHex);
    const shift = BigInt(fullBits - prefixLen);
    return (ipBin >> shift) === (netBin >> shift);
  }
  return false;
};

export const alignedNetwork = (ip: string, prefixLen: number): string => {
  if (isValidIPv4(ip)) {
    const mask = prefixLen === 0 ? 0 : (0xFFFFFFFF << (32 - prefixLen)) >>> 0;
    const net = (toNum(ip) & mask) >>> 0;
    return [(net >>> 24) & 0xFF, (net >>> 16) & 0xFF, (net >>> 8) & 0xFF, net & 0xFF].join('.');
  }
  return ip;
};

export const isValidVlanId = (v: string): boolean => {
  if (!v) return true;
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 && n <= 4094;
};

export const maxPrefix = (network: string): number => isValidIPv6(network) ? 128 : 32;

export const isValidPrefixLen = (v: number, network?: string): boolean => {
  const max = network && isValidIPv6(network) ? 128 : 32;
  return Number.isInteger(v) && v >= 1 && v <= max;
};

export const subnetSizeInfo = (prefixLen: number, isV6: boolean): { hosts: string; label: string } => {
  if (isV6) {
    const bits = 128 - prefixLen;
    if (bits <= 0) return { hosts: '1', label: '' };
    if (bits <= 53) {
      const n = 2 ** bits;
      return { hosts: n.toLocaleString(), label: `/${prefixLen}` };
    }
    return { hosts: `2^${bits}`, label: `/${prefixLen}` };
  }
  if (prefixLen >= 31) return { hosts: prefixLen === 32 ? '1' : '2', label: '' };
  const n = 2 ** (32 - prefixLen) - 2;
  return { hosts: n.toLocaleString(), label: '' };
};

export const commonPrefixes = (isV6: boolean) => isV6 ? COMMON_PREFIXES_V6 : COMMON_PREFIXES_V4;

export const utilColor = (pct: number): string => pct >= 90 ? 'text-red-600' : pct >= 80 ? 'text-orange-500' : pct >= 50 ? 'text-[#00172D]' : 'text-emerald-600';

export const utilBarColor = (pct: number): string => pct >= 90 ? '#ef4444' : pct >= 80 ? '#f97316' : pct >= 50 ? '#00bceb' : '#10b981';
