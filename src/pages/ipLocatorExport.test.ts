import { describe, expect, it } from 'vitest';
import { readExplicitTableData } from '../components/ui/TableExportMenu';
import { buildMacChangeExportData, filterMacChangeEntries, loadAllMacChangeEntries, type MacChangeExportEntry } from './ipLocatorExport';

const entry = (index: number): MacChangeExportEntry => ({
  id: `internal-${index}`,
  ip: `192.0.2.${index % 250}`,
  old_mac: `00:00:00:00:${String(Math.floor(index / 256)).padStart(2, '0')}:${String(index % 256).padStart(2, '0')}`,
  new_mac: `00:00:00:01:${String(Math.floor(index / 256)).padStart(2, '0')}:${String(index % 256).padStart(2, '0')}`,
  old_vendor: 'Old vendor',
  new_vendor: 'New vendor',
  old_device: 'old-switch',
  new_device: 'new-switch',
  detected_at: `2026-09-28T00:${String(index % 60).padStart(2, '0')}:00Z`,
});

describe('IP locator export', () => {
  it('loads every offset page beyond the old 1000-row cap', async () => {
    const requestedOffsets: number[] = [];
    let laterPageMatch = '';
    const allEntries = await loadAllMacChangeEntries(async (offset, limit) => {
      requestedOffsets.push(offset);
      expect(limit).toBe(1000);
      const entries = offset === 0
        ? Array.from({ length: 1000 }, (_, index) => entry(index))
        : Array.from({ length: 30 }, (_, index) => entry(index + 1000));
      if (offset === 1000) {
        entries[17].old_device = 'match-only-on-later-page';
        laterPageMatch = entries[17].ip;
      }
      return {
        total: 1030,
        entries,
      };
    });

    expect(requestedOffsets).toEqual([0, 1000]);
    expect(allEntries).toHaveLength(1030);
    expect(filterMacChangeEntries(allEntries, 'match-only-on-later-page').map(row => row.ip)).toEqual([laterPageMatch]);
  });

  it('exports split old/new fields in visible order and filters across all fetched pages', () => {
    const rows = filterMacChangeEntries([entry(1), entry(2)], 'old-switch');
    const normalized = readExplicitTableData(buildMacChangeExportData(rows, true, value => `显示-${value}`));

    expect(normalized.headers).toEqual(['IP', '旧 MAC', '新 MAC', '旧厂商', '新厂商', '来源设备', '检测时间']);
    expect(normalized.rows).toHaveLength(2);
    expect(normalized.rows[0]).toEqual([
      '192.0.2.1',
      '00:00:00:00:00:01',
      '00:00:00:01:00:01',
      'Old vendor',
      'New vendor',
      'new-switch',
      expect.stringContaining('显示-2026-09-28T00:'),
    ]);
    expect(normalized.rows[0].join(' ')).not.toContain('internal-1');
  });
});
