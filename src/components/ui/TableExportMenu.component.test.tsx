import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TableExportMenu } from './TableExportMenu';

const xlsxMocks = vi.hoisted(() => ({
  aoaToSheet: vi.fn((rows: unknown[][]) => ({ rows })),
  bookNew: vi.fn(() => ({ sheets: [] as unknown[] })),
  appendSheet: vi.fn((book: { sheets: unknown[] }, sheet: unknown) => { book.sheets.push(sheet); }),
  writeFile: vi.fn(),
}));

vi.mock('xlsx', () => ({
  utils: {
    aoa_to_sheet: xlsxMocks.aoaToSheet,
    book_new: xlsxMocks.bookNew,
    book_append_sheet: xlsxMocks.appendSheet,
  },
  writeFile: xlsxMocks.writeFile,
}));

describe('TableExportMenu async data source', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('waits for all filtered rows before exporting', async () => {
    const exportData = vi.fn(async () => ({
      headers: ['设备', '管理 IP'],
      rows: [
        ['core-sw-01', '192.168.18.201'],
        ['core-sw-02', '192.168.18.202'],
      ],
    }));
    render(<TableExportMenu filename="devices" language="en" exportData={exportData} />);

    fireEvent.click(screen.getByRole('button', { name: 'Export table' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Export Excel (.xlsx)' }));

    await waitFor(() => expect(xlsxMocks.writeFile).toHaveBeenCalledWith(expect.any(Object), 'devices.xlsx'));
    expect(exportData).toHaveBeenCalledOnce();
    expect(xlsxMocks.aoaToSheet).toHaveBeenCalledWith([
      ['设备', '管理 IP'],
      ['core-sw-01', '192.168.18.201'],
      ['core-sw-02', '192.168.18.202'],
    ]);
  });
});
