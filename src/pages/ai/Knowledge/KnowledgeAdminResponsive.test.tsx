import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Pagination from '../../../components/Pagination';
import RagEvaluationPanel from './RagEvaluationPanel';
import RetrievalTracePanel from './RetrievalTracePanel';
import { getKnowledgeEvaluation, getKnowledgeExperimentObservability, getKnowledgeGold400FixtureSummary, listKnowledgeRetrievalTraces } from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  getKnowledgeEvaluation: vi.fn(),
  getKnowledgeExperimentObservability: vi.fn(),
  getKnowledgeGold400FixtureSummary: vi.fn(),
  runKnowledgeEvaluation: vi.fn(),
  listKnowledgeRetrievalTraces: vi.fn(),
  getKnowledgeRetrievalTrace: vi.fn(),
}));

const getEvaluation = vi.mocked(getKnowledgeEvaluation);
const getObservability = vi.mocked(getKnowledgeExperimentObservability);
const getFixture = vi.mocked(getKnowledgeGold400FixtureSummary);
const listTraces = vi.mocked(listKnowledgeRetrievalTraces);

const report = {
  contract_version: 'kui-016-v1',
  suite: 'v1_baseline_postgresql',
  status: 'passed',
  tenant_id: 'tenant-a',
  baseline_id: 'baseline',
  system_under_test: 'rag',
  database: 'PostgreSQL',
  execution_mode: 'temporary_transaction',
  production_database_write: false,
  external_network_call: false,
  rollback: 'transaction_rollback',
  case_count: 1,
  metrics: { retrieval_accuracy: 1, wrong_vendor_rate: 0, version_conflict_rate: 0, citation_accuracy: 1, citation_recall: 1, latency_ms: { average: 1, p50: 1, p95: 2, max: 3 } },
  gates: [{ metric: 'retrieval_accuracy', actual: 1, operator: '>=', threshold: 0.95, passed: true }],
  cases: [{ id: 'Q01', retrieval_correct: true, citation_precision: 1, vendor_mismatch: false, version_conflict: false, latency_ms: 1 }],
};

describe('KUI-018 knowledge administration responsive gates', () => {
  beforeEach(() => {
    getEvaluation.mockResolvedValue(report as any);
    getObservability.mockResolvedValue({ schema_version: 'obs-002-v1', tenant_id: 'tenant-a', database: 'PostgreSQL', redacted: true, contains_prompt_or_answer: false, contains_document_or_chunk_identity: false, runs: [], rollouts: [], shadow_observations: [] });
    getFixture.mockResolvedValue({ dataset_id: 'nexora-kb-eval-gold-400-v2-20260905', status: 'frozen', purpose: 'Official-source-backed automated evaluation dataset', test_only: false, synthetic_data: false, production_eligible: true, production_gate: 'READY', case_count: 400, database: 'PostgreSQL', collection: { mode: 'official_url_backed_local_summary', source_manifest: 'data/kb_import/manifest.json', source_manifest_sha256: 'manifest-sha', collected_at: '2026-09-05', content_origin: 'local_summary_derived_from_official_pages' }, source_policy: { database: 'PostgreSQL', sqlite: 'not_used', external_network: 'forbidden', secrets: 'forbidden', production_data: 'forbidden', official_sources: 'required', source_collection: 'official_url_backed_local_summary' }, coverage: { categories: [{ key: 'knowledge_config_reference', count: 140 }], vendors: [{ key: 'Huawei', count: 100 }], splits: [{ key: 'train', count: 240 }] }, review: { mode: 'official_source_provenance_automated', minimum_double_review_cases: 0, human_review_required: false, human_review_ready: true }, redacted: true, contains_case_content: false } as any);
    listTraces.mockResolvedValue({ items: [], limit: 50, status: 'all', redacted: true });
    document.documentElement.setAttribute('data-theme', 'dark');
  });

  afterEach(() => {
    cleanup();
    document.documentElement.removeAttribute('data-theme');
  });

  it('keeps pagination bilingual, bounded and keyboard-operable', async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    const { rerender } = render(<Pagination currentPage={1} totalItems={25} itemsPerPage={10} onPageChange={onPageChange} language="zh" />);
    expect(screen.getByText('共 25 条')).toBeTruthy();
    expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(false);
    await user.click(screen.getByRole('button', { name: '下一页' }));
    expect(onPageChange).toHaveBeenCalledWith(2);

    rerender(<Pagination currentPage={2} totalItems={25} itemsPerPage={10} onPageChange={onPageChange} language="en" />);
    expect(screen.getByText('25 items')).toBeTruthy();
    expect(screen.getByText('/ 3 pages')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps evaluation table scrollable with a sticky dark-aware header', async () => {
    render(<RagEvaluationPanel />);
    const table = await screen.findByRole('table');
    const header = table.querySelector('thead');
    expect(header?.className).toContain('sticky');
    expect(header?.className).toContain('dark:bg-slate-800/95');
    expect(table.parentElement?.className).toContain('overflow-x-auto');
    expect(table.className).toContain('min-w-[640px]');
  });

  it('keeps retrieval trace empty state responsive and redacted in dark mode', async () => {
    render(<RetrievalTracePanel />);
    expect(await screen.findByText(/暂无检索记录/)).toBeTruthy();
    const root = screen.getByText('检索过程追踪').closest('div.mx-auto');
    expect(root?.className).toContain('dark:text-slate-100');
    expect(root?.className).toContain('w-full');
    expect((await screen.findAllByText(/默认脱敏/)).length).toBeGreaterThan(0);
  });
});
