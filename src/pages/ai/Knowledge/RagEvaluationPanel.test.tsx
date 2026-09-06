import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RagEvaluationPanel from './RagEvaluationPanel';
import { getKnowledgeEvaluation, getKnowledgeExperimentObservability, getKnowledgeGold400FixtureSummary, runKnowledgeEvaluation } from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  getKnowledgeEvaluation: vi.fn(),
  getKnowledgeExperimentObservability: vi.fn(),
  getKnowledgeGold400FixtureSummary: vi.fn(),
  runKnowledgeEvaluation: vi.fn(),
}));

const getEvaluation = vi.mocked(getKnowledgeEvaluation);
const getObservability = vi.mocked(getKnowledgeExperimentObservability);
const getFixture = vi.mocked(getKnowledgeGold400FixtureSummary);
const runEvaluation = vi.mocked(runKnowledgeEvaluation);

const emptyReport = {
  contract_version: 'kui-016-v1',
  suite: 'v1_baseline_postgresql',
  status: 'not_run',
  tenant_id: 'tenant-a',
  baseline_id: 'nexora-kb-v1-20260809',
  system_under_test: 'current-local-rag-retrieval-path',
  database: 'PostgreSQL',
  execution_mode: 'temporary_transaction',
  production_database_write: false,
  external_network_call: false,
  rollback: 'transaction_rollback',
  case_count: 10,
  metrics: null,
  gates: [],
  cases: [],
};

const passReport = {
  ...emptyReport,
  status: 'passed',
  metrics: {
    retrieval_accuracy: 1,
    wrong_vendor_rate: 0,
    version_conflict_rate: 0,
    citation_accuracy: 1,
    citation_recall: 1,
    latency_ms: { average: 1, p50: 1, p95: 2, max: 3 },
  },
  gates: [
    { metric: 'retrieval_accuracy', actual: 1, operator: '>=', threshold: 0.95, passed: true },
    { metric: 'wrong_vendor_rate', actual: 0, operator: '<=', threshold: 0.01, passed: true },
  ],
  cases: [{ id: 'Q01', retrieval_correct: true, citation_precision: 1, vendor_mismatch: false, version_conflict: false, latency_ms: 1 }],
};

const fixtureSummary = {
  dataset_id: 'nexora-kb-eval-gold-400-v2-20260905',
  status: 'frozen',
  purpose: 'Official-source-backed automated evaluation dataset',
  test_only: false,
  synthetic_data: false,
  production_eligible: true,
  production_gate: 'READY',
  case_count: 400,
  database: 'PostgreSQL',
  collection: { mode: 'official_url_backed_local_summary', source_manifest: 'data/kb_import/manifest.json', source_manifest_sha256: 'manifest-sha', collected_at: '2026-09-05', content_origin: 'local_summary_derived_from_official_pages' },
  source_policy: { database: 'PostgreSQL', sqlite: 'not_used', external_network: 'forbidden', secrets: 'forbidden', production_data: 'forbidden', official_sources: 'required', source_collection: 'official_url_backed_local_summary' },
  coverage: {
    categories: [{ key: 'knowledge_config_reference', count: 140 }, { key: 'troubleshooting', count: 70 }],
    vendors: [{ key: 'Huawei', count: 100 }, { key: 'Cisco', count: 100 }],
    splits: [{ key: 'train', count: 240 }, { key: 'debug', count: 80 }, { key: 'hidden', count: 80 }],
  },
  review: { mode: 'official_source_provenance_automated', minimum_double_review_cases: 0, human_review_required: false, human_review_ready: true },
  redacted: true,
  contains_case_content: false,
};

describe('RagEvaluationPanel', () => {
  beforeEach(() => {
    getEvaluation.mockResolvedValue(emptyReport as any);
    getObservability.mockResolvedValue({ schema_version: 'obs-002-v1', tenant_id: 'tenant-a', database: 'PostgreSQL', redacted: true, contains_prompt_or_answer: false, contains_document_or_chunk_identity: false, runs: [], rollouts: [], shadow_observations: [] });
    getFixture.mockResolvedValue(fixtureSummary as any);
    runEvaluation.mockResolvedValue(passReport as any);
  });

  afterEach(() => cleanup());

  it('shows a safe empty state and runs the PostgreSQL regression', async () => {
    const user = userEvent.setup();
    render(<RagEvaluationPanel />);
    expect(await screen.findByText('尚未运行基线回归，请点击“运行基线回归”。')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '运行基线回归' }));
    expect((await screen.findAllByText('PASS')).length).toBeGreaterThan(0);
    expect(screen.getByText('Q01')).toBeTruthy();
    expect(screen.getByText('400')).toBeTruthy();
    expect(screen.getByText('人工评审：不要求（双审要求 0 条）')).toBeTruthy();
    expect(screen.getByText(/required · official_url_backed_local_summary/)).toBeTruthy();
    expect(screen.getByText(/来源清单：data\/kb_import\/manifest\.json/)).toBeTruthy();
    expect(runEvaluation).toHaveBeenCalledWith();
  });

  it('shows a stable error without rendering raw backend payloads', async () => {
    getEvaluation.mockRejectedValue(new Error('Evaluation unavailable'));
    render(<RagEvaluationPanel />);
    expect((await screen.findByRole('alert')).textContent).toContain('Evaluation unavailable');
  });
});
