import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductCatalogManagementTab } from './ProductCatalogManagementTab';
import {
  createKnowledgeCatalogCustomModel,
  deleteKnowledgeCatalogCustomModel,
  getKnowledgeCatalog,
  getKnowledgeCatalogAliases,
  resolveKnowledgeCatalogAlias,
  updateKnowledgeCatalogCustomModel,
} from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';

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

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  createKnowledgeCatalogCustomModel: vi.fn(),
  deleteKnowledgeCatalogCustomModel: vi.fn(),
  getKnowledgeCatalog: vi.fn(),
  getKnowledgeCatalogAliases: vi.fn(),
  resolveKnowledgeCatalogAlias: vi.fn(),
  updateKnowledgeCatalogCustomModel: vi.fn(),
}));

const hierarchy = [
  {
    vendor_id: 'cisco',
    vendor_name: 'Cisco',
    model_count: 2,
    families: [
      {
        family_code: 'catalyst_9300',
        family_name: 'Catalyst 9300',
        model_count: 2,
        series: [
          {
            series_code: 'c9300',
            series_name: 'Catalyst C9300',
            model_count: 2,
            models: [
              { product_model_id: 'cisco:c9300:24p', model_code: 'C9300-24P', display_name: 'Catalyst C9300-24P', status: 'draft' },
              { product_model_id: 'cisco:c9300:48p', model_code: 'C9300-48P', display_name: 'Catalyst C9300-48P', status: 'draft' },
            ],
          },
        ],
      },
    ],
  },
] as any;

const catalogResponse = {
  persistence_status: 'contract_only_read_only_seed',
  tenant_id: 'tenant-default-reviewed',
  items: [],
  total: 0,
  read_only: true,
  source_artifacts: ['CAT-006-CISCO-C9300.yaml'],
  facets: {
    vendors: ['cisco'],
    families: ['catalyst_9300'],
    series: ['c9300'],
    software_versions: [],
    hierarchy,
  },
  meta: { pagination: { page: 1, page_size: 20, total: 0, total_pages: 1, sort_by: 'vendor_id', sort_order: 'asc' }, filters: {} },
};

const getCatalog = vi.mocked(getKnowledgeCatalog);
const getAliases = vi.mocked(getKnowledgeCatalogAliases);
const resolveAlias = vi.mocked(resolveKnowledgeCatalogAlias);

describe('ProductCatalogManagementTab browser key paths', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast: vi.fn(), currentUser: { role: 'Administrator' } } as never);
    getCatalog.mockResolvedValue(catalogResponse as any);
    getAliases.mockResolvedValue({ items: [], total: 0, conflicts: [], persistence_status: 'contract_only_read_only_seed', tenant_id: 'tenant-default-reviewed', read_only: true, source_artifact: 'CAT-010-ALIAS-SAMPLES.yaml' } as any);
    resolveAlias.mockResolvedValue({ candidates: [], candidate_count: 0, outcome: 'unknown', query: 'unknown', normalized_query: 'unknown', conflict_groups: [], requires_clarification: false, selection_allowed: false, manual_review_required: false, persistence_status: 'contract_only_read_only_seed', tenant_id: 'tenant-default-reviewed', dry_run: true, read_only: true, driver_selection_allowed: false } as any);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('browses the hierarchy and sends a server-side cascading filter for the selected model', async () => {
    const user = userEvent.setup();
    render(<ProductCatalogManagementTab />);

    expect(await screen.findByRole('button', { name: /Cisco/ })).toBeTruthy();
    expect(screen.getByText('产品分类浏览')).toBeTruthy();
    expect(screen.getByText('先选择 Vendor')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /Cisco/ }));
    expect(await screen.findByRole('button', { name: /Catalyst 9300/ })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /Catalyst 9300/ }));
    expect(await screen.findByRole('button', { name: /Catalyst C9300/ })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /Catalyst C9300/ }));
    expect(await screen.findByRole('button', { name: /C9300-48P/ })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /C9300-48P/ }));

    await waitFor(() => expect(getCatalog).toHaveBeenLastCalledWith(expect.objectContaining({
      vendor_id: 'cisco',
      family_code: 'catalyst_9300',
      series_code: 'c9300',
      model: 'C9300-48P',
      page: 1,
    })));
  });

  it('exports all filtered model pages with one business attribute per column and no internal IDs', async () => {
    const model = {
      product_model_id: 'internal-model-1', tenant_id: 'tenant-1', vendor_id: 'cisco', vendor_name: 'Cisco',
      family_code: 'catalyst_9300', family_name: 'Catalyst 9300', series_code: 'c9300', series_name: 'Catalyst C9300',
      model_code: 'C9300-24P', display_name: 'Catalyst C9300-24P', status: 'active', review_status: 'manual_approved',
      software_scope: { os_family: 'IOS XE', software_train: '17.x', primary_version: '17.9', compatibility_version: '17.6' },
    };
    getCatalog.mockResolvedValue({
      ...catalogResponse,
      items: [model as any],
      total: 2,
      meta: { ...catalogResponse.meta, pagination: { ...catalogResponse.meta.pagination, total: 2 } },
    } as any);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      const pageItem = { ...model, product_model_id: `internal-model-${url.searchParams.get('page')}`, model_code: `C9300-${url.searchParams.get('page')}4P` };
      return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, data: { items: [pageItem], total: 2 } }),
      };
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<ProductCatalogManagementTab />);

    await screen.findByText('C9300-24P');
    await user.selectOptions(screen.getAllByRole('combobox')[0], 'cisco');
    await user.click(await screen.findByRole('button', { name: '导出表格' }));
    await user.click(screen.getByRole('menuitem', { name: '导出 Excel (.xlsx)' }));

    await waitFor(() => expect(xlsxMocks.writeFile).toHaveBeenCalledWith(expect.any(Object), 'product-model-catalog.xlsx'));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    const secondUrl = new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost');
    expect(firstUrl.searchParams.get('vendor_id')).toBe('cisco');
    expect(firstUrl.searchParams.get('page')).toBe('1');
    expect(secondUrl.searchParams.get('page')).toBe('2');
    expect(xlsxMocks.aoaToSheet.mock.calls[0][0][0]).toEqual([
      'Vendor', 'Family Name', 'Family Code', 'Series Name', 'Series Code', 'Model Code',
      'OS 系列', '软件 Train', 'Software Version', '兼容版本', '状态', '审核状态',
    ]);
    expect(xlsxMocks.aoaToSheet.mock.calls[0][0]).toHaveLength(3);
    expect(xlsxMocks.aoaToSheet.mock.calls[0][0][1]).toEqual([
      'Cisco', 'Catalyst 9300', 'catalyst_9300', 'Catalyst C9300', 'c9300', 'C9300-14P',
      'IOS XE', '17.x', '17.9', '17.6', '启用', '人工通过',
    ]);
    expect(JSON.stringify(xlsxMocks.aoaToSheet.mock.calls[0][0])).not.toContain('internal-model');
    expect(JSON.stringify(xlsxMocks.aoaToSheet.mock.calls[0][0])).not.toContain('tenant-1');
  });

  it('exports all filtered alias pages as split fields without product or vendor IDs', async () => {
    const alias = {
      id: 'internal-alias-1', tenant_id: 'tenant-1', product_model_id: 'internal-model-1', alias: 'C9300',
      normalized_alias: 'c9300', alias_kind: 'exact', seed_status: 'active', expected_outcome: 'unique',
      conflict_status: 'manual_approved', conflict_group: '', conflict_reason: '', conflict_count: 0,
      model: { vendor_id: 'internal-vendor-1', vendor_name: 'Cisco', series_code: 'c9300', model_code: 'C9300-24P' },
    };
    getAliases.mockResolvedValue({ items: [alias as any], total: 2, conflicts: [], persistence_status: 'seed', tenant_id: 'tenant-1', read_only: true, source_artifact: 'catalog' } as any);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, data: { items: [{ ...alias, id: `internal-alias-${url.searchParams.get('page')}` }], total: 2 } }),
      };
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<ProductCatalogManagementTab />);

    await screen.findByRole('button', { name: /Cisco/ });
    await user.click(screen.getByRole('button', { name: 'Alias 队列' }));
    await screen.findByText('C9300');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Alias 类型' }), 'exact');
    await user.click(await screen.findByRole('button', { name: '导出表格' }));
    await user.click(screen.getByRole('menuitem', { name: '导出 Excel (.xlsx)' }));

    await waitFor(() => expect(xlsxMocks.writeFile).toHaveBeenCalledWith(expect.any(Object), 'product-model-aliases.xlsx'));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(firstUrl.searchParams.get('alias_kind')).toBe('exact');
    expect(new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost').searchParams.get('page')).toBe('2');
    expect(xlsxMocks.aoaToSheet.mock.calls[0][0][0]).toEqual([
      'Alias', '规范化别名', '类型', '目标型号', 'Vendor', 'Series Code', '冲突状态', '种子状态',
    ]);
    expect(xlsxMocks.aoaToSheet.mock.calls[0][0]).toHaveLength(3);
    expect(xlsxMocks.aoaToSheet.mock.calls[0][0][1]).toEqual([
      'C9300', 'c9300', '精确', 'C9300-24P', 'Cisco', 'c9300', '人工通过', '启用',
    ]);
    expect(JSON.stringify(xlsxMocks.aoaToSheet.mock.calls[0][0])).not.toContain('internal-alias');
    expect(JSON.stringify(xlsxMocks.aoaToSheet.mock.calls[0][0])).not.toContain('internal-model');
    expect(JSON.stringify(xlsxMocks.aoaToSheet.mock.calls[0][0])).not.toContain('internal-vendor');
  });
});
