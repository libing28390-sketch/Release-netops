import { describe, expect, it } from 'vitest';
import {
  getIPAddressRegisteredPrefixLabel,
  getIPAddressSourceLabel,
  getIPAddressTimestampPresentation,
} from './ipAddressTablePresentation';

describe('IP address table timestamp presentation', () => {
  it('labels persisted interface CLI rows as IPAM source records', () => {
    expect(getIPAddressSourceLabel({ source: 'interface_cli' }, true)).toBe('接口采集');
    expect(getIPAddressSourceLabel({ source: 'interface_cli' }, false)).toBe('Interface collection');
  });

  it('labels discovery timestamps as discovery and preserves the timestamp timezone', () => {
    expect(getIPAddressTimestampPresentation({
      discovered_last_seen: '2026-10-28T08:30:00Z',
      last_seen: '2026-10-27T08:30:00Z',
      updated_at: '2026-10-28T09:00:00Z',
    }, true)).toEqual({ kind: 'discovered', label: '最近发现', value: '2026-10-28 08:30:00Z' });
  });

  it('uses the update timestamp for a manual address without discovery time', () => {
    expect(getIPAddressTimestampPresentation({
      source: 'manual',
      last_seen: '2026-10-27T09:00:00Z',
      created_at: '2026-10-27T09:00:00Z',
      updated_at: '2026-10-28T09:00:00+08:00',
    }, false)).toEqual({ kind: 'updated', label: 'Updated', value: '2026-10-28 09:00:00+08:00' });
  });

  it('does not treat a manual row last_seen value as discovery when its observed timestamp is absent', () => {
    expect(getIPAddressTimestampPresentation({
      source: 'manual+discovered', last_seen: '2026-10-27T09:00:00Z', updated_at: '2026-10-28T09:00:00Z',
    }, true)).toEqual({ kind: 'updated', label: '更新时间', value: '2026-10-28 09:00:00Z' });
  });

  it('keeps persisted interface CLI source time distinct from updates', () => {
    expect(getIPAddressTimestampPresentation({
      source: 'interface_cli', last_seen: '2026-10-28T08:30:00Z', updated_at: '2026-10-28T09:00:00Z',
    }, true)).toEqual({ kind: 'collected', label: '最近发现 / 采集', value: '2026-10-28 08:30:00Z' });
    expect(getIPAddressTimestampPresentation({ source: 'interface_cli', updated_at: '2026-10-28T09:00:00Z' }, true))
      .toEqual({ kind: 'missing', label: '无采集时间', value: '' });
  });

  it('shows prefix gateways as not collected and distinguishes general missing timestamps', () => {
    expect(getIPAddressTimestampPresentation({ source: 'prefix_gateway', updated_at: '2026-10-28T09:00:00Z' }, true))
      .toEqual({ kind: 'missing', label: '未采集', value: '' });
    expect(getIPAddressTimestampPresentation({ source: 'manual' }, false))
      .toEqual({ kind: 'missing', label: 'No timestamp', value: '' });
  });
});

describe('IPAM registered prefix display', () => {
  it('shows only the registered prefix and labels a ledger row without a linked prefix', () => {
    expect(getIPAddressRegisteredPrefixLabel(' 10.254.100.0/24 ', true)).toBe('10.254.100.0/24');
    expect(getIPAddressRegisteredPrefixLabel('', true)).toBe('未关联网段');
    expect(getIPAddressRegisteredPrefixLabel(null, false)).toBe('No linked prefix');
  });
});
