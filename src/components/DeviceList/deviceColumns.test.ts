import { describe, expect, it } from 'vitest';
import {
  COLUMN_KEYS,
  COLUMN_VISIBILITY_STORAGE_KEY,
  DEFAULT_COLUMNS,
  defaultColumnVisibility,
  loadColumnVisibility,
  normalizeColumnVisibility,
  saveColumnVisibility,
  setColumnVisibility,
} from './deviceColumns';

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
}

describe('network-device column preferences', () => {
  it('defaults to the useful identity, location, and health fields', () => {
    expect(COLUMN_KEYS.filter((key) => DEFAULT_COLUMNS[key])).toEqual([
      'hostname', 'assetTag', 'managementIp', 'category', 'role',
      'vendor', 'model', 'site', 'rack', 'rackUnit', 'status', 'health', 'actions',
    ]);
    expect(DEFAULT_COLUMNS.adaptation).toBe(false);
    const columnKeys = COLUMN_KEYS.map(String);
    expect(columnKeys).not.toContain('platform');
    expect(columnKeys).not.toContain('adaptationVersion');
    expect(columnKeys).not.toContain('adaptationSource');
    expect(columnKeys).not.toContain('versionMismatch');
  });

  it('round trips visible columns using the versioned storage key', () => {
    const storage = memoryStorage();
    const customized = { ...DEFAULT_COLUMNS, tags: true, category: false };

    saveColumnVisibility(customized, storage);

    expect(storage.getItem(COLUMN_VISIBILITY_STORAGE_KEY)).not.toBeNull();
    expect(loadColumnVisibility(storage)).toEqual(customized);
  });

  it('resets old all-column preferences to the compact defaults after a preference version change', () => {
    const oldAllColumns = Object.fromEntries(COLUMN_KEYS.map((key) => [key, true]));
    const storage = memoryStorage({
      'netops:network-devices:columns:v1': JSON.stringify(oldAllColumns),
    });

    expect(loadColumnVisibility(storage)).toEqual(DEFAULT_COLUMNS);
  });

  it('ignores unknown fields, defaults missing values, and keeps row actions enabled', () => {
    expect(normalizeColumnVisibility({
      hostname: false,
      platform: true,
      actions: false,
      oldRemovedField: true,
    })).toEqual({
      ...DEFAULT_COLUMNS,
      hostname: false,
    });
  });

  it('falls back to core columns after malformed or unavailable preferences', () => {
    expect(loadColumnVisibility(memoryStorage({
      [COLUMN_VISIBILITY_STORAGE_KEY]: '{broken json',
    }))).toEqual(DEFAULT_COLUMNS);
    expect(loadColumnVisibility({
      getItem: () => { throw new Error('storage blocked'); },
      setItem: () => { throw new Error('storage blocked'); },
    })).toEqual(DEFAULT_COLUMNS);
  });

  it('restores defaults and prevents hiding the last data column or row actions', () => {
    const onlyHostname = Object.fromEntries(
      COLUMN_KEYS.map((key) => [key, key === 'hostname' || key === 'actions']),
    ) as typeof DEFAULT_COLUMNS;

    expect(setColumnVisibility(onlyHostname, 'hostname', false)).toBe(onlyHostname);
    expect(setColumnVisibility(onlyHostname, 'actions', false)).toBe(onlyHostname);
    expect(defaultColumnVisibility()).toEqual(DEFAULT_COLUMNS);
  });

  it('continues working when saving is blocked by browser storage policy', () => {
    expect(() => saveColumnVisibility(DEFAULT_COLUMNS, {
      getItem: () => null,
      setItem: () => { throw new Error('storage blocked'); },
    })).not.toThrow();
  });
});
