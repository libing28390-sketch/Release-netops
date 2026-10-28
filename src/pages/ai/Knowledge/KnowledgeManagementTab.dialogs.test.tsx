import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import KnowledgeManagementTab from './KnowledgeManagementTab';
import {
  getKnowledgeAssetOptions,
  getKnowledgeDirectories,
  getKnowledgeDocument,
  getKnowledgeDocumentActionImpact,
  getKnowledgeDocumentFacets,
  getKnowledgeDocuments,
  getKnowledgeStats,
  reparseKnowledgeDocument,
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
    getKnowledgeDocument: vi.fn(),
    getKnowledgeDocumentActionImpact: vi.fn(),
    getKnowledgeDocumentFacets: vi.fn(),
    getKnowledgeDocuments: vi.fn(),
    getKnowledgeStats: vi.fn(),
    reparseKnowledgeDocument: vi.fn(),
  };
});

const documentRecord = {
  id: 'doc-router-runbook',
  document_id: 'doc-router-runbook',
  name: 'Router Runbook',
  knowledge_source_type: 'user_document',
  document_category: '01_product',
  product_family: 'Catalyst',
  product_model: 'C9300',
  vendor: 'cisco',
  platform: 'cisco_ios',
  os_family: 'IOS XE',
  software_release: '17.9',
  chunk_count: 2,
  status: 'active',
  exclude_from_rag: false,
  created_at: '2026-10-01T00:00:00Z',
  source: 'uploaded file',
  raw_source: { source: 'uploaded file' },
} as any;

const getStats = vi.mocked(getKnowledgeStats);
const getDocuments = vi.mocked(getKnowledgeDocuments);
const getFacets = vi.mocked(getKnowledgeDocumentFacets);
const getAssetOptions = vi.mocked(getKnowledgeAssetOptions);
const getDirectories = vi.mocked(getKnowledgeDirectories);
const getDocument = vi.mocked(getKnowledgeDocument);
const getActionImpact = vi.mocked(getKnowledgeDocumentActionImpact);

describe('KnowledgeManagementTab modal keyboard interactions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getStats.mockResolvedValue({ total_documents: 1, total_chunks: 2, total_vendors: 1, ready_indexes: 1 } as any);
    getDocuments.mockResolvedValue({ items: [documentRecord], total: 1, page: 1, page_size: 10 } as any);
    getFacets.mockResolvedValue({ vendors: [], families: [], series: [], unknown_count: 0 } as any);
    getAssetOptions.mockResolvedValue({ source: 'physical_assets', asset_count: 0, vendors: [] } as any);
    getDirectories.mockResolvedValue({ items: [] } as any);
    getDocument.mockResolvedValue({
      ...documentRecord,
      chunks: [],
      source_version_history: [],
      original_content: 'A sample runbook for testing the document viewer.',
    } as any);
    getActionImpact.mockResolvedValue({
      document_id: documentRecord.id,
      name: documentRecord.name,
      current_status: 'active',
      impact: { documents: 1, chunks: 2, indexes: 1, references: 0, reference_details: [] },
      recovery: { reparse: 'The document can be reparsed again.' },
      safe_to_confirm: true,
    } as any);
  });

  afterEach(() => cleanup());

  it('opens the upload dialog, announces the selected mode, contains focus, and restores the trigger after Escape', async () => {
    const user = userEvent.setup();
    render(<KnowledgeManagementTab />);

    const opener = await screen.findByRole('button', { name: '批量上传企业文件' });
    await user.click(opener);
    const dialog = screen.getByRole('dialog', { name: '新增与上传企业知识文件' });
    const close = screen.getByRole('button', { name: '关闭上传窗口' });
    expect(document.activeElement).toBe(close);

    const batchMode = screen.getByRole('button', { name: /批量上传文件/ });
    const manualMode = screen.getByRole('button', { name: /手动录入文本/ });
    expect(batchMode.getAttribute('aria-pressed')).toBe('true');
    expect(manualMode.getAttribute('aria-pressed')).toBe('false');
    await user.click(manualMode);
    expect(manualMode.getAttribute('aria-pressed')).toBe('true');
    expect(batchMode.getAttribute('aria-pressed')).toBe('false');

    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '新增与上传企业知识文件' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it('traps the document viewer focus and returns it to the selected row after Escape', async () => {
    const user = userEvent.setup();
    render(<KnowledgeManagementTab />);

    const opener = await screen.findByRole('button', { name: 'Router Runbook' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Router Runbook' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭文档查看器' }));

    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Router Runbook' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it('keeps dangerous document actions behind the impact dialog and returns focus when canceled with Escape', async () => {
    const user = userEvent.setup();
    render(<KnowledgeManagementTab />);

    const opener = await screen.findByRole('button', { name: '重新解析 Metadata' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: '危险操作影响确认' });
    const cancel = screen.getByRole('button', { name: '取消' });
    expect(document.activeElement).toBe(cancel);

    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '危险操作影响确认' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
    expect(getActionImpact).toHaveBeenCalledWith(documentRecord.id);
    expect(reparseKnowledgeDocument).not.toHaveBeenCalled();
  });
});
