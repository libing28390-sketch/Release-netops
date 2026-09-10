const LOCATION_TYPE_LABELS: Record<string, [string, string]> = {
  PATH_TRACED: ['已定位到接入端口', 'Access port located'],
  ARP_DIRECT: ['ARP 来源接口', 'ARP source interface'],
  CACHED_ENDPOINT: ['缓存端点', 'Cached endpoint'],
  TRACE_INCOMPLETE: ['链路追踪未完成', 'Path trace incomplete'],
  MAC_TABLE_NO_PORT: ['MAC 已命中但缺少端口', 'MAC hit without port'],
};

export function formatLocationType(type: string | undefined, zhLang: boolean): string {
  const normalized = String(type || '').trim();
  if (!normalized) return '';
  const labels = LOCATION_TYPE_LABELS[normalized];
  return labels ? labels[zhLang ? 0 : 1] : normalized;
}
