import { describe, expect, it } from 'vitest';
import { buildTopologyGraphLinks, getTopologyLinkEvidenceDash } from './topologyGraphLinks';

describe('buildTopologyGraphLinks', () => {
  it('preserves distinct physical links between the same devices', () => {
    const devices = [{ id: 'a' }, { id: 'b' }];
    const links = [
      { id: 'link-1', source_device_id: 'a', target_device_id: 'b', source_port: 'GE1/0/1', target_port: 'GE1/0/2' },
      { id: 'link-2', source_device_id: 'a', target_device_id: 'b', source_port: 'GE1/0/2', target_port: 'GE1/0/1' },
    ];

    const graphLinks = buildTopologyGraphLinks(devices, links);

    expect(graphLinks).toHaveLength(2);
    expect(graphLinks.map((link) => link.id)).toEqual(['link-1', 'link-2']);
    expect(graphLinks.every((link) => link.source === devices[0] && link.target === devices[1])).toBe(true);
  });

  it('skips a link only when one of its endpoint devices is absent', () => {
    const devices = [{ id: 'a' }, { id: 'b' }];
    const links = [
      { id: 'visible', source_device_id: 'a', target_device_id: 'b' },
      { id: 'missing-peer', source_device_id: 'a', target_device_id: 'unknown' },
    ];

    expect(buildTopologyGraphLinks(devices, links).map((link) => link.id)).toEqual(['visible']);
  });
});

describe('getTopologyLinkEvidenceDash', () => {
  it('uses a solid line only for mutual confirmation and one dashed pattern otherwise', () => {
    expect(getTopologyLinkEvidenceDash({ evidence_status: 'bidirectional_confirmed' })).toBe('');
    expect(getTopologyLinkEvidenceDash({ evidence_status: 'single_sided_evidence' })).toBe('6,5');
    expect(getTopologyLinkEvidenceDash({ evidence_status: 'neighbor_mismatch' })).toBe('6,5');
    expect(getTopologyLinkEvidenceDash({ evidence_status: 'stale' })).toBe('6,5');
    expect(getTopologyLinkEvidenceDash({ evidence_status: 'unknown' })).toBe('6,5');
    expect(getTopologyLinkEvidenceDash({ reverse_confirmed: true })).toBe('');
    expect(getTopologyLinkEvidenceDash({ metadata: { reverse_seen: true } })).toBe('');
  });
});
