import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import IPPoolTab from './IPPoolTab';

const response = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;

describe('IPPoolTab status presentation', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/pools?')) return response({
        items: [{
          id: 'pool-1', name: 'Reserved range', prefix_id: 'prefix-1', prefix: '10.0.0.0/24',
          prefix_name: 'Office', start_ip: '10.0.0.100', end_ip: '10.0.0.109', description: '',
          status: 'reserved', tenant_id: 'tenant-default', tenant_name: null,
          total_ips: 10, used_ips: 0, utilization: 0,
        }],
        total: 1,
      });
      if (url === '/api/ipam/subnets') return response([]);
      return response({});
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uses a warning tone for reserved pools', async () => {
    render(<IPPoolTab language="zh" t={(key) => key} />);
    const badge = (await screen.findByText('RESERVED')).closest('span');
    expect(badge?.className).toContain('bg-amber-50');
    expect(badge?.className).not.toContain('bg-emerald-50');
  });
});
