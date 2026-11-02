import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import IPUtilizationTab from './IPUtilizationTab';

const analytics = (networkScope: 'business' | 'all') => ({
  network_scope: networkScope,
  overview: {
    prefixes_count: networkScope === 'business' ? 1 : 3,
    ips_count: 10,
    pools_count: 2,
    vips_count: 1,
    leases_count: 0,
    total_ips: networkScope === 'business' ? 254 : 510,
    used_ips: networkScope === 'business' ? 3 : 5,
    free_ips: networkScope === 'business' ? 251 : 505,
    utilization_rate: networkScope === 'business' ? 1.2 : 1,
    capacity_prefixes_count: networkScope === 'business' ? 1 : 3,
    excluded_prefixes_count: 0,
    scope_excluded_prefixes_count: networkScope === 'business' ? 2 : 0,
    interconnect_prefixes_excluded_count: networkScope === 'business' ? 2 : 0,
    capacity_policy: `${networkScope}_scope_excluding_non_allocatable_prefixes`,
  },
  top_utilized_prefixes: [{
    id: networkScope === 'business' ? 'users' : 'transit',
    prefix: networkScope === 'business' ? '10.0.0.0/24' : '10.0.1.0/30',
    name: networkScope === 'business' ? '办公网' : '设备互联',
    status: 'active',
    network_type: networkScope === 'business' ? 'user_access' : 'transit',
    total_ips: 254,
    used_ips: 3,
    utilization: 1.2,
  }],
  site_breakdown: [{ site: 'Shanghai DC', total_ips: 254, used_ips: 3, utilization: 1.2 }],
  forecast_trend: [{ day: '2026-10-29', allocated: 3 }],
});

const jsonResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status,
  headers: { 'Content-Type': 'application/json' },
});

describe('IPUtilizationTab network scope', () => {
  beforeEach(() => localStorage.removeItem('netops_token'));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('requests business capacity by default and refetches all panels when scope changes', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const scope = new URL(String(input), 'http://localhost').searchParams.get('network_scope');
      return Promise.resolve(jsonResponse(analytics(scope === 'all' ? 'all' : 'business')));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<IPUtilizationTab language="zh" t={(key) => key} />);
    expect(await screen.findByText('办公网')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ipam/analytics?network_scope=business',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(screen.getByText('默认聚焦业务网段；已排除 2 个互联地址网段和 0 个其他非业务网段。')).toBeTruthy();
    expect(screen.getByText('业务容量网段')).toBeTruthy();
    expect(screen.getByText('剩余可分配 IP')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '全部网段' }));
    expect((await screen.findAllByText('设备互联'))).toHaveLength(2);
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/ipam/analytics?network_scope=all',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ));
    expect(screen.getByText('已包含管理网、互联地址和其他全部分类的网段。')).toBeTruthy();
  });

  it('shows a permission error instead of remaining in loading and retries the selected scope', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'forbidden' }, 403))
      .mockResolvedValueOnce(jsonResponse(analytics('business')));
    vi.stubGlobal('fetch', fetchMock);

    render(<IPUtilizationTab language="zh" t={(key) => key} />);
    expect((await screen.findByRole('alert')).textContent).toContain('当前账号没有查看 IP 利用率的权限');
    expect(screen.queryByText('加载分析数据中...')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('办公网')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
