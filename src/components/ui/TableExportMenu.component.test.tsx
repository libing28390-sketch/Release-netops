import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TableExportMenu } from './TableExportMenu';

const xlsxMocks = vi.hoisted(() => ({
  aoaToSheet: vi.fn((rows: unknown[][]) => ({ rows })),
  bookNew: vi.fn(() => ({ sheets: [] as unknown[] })),
  appendSheet: vi.fn((book: { sheets: unknown[] }, sheet: unknown) => { book.sheets.push(sheet); }),
  write: vi.fn(() => new Uint8Array([1, 2, 3])),
}));

vi.mock('xlsx', () => ({
  utils: {
    aoa_to_sheet: xlsxMocks.aoaToSheet,
    book_new: xlsxMocks.bookNew,
    book_append_sheet: xlsxMocks.appendSheet,
  },
  write: xlsxMocks.write,
}));

describe('TableExportMenu async data source', () => {
  let originalCreateObjectUrl: PropertyDescriptor | undefined;
  let createObjectUrlMock: ReturnType<typeof vi.fn>;
  let generatedBlobUrlCount: number;

  beforeEach(() => {
    vi.clearAllMocks();
    generatedBlobUrlCount = 0;
    originalCreateObjectUrl = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
    createObjectUrlMock = vi.fn(() => `blob:test-export-${++generatedBlobUrlCount}`);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrlMock });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    if (originalCreateObjectUrl) {
      Object.defineProperty(URL, 'createObjectURL', originalCreateObjectUrl);
    } else {
      Reflect.deleteProperty(URL, 'createObjectURL');
    }
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
    const loadingMenuItem = screen.getByRole('menuitem', { name: 'Export Excel (.xlsx)' });
    expect(loadingMenuItem.tagName).toBe('BUTTON');
    expect((loadingMenuItem as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('2 rows ready'));
    const excelLink = screen.getByRole('menuitem', { name: 'Export Excel (.xlsx)' }) as HTMLAnchorElement;
    expect(excelLink.tagName).toBe('A');
    expect(excelLink.href).toBe('blob:test-export-1');
    expect(excelLink.download).toBe('devices.xlsx');
    expect(exportData).toHaveBeenCalledOnce();
    expect(xlsxMocks.write).toHaveBeenCalledWith(expect.any(Object), { bookType: 'xlsx', type: 'array' });
    expect(createObjectUrlMock).toHaveBeenCalledTimes(2);
    expect(createObjectUrlMock).toHaveBeenNthCalledWith(1, expect.any(Blob));
    expect(createObjectUrlMock).toHaveBeenNthCalledWith(2, expect.any(Blob));
    expect(xlsxMocks.aoaToSheet).toHaveBeenCalledWith([
      ['设备', '管理 IP'],
      ['core-sw-01', '192.168.18.201'],
      ['core-sw-02', '192.168.18.202'],
    ]);
  });

  it('keeps formats disabled after prefetch failure and supports retry', async () => {
    const exportData = vi.fn()
      .mockRejectedValueOnce(new Error('Export data is unavailable.'))
      .mockResolvedValue({ headers: ['设备'], rows: [['core-sw-01']] });
    render(<TableExportMenu filename="devices" language="en" exportData={exportData} />);

    fireEvent.click(screen.getByRole('button', { name: 'Export table' }));
    await screen.findByRole('alert');
    const disabledExcelItem = screen.getByRole('menuitem', { name: 'Export Excel (.xlsx)' }) as HTMLButtonElement;
    expect(disabledExcelItem.tagName).toBe('BUTTON');
    expect(disabledExcelItem.disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading export data' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('1 rows ready'));
    const excelLink = screen.getByRole('menuitem', { name: 'Export Excel (.xlsx)' }) as HTMLAnchorElement;
    expect(excelLink.tagName).toBe('A');
    expect(excelLink.download).toBe('devices.xlsx');
    expect(exportData).toHaveBeenCalledTimes(2);
  });
});
