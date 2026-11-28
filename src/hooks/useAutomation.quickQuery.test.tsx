import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useAutomation } from './useAutomation';

afterEach(() => vi.unstubAllGlobals());

it('keeps the selected device identity and reports a failed business result', async () => {
  const device = { id: 'device-a', hostname: 'switch-a', ip_address: '192.0.2.1', platform: 'h3c_comware' };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      categories: [{
        success: false,
        commands: ['display version'],
        records: [{ Hostname: 'parsed-name', 'IP Address': '192.0.2.99', version: '3.40' }],
        parse_status: 'matched',
      }],
    }),
  }));
  const { result, unmount } = renderHook(() => useAutomation({
    currentUser: { role: 'Administrator' } as never,
    isAuthenticated: false,
    language: 'zh',
    showToast: vi.fn(),
    navigate: vi.fn(),
    setSelectedDevice: vi.fn(),
    devices: [device],
    selectedDevice: device,
    activeTab: 'assets',
    automationPage: '',
  }));

  await act(async () => result.current.runQuickQuery('version', 'display version'));

  expect(result.current.quickQueryStructured.categories[0].records[0]).toMatchObject({
    Hostname: 'switch-a', 'IP Address': '192.0.2.1', version: '3.40',
  });
  expect(result.current.quickQueryStructured.device_results[0].request_status).toBe('failed');
  unmount();
});
