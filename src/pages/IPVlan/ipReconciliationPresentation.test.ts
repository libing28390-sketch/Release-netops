import { describe, expect, it } from 'vitest';
import {
  canCalibrateMac,
  getLatestActiveEndpointSeen,
  getReconciliationCategoryCount,
  getReconciliationEmptyMessage,
  getReconciliationEmptyState,
  RECONCILIATION_TABS,
} from './ipReconciliationPresentation';

describe('IPAM reconciliation categories', () => {
  it('covers all six server-side tabs and uses the matching summary counts', () => {
    const summary = {
      total_undocumented: 1,
      total_mismatched: 2,
      total_stale: 3,
      total_never_observed: 4,
      total_unscoped: 5,
      total_unavailable: 6,
    };
    expect(RECONCILIATION_TABS).toEqual(['undocumented', 'mismatched', 'stale', 'never_observed', 'unscoped', 'unavailable']);
    expect(RECONCILIATION_TABS.map((tab) => getReconciliationCategoryCount(summary, tab))).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it.each(RECONCILIATION_TABS)('provides a category-specific empty-state message for %s', (tab) => {
    const state = getReconciliationEmptyState({
      allocated_ipam_address_count: 8,
      active_endpoint_count: 12,
      endpoint_cache_fresh: true,
      coverage_status: 'complete',
    }, { resultTotal: 0, search: '' });
    expect(state).toBe('no_differences');
    expect(getReconciliationEmptyMessage(state, tab, true)).not.toBe('');
  });

  it('never claims no differences when discovery coverage is partial or unavailable', () => {
    const state = getReconciliationEmptyState({
      allocated_ipam_address_count: 8,
      active_endpoint_count: 12,
      coverage_status: 'partial',
      coverage_reason: '2 sources failed',
    }, { resultTotal: 0, search: '' });
    expect(state).toBe('coverage_incomplete');
    expect(getReconciliationEmptyMessage(state, 'undocumented', true, '2 sources failed')).toContain('2 sources failed');
  });

  it('keeps missing inputs and empty discovery separate from no differences', () => {
    expect(getReconciliationEmptyState({ endpoint_cache_fresh: false }, { resultTotal: 0, search: '' })).toBe('input_counts_unknown');
    expect(getReconciliationEmptyState({
      endpoint_cache_fresh: false,
      allocated_ipam_address_count: 0,
      active_endpoint_count: 0,
      interface_snapshot_ip_count: 55,
    }, { resultTotal: 0, search: '' })).toBe('no_comparable_data');
    expect(getReconciliationEmptyMessage('no_comparable_data', 'undocumented', true)).toContain('接口采集快照不属于');
  });

  it('reports active endpoints first and only falls back to the legacy timestamp when absent', () => {
    expect(getLatestActiveEndpointSeen({ latest_active_endpoint_seen: 'active', latest_endpoint_seen: 'legacy' })).toBe('active');
    expect(getLatestActiveEndpointSeen({ latest_active_endpoint_seen: '', latest_endpoint_seen: 'legacy' })).toBe('');
    expect(getLatestActiveEndpointSeen({ latest_endpoint_seen: 'legacy' })).toBe('legacy');
  });
});

describe('MAC calibration safety gate', () => {
  const safeCandidate = {
    observation_id: 'observation-1',
    ipam_address_id: 'address-1',
    ipam_mac: '00:11:22:33:44:55',
    observed_mac: '00:11:22:33:44:66',
    observed_at: '2026-10-28T10:00:00Z',
    mac_mismatch: true,
    scope_status: 'resolved',
    evidence_status: 'recent',
    timestamp_status: 'valid',
    calibration_safe: true,
  };

  it('allows only a current, unique, resolved MAC mismatch with version values', () => {
    expect(canCalibrateMac(safeCandidate)).toBe(true);
    expect(canCalibrateMac({ ...safeCandidate, evidence_status: 'historical' })).toBe(false);
    expect(canCalibrateMac({ ...safeCandidate, timestamp_status: 'future' })).toBe(false);
    expect(canCalibrateMac({ ...safeCandidate, calibration_safe: false })).toBe(false);
    expect(canCalibrateMac({ ...safeCandidate, calibration_safe: undefined })).toBe(false);
    expect(canCalibrateMac({ ...safeCandidate, scope_status: 'scope_pending' })).toBe(false);
    expect(canCalibrateMac({ ...safeCandidate, observation_id: undefined })).toBe(false);
    expect(canCalibrateMac({ ...safeCandidate, mac_mismatch: false })).toBe(false);
  });
});
