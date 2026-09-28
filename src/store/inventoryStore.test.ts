import { describe, expect, it } from 'vitest';
import { useInventoryStore } from './inventoryStore';

describe('network device inventory pagination', () => {
  it('defaults to 20 rows per page', () => {
    expect(useInventoryStore.getInitialState().inventoryPageSize).toBe(20);
  });

  it('returns to the first page when the page size changes', () => {
    useInventoryStore.getState().setInventoryPage(3);
    useInventoryStore.getState().setInventoryPageSize(10);

    expect(useInventoryStore.getState().inventoryPage).toBe(1);
    expect(useInventoryStore.getState().inventoryPageSize).toBe(10);
  });
});
