import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RagEvaluationPanel from './RagEvaluationPanel';
import { getKnowledgeEvaluation, runKnowledgeEvaluation } from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  getKnowledgeEvaluation: vi.fn(),
  runKnowledgeEvaluation: vi.fn(),
}));

const getEvaluation = vi.mocked(getKnowledgeEvaluation);
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
  cases: [{ id: 'Q01', query: 'show ospf peer', retrieval_correct: true, citation_precision: 1, vendor_mismatch: false, version_conflict: false, latency_ms: 1 }],
};

describe('RagEvaluationPanel', () => {
  beforeEach(() => {
    getEvaluation.mockResolvedValue(emptyReport as any);
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
    expect(runEvaluation).toHaveBeenCalledWith();
  });

  it('shows a stable error without rendering raw backend payloads', async () => {
    getEvaluation.mockRejectedValue(new Error('Evaluation unavailable'));
    render(<RagEvaluationPanel />);
    expect((await screen.findByRole('alert')).textContent).toContain('Evaluation unavailable');
  });
});
