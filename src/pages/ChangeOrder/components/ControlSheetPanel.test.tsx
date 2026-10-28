import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { SessionUser } from '../../../types';
import type { ChangeOrder } from '../types';
import { ControlSheetPanel } from './ControlSheetPanel';

const approvedOrder: ChangeOrder = {
  id: 'order-1',
  order_number: 'CO-1',
  title: 'Core switch change',
  description: '',
  order_type: 'config_change',
  priority: 'medium',
  status: 'approved',
  requester_id: 'requester-1',
  requester_username: 'requester',
  assigned_initial_reviewer_id: '',
  assigned_initial_reviewer_username: '',
  assigned_final_approver_id: 'approver-1',
  assigned_final_approver_username: 'approver',
  initial_reviewer_id: '',
  initial_reviewer_username: '',
  final_approver_id: 'approver-1',
  final_approver_username: 'approver',
  approver_id: 'approver-1',
  approver_username: 'approver',
  target_devices: [],
  commands: ['show version'],
  rollback_plan: '',
  risk_level: 'low',
  scheduled_start: '',
  scheduled_end: '',
  actual_start: '',
  actual_end: '',
  result_summary: '',
  result_detail: {},
  rejected_reason: '',
  control_sheet: { pre_check: 'show version' },
  control_sheet_attachments: [],
  created_at: '',
  updated_at: '',
};

const requester: SessionUser = { id: 'requester-1', username: 'requester', role: 'Operator' };

describe('ControlSheetPanel attachments', () => {
  afterEach(cleanup);

  it('lets the requester upload an approved order attachment and explains that approval must be repeated', async () => {
    const onUpload = vi.fn().mockResolvedValue({ success: true, requiresReview: true });
    render(<ControlSheetPanel language="en" selectedOrder={approvedOrder} currentUser={requester} onUpload={onUpload} onDownload={vi.fn()} />);

    expect(screen.getByText('Uploading during review, after approval, or during implementation returns the order to initial review and requires approval again.')).toBeTruthy();
    expect(screen.getByText('Upload at least one PDF, Word, or Excel control sheet attachment before implementation.')).toBeTruthy();
    const file = new File(['change plan'], 'change-plan.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('Upload control sheet attachment'), { target: { files: [file] } });

    await waitFor(() => expect(onUpload).toHaveBeenCalledWith('order-1', file));
    expect((await screen.findByRole('status')).textContent).toContain('The order returned to initial review and needs approval again.');
  });

  it('hides upload from an unrelated user and validates file type before calling the API', async () => {
    const onUpload = vi.fn();
    render(<ControlSheetPanel
      language="en"
      selectedOrder={approvedOrder}
      currentUser={{ id: 'other-user', username: 'other', role: 'Operator' }}
      onUpload={onUpload}
      onDownload={vi.fn()}
    />);
    expect(screen.queryByLabelText('Upload control sheet attachment')).toBeNull();

    cleanup();
    render(<ControlSheetPanel language="en" selectedOrder={approvedOrder} currentUser={requester} onUpload={onUpload} onDownload={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Upload control sheet attachment'), {
      target: { files: [new File(['script'], 'commands.txt', { type: 'text/plain' })] },
    });

    expect((await screen.findByRole('alert')).textContent).toContain('Only PDF, Word, and Excel files are supported.');
    expect(onUpload).not.toHaveBeenCalled();
  });

  it('renders persisted attachment fields and delegates authenticated download by attachment id', () => {
    const onDownload = vi.fn();
    const detailOrder: ChangeOrder = {
      ...approvedOrder,
      control_sheet_attachments: [{
        id: 'attachment-1',
        file_name: 'change-plan.xlsx',
        file_size: 2048,
        created_at: '2026-10-26T09:00:00Z',
        sha256: 'digest',
      }],
    };
    render(<ControlSheetPanel
      language="en"
      selectedOrder={detailOrder}
      currentUser={requester}
      onUpload={vi.fn()}
      onDownload={onDownload}
    />);

    expect(screen.getByText('change-plan.xlsx')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Download attachment' }));
    expect(onDownload).toHaveBeenCalledWith('order-1', 'attachment-1', 'change-plan.xlsx');
  });
});
