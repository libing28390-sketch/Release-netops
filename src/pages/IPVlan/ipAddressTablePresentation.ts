export interface IPAddressTimestampSource {
  discovered_last_seen?: string | null;
  last_seen?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  source?: string | null;
  source_type?: string | null;
  is_discovered?: boolean;
  is_prefix_gateway?: boolean;
  is_virtual_gateway?: boolean;
}

export type IPAddressTimestampKind = 'discovered' | 'collected' | 'updated' | 'missing';

export function getIPAddressObservationStatus(
  address: { source?: string; has_interface_observation?: boolean; interface_admin_status?: string; interface_oper_status?: string },
  zh: boolean,
): { label: string; tone: 'success' | 'warning' | 'neutral' } | null {
  if (address.source === 'discovered') {
    return { label: zh ? '发现记录' : 'Observed', tone: 'neutral' };
  }
  if (address.source !== 'interface_cli' && !address.has_interface_observation) return null;
  const admin = address.interface_admin_status?.toLowerCase();
  const oper = address.interface_oper_status?.toLowerCase();
  if (admin === 'down' || oper === 'down') return { label: zh ? '接口 Down' : 'Interface Down', tone: 'warning' };
  if (admin === 'up' && oper === 'up') return { label: zh ? '接口 Up' : 'Interface Up', tone: 'success' };
  return { label: zh ? '接口状态未知' : 'Interface unknown', tone: 'neutral' };
}

export interface IPAddressTimestampPresentation {
  kind: IPAddressTimestampKind;
  label: string;
  value: string;
}

/** Prefix text on the IP address page comes only from the IPAM address ledger association. */
export function getIPAddressRegisteredPrefixLabel(prefix: string | null | undefined, zh: boolean): string {
  return prefix?.trim() || (zh ? '未关联网段' : 'No linked prefix');
}

export function getIPAddressSourceLabel(address: IPAddressTimestampSource, zh: boolean): string {
  if (address.source_type === 'interface_collection') return zh ? '接口生成台账' : 'Interface-generated record';
  if (address.source === 'manual+discovered') return zh ? 'IPAM + 采集' : 'IPAM + Discovery';
  if (address.source === 'interface_cli') return zh ? '接口采集' : 'Interface collection';
  if (address.source === 'prefix_gateway' || address.is_prefix_gateway) return zh ? '前缀网关' : 'Prefix gateway';
  if (address.source === 'discovered' || address.is_discovered) return zh ? '自动发现' : 'Discovered';
  if (address.source === 'manual') return zh ? 'IPAM 登记' : 'IPAM record';
  return address.is_virtual_gateway ? (zh ? '前缀配置' : 'Prefix config') : (zh ? 'IPAM 登记' : 'IPAM record');
}

const firstTimestamp = (...values: Array<string | null | undefined>): string =>
  values.find((value) => typeof value === 'string' && value.trim().length > 0)?.trim() || '';

const formatTimestamp = (value: string): string => value.replace('T', ' ');

const pad2 = (value: number): string => String(value).padStart(2, '0');

/**
 * Render a stored (usually UTC) timestamp in the browser's local time zone,
 * e.g. "2026-11-11 13:57:51+00:00" -> "2026-11-11 21:57:51" in Asia/Shanghai.
 * Values without an explicit offset are shown unchanged because their zone is unknown.
 */
export function formatIPAddressLocalTime(value: string | null | undefined): string {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const isoLike = raw.replace(' ', 'T');
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(isoLike)) return formatTimestamp(raw);
  const date = new Date(isoLike);
  if (Number.isNaN(date.getTime())) return formatTimestamp(raw);
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} `
    + `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
}

/** Keep discovery timestamps separate from record update times and missing collection data. */
export function getIPAddressTimestampPresentation(
  address: IPAddressTimestampSource,
  zh: boolean,
): IPAddressTimestampPresentation {
  if (address.source === 'interface_cli' || address.source_type === 'interface_collection') {
    const collectedAt = firstTimestamp(address.discovered_last_seen, address.last_seen);
    return collectedAt
      ? {
        kind: 'collected',
        label: zh ? '最近发现 / 采集' : 'Last discovered / collected',
        value: formatTimestamp(collectedAt),
      }
      : {
        kind: 'missing',
        label: zh ? '无采集时间' : 'No collection time',
        value: '',
      };
  }

  const hasDiscoverySource = address.is_discovered
    || address.source === 'discovered';
  const discoveredAt = firstTimestamp(address.discovered_last_seen, hasDiscoverySource ? address.last_seen : undefined);
  if (discoveredAt) {
    return {
      kind: 'discovered',
      label: zh ? '最近发现' : 'Last discovered',
      value: formatTimestamp(discoveredAt),
    };
  }

  const isPrefixGateway = address.source === 'prefix_gateway' || address.is_prefix_gateway || address.is_virtual_gateway;
  if (isPrefixGateway) {
    return {
      kind: 'missing',
      label: zh ? '未采集' : 'Not collected',
      value: '',
    };
  }

  const updatedAt = firstTimestamp(address.updated_at);
  if (updatedAt) {
    return {
      kind: 'updated',
      label: zh ? '更新时间' : 'Updated',
      value: formatTimestamp(updatedAt),
    };
  }

  return {
    kind: 'missing',
    label: zh ? '无时间记录' : 'No timestamp',
    value: '',
  };
}
