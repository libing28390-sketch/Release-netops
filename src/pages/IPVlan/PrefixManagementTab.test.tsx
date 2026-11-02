import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PrefixManagementTab from './PrefixManagementTab';

const response = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;

describe('PrefixManagementTab creation defaults', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url === '/api/cmdb/sites' || url === '/api/cmdb/vrfs' || url === '/api/cmdb/vlans' || url === '/api/devices?mode=light') {
        return response([]);
      }
      return response([]);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('does not assume a new prefix is a server network', async () => {
    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));

    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    const networkType = Array.from(dialog.querySelectorAll('select')).find((select) =>
      Array.from(select.options).some((option) => option.value === 'unclassified'),
    );
    expect(networkType).toBeTruthy();
    expect((networkType as HTMLSelectElement).value).toBe('unclassified');
    expect(within(dialog).getByText('网络用途 (Role)')).toBeTruthy();
  });
});
