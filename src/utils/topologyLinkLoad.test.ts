import { describe, expect, it } from 'vitest';
import { formatTopologyLinkUtilization, getTopologyLinkLoadTier, getTopologyLinkUtilization, TOPOLOGY_LINK_LOAD_TIERS } from './topologyLinkLoad';

describe('topology link load', () => {
  it('distinguishes a small nonzero reading from zero', () => {
    expect(formatTopologyLinkUtilization(0)).toBe('0%');
    expect(formatTopologyLinkUtilization(0.02)).toBe('<0.1%');
    expect(formatTopologyLinkUtilization(84.99)).toBe('84.9%');
  });
  it('uses the higher measured endpoint and preserves a valid zero', () => {
    expect(getTopologyLinkUtilization({
      source_interface_snapshot: { maxUtilizationPct: 52 },
      target_interface_snapshot: { maxUtilizationPct: 89 },
    })).toBe(89);
    expect(getTopologyLinkUtilization({
      source_interface_snapshot: { maxUtilizationPct: 0 },
      target_interface_snapshot: null,
    })).toBe(0);
  });

  it('excludes missing, invalid, down, and stale measurements', () => {
    expect(getTopologyLinkUtilization({
      source_interface_snapshot: { maxUtilizationPct: Number.NaN },
      target_interface_snapshot: { status: 'down', maxUtilizationPct: 95 },
    })).toBeNull();
    for (const operational_state of ['down', 'stale']) {
      expect(getTopologyLinkUtilization({
        operational_state,
        source_interface_snapshot: { maxUtilizationPct: 95 },
      })).toBeNull();
    }
  });

  it('uses inclusive lower boundaries for orange and red', () => {
    expect(getTopologyLinkLoadTier(null)).toBe(TOPOLOGY_LINK_LOAD_TIERS[3]);
    expect(getTopologyLinkLoadTier(69.99)).toBe(TOPOLOGY_LINK_LOAD_TIERS[0]);
    expect(getTopologyLinkLoadTier(70)).toBe(TOPOLOGY_LINK_LOAD_TIERS[1]);
    expect(getTopologyLinkLoadTier(84.99)).toBe(TOPOLOGY_LINK_LOAD_TIERS[1]);
    expect(getTopologyLinkLoadTier(85)).toBe(TOPOLOGY_LINK_LOAD_TIERS[2]);
  });
});
