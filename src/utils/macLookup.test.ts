import { describe, expect, it } from 'vitest';
import { formatMacLookupMessage, macLookupStatusLabel } from './macLookup';
import { formatLocationType } from './ipLocator';

describe('MAC lookup status presentation', () => {
  it.each([
    ['disabled', '该设备未开启 MAC 表查询，当前定位基于 ARP 记录'],
    ['unsupported', '该设备不支持 MAC 表查询，当前定位基于 ARP 记录'],
    ['query_failed', 'MAC 表查询失败，当前定位基于 ARP 记录'],
    ['not_found', '已查询 MAC 表但未找到该 MAC，当前定位基于 ARP 记录'],
  ] as const)('renders %s as a distinct ARP fallback message', (status, message) => {
    expect(formatMacLookupMessage({ status }, true)).toBe(message);
  });

  it('renders the matched device, port, and VLAN', () => {
    expect(formatMacLookupMessage({
      status: 'found',
      device: 'S6850-5',
      port: 'GE1/0/2',
      vlan: '7',
    }, true)).toBe('MAC 表已命中：S6850-5 / GE1/0/2 / VLAN 7');
  });

  it('provides stable status labels for the result chip', () => {
    expect(macLookupStatusLabel('unsupported', true)).toBe('设备不支持');
    expect(macLookupStatusLabel('found', false)).toBe('MAC table hit');
  });

  it('translates internal location enums for the user-facing card', () => {
    expect(formatLocationType('PATH_TRACED', true)).toBe('已定位到接入端口');
    expect(formatLocationType('PATH_TRACED', false)).toBe('Access port located');
  });
});
