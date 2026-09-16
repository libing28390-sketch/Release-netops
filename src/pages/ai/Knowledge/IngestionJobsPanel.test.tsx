import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IngestionJobsPanel from './IngestionJobsPanel';
import { getKnowledgeIngestionJobErrors, listKnowledgeIngestionJobs, retryKnowledgeIngestionJob } from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  getKnowledgeIngestionJobErrors: vi.fn(),
  listKnowledgeIngestionJobs: vi.fn(),
  retryKnowledgeIngestionJob: vi.fn(),
}));

const listJobs = vi.mocked(listKnowledgeIngestionJobs);
const getErrors = vi.mocked(getKnowledgeIngestionJobErrors);
const retryJob = vi.mocked(retryKnowledgeIngestionJob);

const failedJob = {
  id: 'ing_failed_001',
  job_kind: 'document_import',
  execution_state: 'failed',
  phase: 'failed',
  total_count: 4,
  processed_count: 2,
  parsed_count: 2,
  failed_count: 2,
  succeeded_count: 0,
  skipped_count: 0,
  retryable_failed_count: 1,
  error_count: 1,
  progress_percent: 50,
  retry_count: 0,
  max_retries: 2,
  attempt_no: 1,
  last_error_code: 'SOURCE_TIMEOUT',
  created_at: '2026-08-17T08:00:00Z',
  updated_at: '2026-08-17T08:01:00Z',
};

describe('IngestionJobsPanel', () => {
  beforeEach(() => {
    listJobs.mockResolvedValue({ items: [failedJob as any], total: 1, page: 1, page_size: 20, total_pages: 1 });
    getErrors.mockResolvedValue({
      job_id: failedJob.id,
      phase: 'failed',
      execution_state: 'failed',
      last_error_code: 'SOURCE_TIMEOUT',
      error_count: 1,
      errors: [{ code: 'SOURCE_TIMEOUT', safe_message: '官方来源响应超时，可重试。', phase: 'fetched', retryable: true, occurred_at: '2026-08-17T08:01:00Z' }],
    });
    retryJob.mockResolvedValue(failedJob as any);
  });

  afterEach(() => cleanup());

  it('shows server-paged progress, safe error details, and retries a failed job', async () => {
    const user = userEvent.setup();
    render(<IngestionJobsPanel />);

    expect(await screen.findByText('ing_failed_001')).toBeTruthy();
    expect(screen.getByText('50.00%')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '错误详情' }));
    expect(await screen.findByText('官方来源响应超时，可重试。')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(retryJob).toHaveBeenCalledWith('ing_failed_001');
    expect(listJobs).toHaveBeenCalledTimes(2);
  });

  it('resets the page and sends server-side filters', async () => {
    const user = userEvent.setup();
    render(<IngestionJobsPanel />);
    await screen.findByText('ing_failed_001');

    await user.selectOptions(screen.getByRole('combobox', { name: '导入任务状态' }), 'failed');
    await user.type(screen.getByPlaceholderText('搜索任务 ID、类型、阶段或错误码'), 'timeout');
    await user.click(screen.getByRole('button', { name: '搜索' }));

    expect(listJobs).toHaveBeenLastCalledWith(expect.objectContaining({ executionState: 'failed', search: 'timeout', page: 1, pageSize: 20 }));
  });

  it('renders an actionable empty or request error state', async () => {
    listJobs.mockRejectedValueOnce(new Error('任务服务暂不可用'));
    render(<IngestionJobsPanel />);
    expect((await screen.findByRole('alert')).textContent).toContain('任务服务暂不可用');
  });
});
