import React, { type ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Zap } from 'lucide-react';
import type { SessionUser } from '../../../types';
import type { ChangeOrder } from '../types';
import { ChangeOrderDetail } from './ChangeOrderDetail';

vi.mock('./ChangeOrderWorkflowPanels', () => ({ ChangeOrderWorkflowPanels: () => null }));
vi.mock('./ControlSheetPanel', () => ({ ControlSheetPanel: () => null }));

type ChangeOrderDetailProps = ComponentProps<typeof ChangeOrderDetail>;

const requester: SessionUser = { id: 'requester-1', username: 'requester', role: 'Operator' };

const createOrder = (status: string): ChangeOrder => ({
  id: 'order-1',
  order_number: 'CO-1',
  title: 'Core switch change',
  description: '',
  order_type: 'config_change',
  priority: 'medium',
  status,
  requester_id: requester.id || '',
  requester_username: requester.username,
  assigned_initial_reviewer_id: '',
  assigned_initial_reviewer_username: '',
  assigned_final_approver_id: '',
  assigned_final_approver_username: '',
  initial_reviewer_id: '',
  initial_reviewer_username: '',
  final_approver_id: '',
  final_approver_username: '',
  approver_id: '',
  approver_username: '',
  target_devices: [],
  commands: [],
  rollback_plan: '',
  risk_level: 'low',
  scheduled_start: '',
  scheduled_end: '',
  actual_start: '',
  actual_end: '',
  result_summary: '',
  result_detail: {},
  rejected_reason: '',
  created_at: '2026-11-02T08:00:00Z',
  updated_at: '2026-11-02T08:00:00Z',
});

const createProps = (selectedOrder: ChangeOrder): ChangeOrderDetailProps => ({
  language: 'en',
  selectedOrder,
  onCloseDetail: vi.fn(),
  detailLoading: false,
  detailError: null,
  retryDetail: vi.fn(),
  currentUser: requester,
  users: [],
  timeline: [],
  timelineLoading: false,
  setTimeline: vi.fn(),
  bookmarkedIds: new Set<string>(),
  handleToggleBookmark: vi.fn(),
  handleCopyOrder: vi.fn(),
  handleSaveAsTemplate: vi.fn(),
  handleExportOrder: vi.fn(),
  openEdit: vi.fn(),
  getTransitionActions: () => [{ label: 'Submit Review', status: 'initial_review', variant: 'primary', icon: Zap }],
  handleTransition: vi.fn(),
  handleAssignment: vi.fn().mockResolvedValue({ success: true, order: selectedOrder }),
  handleVerification: vi.fn().mockResolvedValue({ success: true, order: selectedOrder }),
  handleResultReview: vi.fn(),
  handleEmergencyReview: vi.fn().mockResolvedValue({ success: true, order: selectedOrder }),
  handleControlSheetUpload: vi.fn().mockResolvedValue({ success: true }),
  handleControlSheetDownload: vi.fn(),
  setExecuteModal: vi.fn(),
  setActionPrompt: vi.fn(),
  setFinalApproverPrompt: vi.fn(),
  FEATURE_CONTROL_SHEET: false,
  platforms: {},
});

describe('ChangeOrderDetail initial review action', () => {
  afterEach(() => cleanup());

  it('opens the editor for a draft submission so the requester can choose an initial reviewer', () => {
    const order = createOrder('draft');
    const props = createProps(order);
    render(<ChangeOrderDetail {...props} />);

    fireEvent.click(screen.getByRole('button', { name: 'Submit Review' }));

    expect(props.openEdit).toHaveBeenCalledWith(order);
    expect(props.setActionPrompt).not.toHaveBeenCalled();
    expect(props.handleTransition).not.toHaveBeenCalled();
  });

  it('keeps the return reason prompt for a final-review rejection to initial review', () => {
    const props = createProps(createOrder('final_review'));
    render(<ChangeOrderDetail {...props} />);

    fireEvent.click(screen.getByRole('button', { name: 'Submit Review' }));

    expect(props.setActionPrompt).toHaveBeenCalledWith(expect.objectContaining({ title: 'Return reason', required: true }));
    const prompt = vi.mocked(props.setActionPrompt).mock.calls[0]?.[0];
    prompt?.onConfirm('Please update the impact analysis');
    expect(props.handleTransition).toHaveBeenCalledWith('order-1', 'initial_review', {
      rejected_reason: 'Please update the impact analysis',
    });
    expect(props.openEdit).not.toHaveBeenCalled();
  });
});
