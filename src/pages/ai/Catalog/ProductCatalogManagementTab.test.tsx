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
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast: vi.fn(), currentUser: { role: 'Administrator' } } as never);
    getCatalog.mockResolvedValue(catalogResponse as any);
    getAliases.mockResolvedValue({ items: [], total: 0, conflicts: [], persistence_status: 'contract_only_read_only_seed', tenant_id: 'tenant-default-reviewed', read_only: true, source_artifact: 'CAT-010-ALIAS-SAMPLES.yaml' } as any);
    resolveAlias.mockResolvedValue({ candidates: [], candidate_count: 0, outcome: 'unknown', query: 'unknown', normalized_query: 'unknown', conflict_groups: [], requires_clarification: false, selection_allowed: false, manual_review_required: false, persistence_status: 'contract_only_read_only_seed', tenant_id: 'tenant-default-reviewed', dry_run: true, read_only: true, driver_selection_allowed: false } as any);
  });

  afterEach(() => cleanup());

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
});
