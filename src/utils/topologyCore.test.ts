import { describe, expect, it } from 'vitest';
import { normalizeTopologyPort } from './topologyCore';

describe('topology port matching', () => {
  it.each([
    ['FGE1/0/54', 'FortyGigE1/0/54', 'fo1/0/54'],
    ['40GE1/0/54', 'Forty-GigabitEthernet1/0/54', 'fo1/0/54'],
    ['XGE1/0/49', 'Ten-GigabitEthernet1/0/49', 'te1/0/49'],
    ['10GE1/0/49', 'TenGigE1/0/49', 'te1/0/49'],
  ])('matches discovery port %s and monitoring port %s', (discovery, monitoring, key) => {
    expect(normalizeTopologyPort(discovery)).toBe(key);
    expect(normalizeTopologyPort(monitoring)).toBe(key);
  });
});
