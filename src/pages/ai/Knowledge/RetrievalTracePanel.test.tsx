import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RetrievalTracePanel from './RetrievalTracePanel';
import { getKnowledgeRetrievalTrace, listKnowledgeRetrievalTraces } from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  getKnowledgeRetrievalTrace: vi.fn(),
  listKnowledgeRetrievalTraces: vi.fn(),
}));

const listTraces = vi.mocked(listKnowledgeRetrievalTraces);
const getTrace = vi.mocked(getKnowledgeRetrievalTrace);

const trace = {
  trace_id: 'rt_1234567890abcdef',
  tenant_id: 'tenant-a',
  actor_hash: 'a1b2c3d4',
  query_hash: '0123456789abcdef',
  created_at: '2026-08-17T12:00:00Z',
  source: 'local_rag',
  status: 'hit',
  metadata_candidate_documents: 3,
  candidate_count: 4,
  dedup_document_count: 2,
  final_document_count: 1,
  vector_top_n: 5,
  clarification_required: false,
  cross_platform_search: false,
  request: { vendor: 'Huawei' },
  resolution: { ambiguous: false, platform_candidates: ['huawei_vrp'], evidence: 'exact' },
  citations: [],
  citation_warning_count: 0,
  redaction: { default: true, raw_query_included: false, raw_chunk_included: false, raw_sql_included: false, credentials_included: false },
};

describe('RetrievalTracePanel', () => {
  beforeEach(() => {
    listTraces.mockResolvedValue({ items: [trace as any], limit: 50, status: 'all', redacted: true });
    getTrace.mockResolvedValue(trace as any);
  });

  afterEach(() => cleanup());

  it('shows bounded trace details without query text', async () => {
    const user = userEvent.setup();
    render(<RetrievalTracePanel />);
    expect(await screen.findByText('检索详情')).toBeTruthy();
    expect(screen.getByText('问题摘要 0123456789ab…')).toBeTruthy();
    expect(screen.queryByText('show secret command')).toBeNull();
    await user.click(screen.getByRole('button', { name: /rt_123456789/ }));
    expect(getTrace).toHaveBeenCalledWith('rt_1234567890abcdef');
  });

  it('shows an empty state when no trace exists', async () => {
    listTraces.mockResolvedValue({ items: [], limit: 50, status: 'all', redacted: true });
    render(<RetrievalTracePanel />);
    expect(await screen.findByText('暂无检索记录；先在 Copilot 中提问，或执行一次本地检索。')).toBeTruthy();
  });
});
