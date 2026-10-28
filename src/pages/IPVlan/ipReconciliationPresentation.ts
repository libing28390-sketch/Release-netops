export type ReconciliationTab = 'undocumented' | 'mismatched' | 'stale' | 'never_observed' | 'unscoped' | 'unavailable';
export type ReconciliationEmptyState =
  | 'current_page_empty'
  | 'search_no_results'
  | 'input_counts_unknown'
  | 'no_comparable_data'
  | 'cache_unavailable'
  | 'coverage_incomplete'
  | 'no_differences';

export interface ReconciliationInputSummary {
  endpoint_cache_fresh?: boolean;
  allocated_ipam_address_count?: number;
  active_endpoint_count?: number;
  interface_snapshot_ip_count?: number;
  total_unscoped?: number;
  coverage_status?: string;
  coverage_reason?: string;
}

export interface ReconciliationEndpointSeenSummary {
  latest_active_endpoint_seen?: string | null;
  latest_endpoint_seen?: string | null;
}

export const RECONCILIATION_TABS: ReconciliationTab[] = [
  'undocumented', 'mismatched', 'stale', 'never_observed', 'unscoped', 'unavailable',
];

export function getLatestActiveEndpointSeen(summary: ReconciliationEndpointSeenSummary): string {
  if (Object.prototype.hasOwnProperty.call(summary, 'latest_active_endpoint_seen')) {
    return summary.latest_active_endpoint_seen || '';
  }
  return summary.latest_endpoint_seen || '';
}

export function getReconciliationCategoryCount(summary: Record<string, unknown>, tab: ReconciliationTab): number {
  const countKey: Record<ReconciliationTab, string> = {
    undocumented: 'total_undocumented',
    mismatched: 'total_mismatched',
    stale: 'total_stale',
    never_observed: 'total_never_observed',
    unscoped: 'total_unscoped',
    unavailable: 'total_unavailable',
  };
  const value = summary[countKey[tab]];
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

export function getReconciliationEmptyState(
  summary: ReconciliationInputSummary,
  input: { resultTotal: number; search: string },
): ReconciliationEmptyState {
  if (input.resultTotal > 0) return 'current_page_empty';
  if (input.search.trim()) return 'search_no_results';
  if (summary.allocated_ipam_address_count === undefined || summary.active_endpoint_count === undefined) {
    return 'input_counts_unknown';
  }
  if (summary.allocated_ipam_address_count === 0 && summary.active_endpoint_count === 0) return 'no_comparable_data';
  if (summary.allocated_ipam_address_count > 0 && summary.active_endpoint_count === 0) return 'cache_unavailable';
  if (summary.coverage_status && !['complete', 'fresh', 'available', 'ok'].includes(summary.coverage_status.toLowerCase())) {
    return 'coverage_incomplete';
  }
  if (summary.coverage_status === undefined && summary.endpoint_cache_fresh === false) return 'cache_unavailable';
  if ((summary.total_unscoped || 0) > 0) return 'coverage_incomplete';
  return 'no_differences';
}

export function getReconciliationEmptyMessage(
  state: ReconciliationEmptyState,
  tab: ReconciliationTab,
  zh: boolean,
  coverageReason = '',
): string {
  if (state === 'current_page_empty') return zh ? '此页没有记录，请检查分页或刷新结果。' : 'This page has no rows. Check pagination or refresh the results.';
  if (state === 'search_no_results') return zh ? '没有匹配当前搜索的记录；清除搜索可查看完整结果。' : 'No rows match the current search. Clear the search to see the full result set.';
  if (state === 'input_counts_unknown') return zh ? '暂时无法获取对账输入数量，请刷新重试。' : 'Comparison input counts are unavailable. Refresh to retry.';
  if (state === 'no_comparable_data') return zh ? '当前没有可比较的 IPAM 地址和发现记录；接口采集快照不属于本页对账来源。' : 'There are no comparable IPAM addresses or discovery records. Interface collection snapshots are not a source for this reconciliation.';
  if (state === 'cache_unavailable') return zh ? '当前没有可用的活动发现记录，暂时无法完成对账。接口采集快照不属于本页对账来源。' : 'No current active discovery records are available, so reconciliation cannot be completed. Interface collection snapshots are not a source for this page.';
  if (state === 'coverage_incomplete') {
    const reason = coverageReason.trim();
    return zh
      ? `发现覆盖范围不完整，不能据此判定无差异。${reason ? `原因：${reason}` : '请检查来源采集状态和待确认范围。'}`
      : `Discovery coverage is incomplete; this cannot be treated as no differences. ${reason ? `Reason: ${reason}` : 'Review source collection status and unresolved scope.'}`;
  }
  const labels: Record<ReconciliationTab, [string, string]> = {
    undocumented: ['未发现漏登记 IP。', 'No undocumented IPs found.'],
    mismatched: ['未发现 IPAM 登记与当前观察不一致。', 'No IPAM registration mismatches found.'],
    stale: ['未发现达到长期未发现条件的登记 IP。', 'No registered IPs meet the stale threshold.'],
    never_observed: ['未发现登记后从未观察到的 IP。', 'No registered IPs have never been observed.'],
    unscoped: ['没有归属待确认的观察记录。', 'No observations need scope confirmation.'],
    unavailable: ['当前没有来源不可用记录。', 'No unavailable sources were reported.'],
  };
  return labels[tab][zh ? 0 : 1];
}

export interface MacCalibrationCandidate {
  observation_id?: string | null;
  ipam_address_id?: string | null;
  ipam_mac?: string | null;
  observed_mac?: string | null;
  observed_at?: string | null;
  mac_mismatch?: boolean;
  scope_status?: string | null;
  evidence_status?: string | null;
  timestamp_status?: string | null;
  calibration_safe?: boolean;
}

export function canCalibrateMac(item: MacCalibrationCandidate): boolean {
  return Boolean(
    item.observation_id
    && item.ipam_address_id
    && item.ipam_mac?.trim()
    && item.observed_mac?.trim()
    && item.observed_at
    && item.mac_mismatch === true
    && item.scope_status === 'resolved'
    && item.evidence_status === 'recent'
    && item.timestamp_status === 'valid'
    && item.calibration_safe === true,
  );
}
