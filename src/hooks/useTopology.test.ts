import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useTopology } from './useTopology';

const response = (payload: unknown) => ({
  ok: true,
  status: 200,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

describe('useTopology graph loading', () => {
  let originalToken: string | null;

  beforeEach(() => {
    originalToken = localStorage.getItem('netops_token');
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/topology/links?')) {
        return response({ links: [], unmanaged_nodes: [], unmanaged_links: [] });
      }
      if (url === '/api/topology/sites') return response({ items: [] });
      return response({ nodes: [], edges: [] });
    }));
  });

  afterEach(() => {
    cleanup();
    if (originalToken === null) localStorage.removeItem('netops_token');
    else localStorage.setItem('netops_token', originalToken);
    vi.unstubAllGlobals();
  });

  it('loads links and site summaries first, then loads the graph when a site is opened', async () => {
    const { result } = renderHook(() => useTopology({
      devices: [],
      language: 'en',
      showToast: vi.fn(),
      isAuthenticated: true,
      enabled: true,
    }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/topology/links?'), expect.anything());
      expect(fetch).toHaveBeenCalledWith('/api/topology/sites', expect.anything());
    });
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/topology/links?'), expect.anything());
    expect(fetch).toHaveBeenCalledWith('/api/topology/sites', expect.anything());
    expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining('/api/topology/graph?'), expect.anything());

    vi.mocked(fetch).mockClear();
    act(() => result.current.setTopologySiteFilter('site-1'));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/topology/graph?'), expect.anything());
    });
  });
});
