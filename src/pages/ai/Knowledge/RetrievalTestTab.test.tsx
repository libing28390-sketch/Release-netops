import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RetrievalTestTab, buildRetrievalSummary } from './RetrievalTestTab';
import { runKnowledgeRetrievalTest, type RetrievalTestResult } from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  runKnowledgeRetrievalTest: vi.fn(),
}));

const runTest = vi.mocked(runKnowledgeRetrievalTest);

const baseResult = (overrides: Partial<RetrievalTestResult> = {}): RetrievalTestResult => ({
  contract_version: 'test',
  entities: { vendor: 'Huawei', feature: 'ospf', empty: '' },
  filters: {},
  resolution: { outcome: 'resolved', ambiguous: false, candidates: [], platform_candidates: [] },
  final_chunks: [
    {
      chunk_id: 'c1',
      document_id: 'd1',
      document_name: 'Huawei OSPF 配置指南',
      section: 'Verification',
      platform: 'huawei_vrp',
      score: 0.8123,
      score_components: { lexical: 0.7, vector: 0.5, note: 'x' },
      content: 'display ospf peer',
    },
  ],
  explanation: {},
  debug: { retrieval_engine: 'v2_exact_small_set', candidate_count: 260, retrieval_latency_ms: 12.6, fts_stage: 'native_postgresql', vector_stage: 'native_pgvector' },
  ...overrides,
});

describe('RetrievalTestTab', () => {
  beforeEach(() => {
    runTest.mockReset();
  });
  afterEach(() => cleanup());

  it('shows the page header and an empty state before the first run', () => {
    render(<RetrievalTestTab />);
    expect(screen.getByRole('heading', { name: /管理员检索测试沙箱/ })).toBeTruthy();
    expect(screen.getByText('尚未执行检索测试')).toBeTruthy();
    expect(screen.getByRole('button', { name: '执行检索测试' })).toBeTruthy();
  });

  it('sends the selected filters and renders the summary, entities and chunks', async () => {
    runTest.mockResolvedValue(baseResult());
    render(<RetrievalTestTab />);

    await userEvent.click(screen.getByRole('button', { name: '执行检索测试' }));

    await waitFor(() => expect(screen.getByLabelText('检索结果概览')).toBeTruthy());
    expect(runTest).toHaveBeenCalledWith('display ospf peer', { vendor: 'Huawei' });
    expect(screen.getByText('V2 精确路径（小知识库）')).toBeTruthy();
    expect(screen.getByText('260')).toBeTruthy();
    expect(screen.getByText('13 ms')).toBeTruthy();
    expect(screen.getByText('feature')).toBeTruthy();
    expect(screen.queryByText('empty')).toBeNull();
    expect(screen.getByText(/最终命中 Chunk（1）/)).toBeTruthy();
    expect(screen.getByText('Score 0.812')).toBeTruthy();
    expect(screen.getByText('lexical: 0.70')).toBeTruthy();
    expect(screen.queryByText(/note:/)).toBeNull();
    expect(screen.queryByText('尚未执行检索测试')).toBeNull();
  });

  it('shows the no-hit empty state and rejects invalid advanced JSON', async () => {
    runTest.mockResolvedValue(baseResult({ final_chunks: [] }));
    render(<RetrievalTestTab />);

    await userEvent.click(screen.getByRole('button', { name: /高级 JSON 过滤扩展/ }));
    const textarea = screen.getByLabelText('高级 JSON 过滤条件');
    await userEvent.clear(textarea);
    await userEvent.type(textarea, '[[1]');
    await userEvent.click(screen.getByRole('button', { name: '执行检索测试' }));
    expect(screen.getByRole('alert').textContent).toBeTruthy();
    expect(runTest).not.toHaveBeenCalled();

    await userEvent.clear(textarea);
    await userEvent.click(screen.getByRole('button', { name: '执行检索测试' }));
    await waitFor(() => expect(screen.getByText('没有命中的 Chunk')).toBeTruthy());
  });

  it('builds summary items only from fields the API returned', () => {
    const items = buildRetrievalSummary(baseResult({ debug: {}, final_chunks: [], resolution: { ambiguous: true, candidates: [], platform_candidates: [] } }));
    expect(items.map((item) => item.key)).toEqual(['chunks', 'resolution']);
    expect(items[0].tone).toBe('warning');
    expect(items[1].value).toBe('需要澄清');
  });
});
