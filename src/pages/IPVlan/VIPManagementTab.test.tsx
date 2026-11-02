import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import VIPManagementTab from './VIPManagementTab';

const response = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;

describe('VIPManagementTab status presentation', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/vips?')) return response({
        items: [{
          id: 'vip-1', address: '10.0.0.10', vip_type: 'VRRP', device_id: null,
          device_name: null, backup_device_id: null, backup_device_name: null,
          interface_name: '', description: '', real_servers: '', status: 'reserved',
          tenant_id: 'tenant-default', tenant_name: null,
        }],
        total: 1,
      });
      if (url === '/api/devices?mode=light') return response([]);
      return response({});
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uses a warning tone for reserved VIP records', async () => {
    render(<VIPManagementTab language="zh" t={(key) => key} />);
    const badge = (await screen.findByText('RESERVED')).closest('span');
    expect(badge?.className).toContain('bg-amber-50');
    expect(badge?.className).not.toContain('bg-emerald-50');
  });
});
