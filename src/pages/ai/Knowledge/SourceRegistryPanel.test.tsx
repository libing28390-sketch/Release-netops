import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SourceRegistryPanel from './SourceRegistryPanel';
import {
  getKnowledgeSourceRefreshStatus,
  listKnowledgeSourceRefreshObservations,
  listKnowledgeSources,
  listOfficialSourceSuggestions,
  reviewOfficialSourceSuggestion,
} from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  getKnowledgeSourceRefreshStatus: vi.fn(),
  listKnowledgeSourceRefreshObservations: vi.fn(),
  listKnowledgeSources: vi.fn(),
  listOfficialSourceSuggestions: vi.fn(),
  refreshKnowledgeSource: vi.fn(),
  reviewOfficialSourceSuggestion: vi.fn(),
  validateKnowledgeSource: vi.fn(),
}));

const listSources = vi.mocked(listKnowledgeSources);
const listSuggestions = vi.mocked(listOfficialSourceSuggestions);
const reviewSuggestion = vi.mocked(reviewOfficialSourceSuggestion);

describe('SourceRegistryPanel', () => {
  beforeEach(() => {
    listSources.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0, total_pages: 1 });
    listSuggestions.mockResolvedValue({ items: [], page: 1, page_size: 100, total: 0, total_pages: 1 });
    vi.mocked(getKnowledgeSourceRefreshStatus).mockResolvedValue({} as never);
    vi.mocked(listKnowledgeSourceRefreshObservations).mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows the real paginated source total instead of the current page length', async () => {
    listSources.mockResolvedValue({
      items: [{ id: 'source-1', name: 'Huawei support', canonical_url: 'https://support.huawei.com/', status: 'active', validation_status: 'valid', source_kind: 'product_support', fetch_enabled: true } as never],
      page: 1,
      page_size: 20,
      total: 45,
      total_pages: 3,
    });

    render(<SourceRegistryPanel />);

    expect(await screen.findByText('注册来源（共 45 条）')).toBeTruthy();
    expect(screen.getByLabelText('来源每页条数')).toBeTruthy();
    expect(screen.getAllByText('已启用').length).toBeGreaterThan(0);
    expect(screen.getByText('校验：已通过')).toBeTruthy();
  });

  it('blocks an insecure suggestion URL before requesting collection', async () => {
    const user = userEvent.setup();
    listSuggestions.mockResolvedValue({
      items: [{
        id: 'suggestion-1', trace_id: 'trace-1', vendor: 'Huawei', product_model: 'S5700', software_release: 'V200R023', feature: 'OSPF',
        label: 'Huawei S5700 OSPF', suggested_url: 'http://support.huawei.test/manual', source_kind: 'product_page', status: 'pending',
        created_at: '2026-08-24T00:00:00Z', updated_at: '2026-08-24T00:00:00Z',
      }],
      page: 1,
      page_size: 100,
      total: 1,
      total_pages: 1,
    });

    render(<SourceRegistryPanel />);

    await user.click(await screen.findByRole('button', { name: /Huawei S5700 OSPF/ }));
    await user.click(screen.getByRole('button', { name: '确认并采集入库' }));

    expect(await screen.findByText('官方来源必须填写有效的 HTTPS URL。')).toBeTruthy();
    expect(reviewSuggestion).not.toHaveBeenCalled();
  });
});
