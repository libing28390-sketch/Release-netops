import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DataTable } from './DataTable';
import { TableActionHeader } from './ui/TableActionColumn';

describe('DataTable export placement', () => {
  it('places export beside the existing action heading', () => {
    const { container } = render(
      <DataTable exportConfig={{ filename: 'records' }}>
        <thead><tr><th>Name</th><TableActionHeader>操作</TableActionHeader></tr></thead>
        <tbody><tr><td>Device</td><td>—</td></tr></tbody>
      </DataTable>,
    );

    const exportButton = container.querySelector('[data-table-export-menu] button');
    expect(exportButton).not.toBeNull();
    expect(exportButton?.closest('th')?.classList.contains('nx-action-column-header')).toBe(true);
    expect(container.querySelector('.nx-exportable-data-table > .mb-2')).toBeNull();
  });

  it('places export in the last visible header when there is no action column', () => {
    const { container } = render(
      <DataTable exportConfig={{ filename: 'records' }}>
        <thead><tr><th>Name</th><th>Status</th></tr></thead>
        <tbody><tr><td>Device</td><td>Online</td></tr></tbody>
      </DataTable>,
    );

    const exportButton = container.querySelector('[data-table-export-menu] button');
    expect(exportButton).not.toBeNull();
    expect(exportButton?.closest('th')?.textContent).toContain('Status');
  });
});
