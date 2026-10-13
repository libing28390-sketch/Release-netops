import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import HomePage from './HomePage';

const assetSummary = {
  total: 7,
  by_type: { network_device: 3, server: 1 },
  by_online_status: { online: 3, offline: 1 },
  by_platform: { huawei_vrp: 2, h3c_comware: 1, unknown: 1 },
};

describe('HomePage asset summary', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(assetSummary),
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uses the asset inventory total and status counts for the home availability card', async () => {
    render(
      <HomePage
        language="zh"
        navigate={vi.fn()}
        isAuthenticated
        autoRefreshEnabled={false}
        jobs={[]}
        notifications={[]}
        hostResources={null}
        userCount={0}
      />,
    );

    await waitFor(() => expect(screen.getByText('75%')).toBeTruthy());

    expect(screen.getByText('3 / 4')).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith(
      '/api/assets/summary',
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });
});
