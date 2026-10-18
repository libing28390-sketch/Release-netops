import { afterEach, describe, expect, it, vi } from 'vitest';
import { useInventoryStore } from './inventoryStore';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('network device inventory pagination', () => {
  afterEach(() => {
    useInventoryStore.setState(useInventoryStore.getInitialState());
    vi.unstubAllGlobals();
  });

  it('defaults to 10 rows per page', () => {
    expect(useInventoryStore.getInitialState().inventoryPageSize).toBe(10);
  });

  it('returns to the first page when the page size changes', () => {
    useInventoryStore.getState().setInventoryPage(3);
    useInventoryStore.getState().setInventoryPageSize(10);

    expect(useInventoryStore.getState().inventoryPage).toBe(1);
    expect(useInventoryStore.getState().inventoryPageSize).toBe(10);
  });

  it('ignores a stale response after a newer filter request has completed', async () => {
    const oldResponse = deferred<{ ok: boolean; json: () => Promise<unknown> }>();
    const newResponse = deferred<{ ok: boolean; json: () => Promise<unknown> }>();
    const fetchMock = vi.fn()
      .mockReturnValueOnce(oldResponse.promise)
      .mockReturnValueOnce(newResponse.promise);
    vi.stubGlobal('fetch', fetchMock);

    const store = useInventoryStore.getState();
    store.setInventorySearch('old filter');
    const oldRequest = store.fetchInventory();
    useInventoryStore.getState().setInventorySearch('new filter');
    const newRequest = useInventoryStore.getState().fetchInventory();

    newResponse.resolve({
      ok: true,
      json: async () => ({ items: [{ id: 'new', hostname: 'new-result' }], total: 1 }),
    });
    await newRequest;
    oldResponse.resolve({
      ok: true,
      json: async () => ({ items: [{ id: 'old', hostname: 'stale-result' }], total: 1 }),
    });
    await oldRequest;

    expect(useInventoryStore.getState().inventoryRows.map((row) => row.hostname)).toEqual(['new-result']);
    expect(useInventoryStore.getState().inventoryLoading).toBe(false);
    expect(useInventoryStore.getState().inventoryError).toBeNull();
  });

  it('stores server-side health counts for the full filtered inventory, not the current page', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [{ id: 'device-page-1', hostname: 'page-one' }],
        total: 219,
        status_counts: { online: 15, offline: 204 },
        health_counts: { healthy: 5, warning: 10, staging_maintenance: 10 },
      }),
    }));

    await useInventoryStore.getState().fetchInventory();

    expect(useInventoryStore.getState().inventoryRows).toHaveLength(1);
    expect(useInventoryStore.getState().inventoryTotal).toBe(219);
    expect(useInventoryStore.getState().inventoryHealthCounts).toEqual({
      healthy: 5,
      warning: 10,
      staging_maintenance: 10,
    });
  });

  it('clears stale rows and shows an API error when the latest request fails', async () => {
    useInventoryStore.setState({
      inventoryRows: [{ id: 'old', hostname: 'stale-result' } as never],
      inventoryTotal: 1,
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'Forbidden' }),
    }));

    await useInventoryStore.getState().fetchInventory();

    expect(useInventoryStore.getState().inventoryRows).toEqual([]);
    expect(useInventoryStore.getState().inventoryTotal).toBe(0);
    expect(useInventoryStore.getState().inventoryLoading).toBe(false);
    expect(useInventoryStore.getState().inventoryError).toBe('Forbidden');
  });

  it('loads the network-device and server total from the asset summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        total: 19,
        by_type: { network_device: 7, server: 5, other: 7 },
        by_online_status: { online: 3, offline: 9 },
        by_platform: { cisco_ios: 7, linux: 5 },
      }),
    }));

    await useInventoryStore.getState().fetchAssetsTotal();

    expect(useInventoryStore.getState().assetsTotal).toBe(12);
    expect(useInventoryStore.getState().assetsOnlineTotal).toBe(3);
    expect(useInventoryStore.getState().assetsPlatformCounts).toEqual({ cisco_ios: 7, linux: 5 });
    expect(useInventoryStore.getState().assetsPlatformError).toBeNull();
    expect(useInventoryStore.getState().assetsTotalError).toBeNull();
  });

  it('clears platform summary values when the shared asset summary is reset', () => {
    useInventoryStore.setState({
      assetsTotal: 12,
      assetsOnlineTotal: 3,
      assetsPlatformCounts: { cisco_ios: 7, linux: 5 },
      assetsPlatformError: null,
    });

    useInventoryStore.getState().resetAssetsTotal();

    expect(useInventoryStore.getState().assetsTotal).toBeNull();
    expect(useInventoryStore.getState().assetsPlatformCounts).toBeNull();
    expect(useInventoryStore.getState().assetsPlatformError).toBeNull();
  });

  it('retains the last successful total and reports a retryable summary error', async () => {
    useInventoryStore.setState({ assetsTotal: 12, assetsOnlineTotal: 3 });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));

    await useInventoryStore.getState().fetchAssetsTotal();

    expect(useInventoryStore.getState().assetsTotal).toBe(12);
    expect(useInventoryStore.getState().assetsOnlineTotal).toBe(3);
    expect(useInventoryStore.getState().assetsTotalError).toBe('Failed to load asset device total');
  });

  it('does not let a stale summary response overwrite a fresher asset-page update', async () => {
    const oldResponse = deferred<{ ok: boolean; json: () => Promise<unknown> }>();
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(oldResponse.promise));

    const oldRequest = useInventoryStore.getState().fetchAssetsTotal();
    useInventoryStore.getState().setAssetsTotal(21);
    oldResponse.resolve({
      ok: true,
      json: async () => ({ by_type: { network_device: 2, server: 3 } }),
    });
    await oldRequest;

    expect(useInventoryStore.getState().assetsTotal).toBe(21);
  });
});
