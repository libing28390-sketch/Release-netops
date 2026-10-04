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

  it('defaults to 20 rows per page', () => {
    expect(useInventoryStore.getInitialState().inventoryPageSize).toBe(20);
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
});
