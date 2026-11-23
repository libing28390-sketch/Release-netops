import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import KnowledgeManagementTab, { DirectoryTreePicker } from './KnowledgeManagementTab';
import {
  getKnowledgeAssetOptions,
  getKnowledgeDirectories,
  getKnowledgeDocumentFacets,
  getKnowledgeDocuments,
  getKnowledgeStats,
  type KnowledgeDirectoryNode,
} from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: () => ({ language: 'zh', currentUser: { role: 'Administrator' }, showToast: vi.fn() }),
}));

vi.mock('../../../api/ai', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/ai')>();
  return {
    ...actual,
    getKnowledgeAssetOptions: vi.fn(),
    getKnowledgeDirectories: vi.fn(),
    getKnowledgeDocumentFacets: vi.fn(),
    getKnowledgeDocuments: vi.fn(),
    getKnowledgeStats: vi.fn(),
  };
});

const node: KnowledgeDirectoryNode = {
  id: 'dir-product',
  knowledge_base_id: 'kb-default',
  tenant_id: 'tenant-default',
  parent_id: null,
  name: '01_product',
  path: '01_product',
  depth: 0,
  is_system: true,
  sort_order: 10,
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z',
  children: [],
};

describe('DirectoryTreePicker', () => {
  it('allows read-only users to browse but hides directory write actions', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    render(
      <DirectoryTreePicker
        nodes={[node]}
        selectedPath=""
        loading={false}
        inline
        canManage={false}
        onSelect={onSelect}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.queryByRole('button', { name: '新建目录' })).toBeNull();
    expect(screen.queryByRole('group', { name: '目录操作' })).toBeNull();
    await user.click(screen.getByRole('button', { name: /01_product/ }));
    expect(onSelect).toHaveBeenCalledWith(node);
  });
});

const PAGE_TITLE = '企业网络知识库中心 (RAG Data Engine)';

describe('KnowledgeManagementTab redesigned layout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getKnowledgeStats).mockResolvedValue({ total_documents: 0, total_chunks: 0, total_vendors: 0, ready_indexes: 0 } as any);
    vi.mocked(getKnowledgeDocuments).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 } as any);
    vi.mocked(getKnowledgeDocumentFacets).mockResolvedValue({ vendors: [], families: [], series: [], unknown_count: 0 } as any);
    vi.mocked(getKnowledgeAssetOptions).mockResolvedValue({ source: 'physical_assets', asset_count: 0, vendors: [] } as any);
    vi.mocked(getKnowledgeDirectories).mockResolvedValue({ items: [] } as any);
  });

  afterEach(() => cleanup());

  it('renders the page header and the one-line summary bar', async () => {
    render(<KnowledgeManagementTab />);

    expect(await screen.findByRole('heading', { level: 2, name: new RegExp('企业网络知识库中心') })).toBeTruthy();
    const summary = screen.getAllByLabelText(PAGE_TITLE).find((element) => element.tagName === 'DL');
    expect(summary).toBeTruthy();
    expect(summary?.textContent).toContain('文档总数');
    expect(summary?.textContent).toContain('Heading 智能切片');
  });

  it('shows the shared empty state inside the document panel when nothing matches', async () => {
    render(<KnowledgeManagementTab />);

    const panel = await screen.findByLabelText('知识文档列表');
    await waitFor(() => expect(panel.textContent).toContain('当前目录暂无符合条件的知识文档'));
    expect(panel.querySelector('h3')?.textContent).toBe('当前目录暂无符合条件的知识文档');
    // No directory is selected, so the directory hint uses the same empty-state component.
    expect(screen.getByText('选择左侧目录查看文档')).toBeTruthy();
  });

  it('shows a load error with a retry action instead of an empty table', async () => {
    vi.mocked(getKnowledgeDocuments).mockRejectedValue(new Error('知识服务暂不可用'));
    const user = userEvent.setup();
    render(<KnowledgeManagementTab />);

    const panel = await screen.findByLabelText('知识文档列表');
    await waitFor(() => expect(panel.textContent).toContain('知识文档加载失败'));
    const retry = screen.getByRole('button', { name: '重试' });
    const callsBefore = vi.mocked(getKnowledgeDocuments).mock.calls.length;
    await user.click(retry);
    await waitFor(() => expect(vi.mocked(getKnowledgeDocuments).mock.calls.length).toBeGreaterThan(callsBefore));
  });
});
