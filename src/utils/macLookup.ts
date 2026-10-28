export type MacLookupStatus =
  | 'not_attempted'
  | 'disabled'
  | 'unsupported'
  | 'query_failed'
  | 'not_found'
  | 'found';

export interface MacLookupInfo {
  status: MacLookupStatus;
  device_id?: string;
  device?: string;
  command?: string;
  record_count?: number;
  port?: string;
  vlan?: string;
  reason?: string;
  error_code?: string;
  attempt_count?: number;
  last_status?: MacLookupStatus;
  last_device_id?: string;
  last_device?: string;
  last_reason?: string;
  last_error_code?: string;
}

export function formatMacLookupMessage(lookup: MacLookupInfo | undefined, zhLang: boolean): string {
  const status = lookup?.status;
  if (status === 'disabled') {
    return zhLang
      ? '该设备未开启 MAC 表查询，当前定位基于 ARP 记录'
      : 'MAC table lookup is disabled for this device; location is based on ARP';
  }
  if (status === 'unsupported') {
    return zhLang
      ? '该设备不支持 MAC 表查询，当前定位基于 ARP 记录'
      : 'This device does not support MAC table lookup; location is based on ARP';
  }
  if (status === 'query_failed') {
    return zhLang
      ? 'MAC 表查询失败，当前定位基于 ARP 记录'
      : 'MAC table lookup failed; location is based on ARP';
  }
  if (status === 'not_found') {
    return zhLang
      ? '已查询 MAC 表但未找到该 MAC，当前定位基于 ARP 记录'
      : 'The MAC table was queried but did not contain this MAC; location is based on ARP';
  }
  if (status === 'found') {
    const device = lookup?.device || '';
    const port = lookup?.port || '';
    const vlan = lookup?.vlan ? ` / VLAN ${lookup.vlan}` : '';
    if (device && port) {
      return zhLang
        ? `MAC 表已命中：${device} / ${port}${vlan}`
        : `MAC table hit: ${device} / ${port}${vlan}`;
    }
    return zhLang ? 'MAC 表已命中目标地址' : 'MAC table contains the target MAC';
  }
  return '';
}

export function macLookupStatusLabel(status: MacLookupStatus | undefined, zhLang: boolean): string {
  const labels: Record<MacLookupStatus, [string, string]> = {
    not_attempted: ['未执行', 'Not attempted'],
    disabled: ['未开启', 'Disabled'],
    unsupported: ['设备不支持', 'Unsupported'],
    query_failed: ['查询失败', 'Query failed'],
    not_found: ['已查询未命中', 'Queried / not found'],
    found: ['MAC 表命中', 'MAC table hit'],
  };
  const normalizedStatus: MacLookupStatus = status && Object.prototype.hasOwnProperty.call(labels, status)
    ? status
    : 'not_attempted';
  return labels[normalizedStatus][zhLang ? 0 : 1];
}
