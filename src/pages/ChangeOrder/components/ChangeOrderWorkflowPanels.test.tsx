import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { SessionUser, User } from '../../../types';
import type { ChangeOrder } from '../types';
import { ChangeOrderWorkflowPanels, type ChangeOrderMutationResult } from './ChangeOrderWorkflowPanels';

const createOrder = (overrides: Partial<ChangeOrder> = {}): ChangeOrder => ({
  id: 'order-1',
  order_number: 'CO-1',
  title: 'Core switch change',
  description: '',
  order_type: 'config_change',
  priority: 'medium',
  status: 'approved',
  requester_id: 'requester-id',
  requester_username: 'requester',
  assigned_initial_reviewer_id: 'reviewer-id',
  assigned_initial_reviewer_username: 'reviewer',
  assigned_final_approver_id: 'approver-id',
  assigned_final_approver_username: 'approver',
  initial_reviewer_id: 'reviewer-id',
  initial_reviewer_username: 'reviewer',
  final_approver_id: 'approver-id',
  final_approver_username: 'approver',
  approver_id: 'approver-id',
  approver_username: 'approver',
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
  control_sheet: {},
  created_at: '',
  updated_at: '',
  ...overrides,
});

const renderPanels = (options: {
  order?: ChangeOrder;
  currentUser?: SessionUser;
  users?: User[];
  onAssignment?: (orderId: string, request: any) => Promise<ChangeOrderMutationResult>;
  onVerification?: (orderId: string, request: any) => Promise<ChangeOrderMutationResult>;
} = {}) => {
  const props = {
    language: 'en',
    order: options.order || createOrder(),
    currentUser: options.currentUser || { id: 'requester-id', username: 'requester', role: 'Operator' },
    users: options.users || [],
    onAssignment: options.onAssignment || vi.fn(async () => ({ success: true as const, order: options.order || createOrder() })),
    onVerification: options.onVerification || vi.fn(async () => ({ success: true as const, order: options.order || createOrder() })),
  };
  return { ...render(<ChangeOrderWorkflowPanels {...props} />), props };
};

describe('ChangeOrderWorkflowPanels', () => {
  afterEach(() => cleanup());

  it('shows the requester, assigned implementer, reviewers, and confirmer', () => {
    const order = createOrder({
      control_sheet: {
        implementer: { id: 'implementer-id', username: 'engineer' },
        business_confirmer: { id: 'confirmer-id', username: 'service-owner' },
      },
      result_detail: {
        assignment_events: [{
          action: 'transfer',
          actor_id: 'lead-id',
          actor_username: 'lead',
          from_implementer_id: 'old-implementer',
          from_username: 'old',
          to_implementer_id: 'implementer-id',
          to_username: 'engineer',
          implementer_id: 'implementer-id',
          implementer_username: 'engineer',
          reason: 'Coverage change',
          created_at: '2026-10-24T10:00:00Z',
        }],
      },
    });
    renderPanels({ order });

    expect(screen.getByText('requester')).toBeTruthy();
    expect(screen.getByText('engineer')).toBeTruthy();
    expect(screen.getByText('reviewer')).toBeTruthy();
    expect(screen.getByText('approver')).toBeTruthy();
    expect(screen.getByText('service-owner')).toBeTruthy();
    expect(screen.getByText('Reviewer')).toBeTruthy();
    fireEvent.click(screen.getByText('View most recent handoff'));
    expect(screen.getByText(/old → engineer/)).toBeTruthy();
    expect(screen.getByText(/Coverage change/)).toBeTruthy();
  });

  it('does not expose claim or assignment controls to the final approver or admin-only managers', () => {
    const order = createOrder({ control_sheet: {} });
    const approverProps = renderPanels({
      order,
      currentUser: { id: 'approver-id', username: 'approver', role: 'Administrator' },
      users: [{ id: 'implementer-id', username: 'engineer', role: 'Operator', change_groups: ['implementer'] }],
    });
    expect(screen.queryByRole('button', { name: 'Claim order' })).toBeNull();
    expect(screen.queryByText('Change implementer')).toBeNull();
    approverProps.unmount();

    renderPanels({
      order,
      currentUser: { id: 'admin-id', username: 'admin', role: 'Administrator' },
      users: [{ id: 'implementer-id', username: 'engineer', role: 'Operator', change_groups: ['implementer'] }],
    });
    expect(screen.queryByRole('button', { name: 'Claim order' })).toBeNull();
    fireEvent.click(screen.getByText('Assign implementer'));
    expect(screen.getByLabelText('Implementer')).toBeTruthy();
    expect(screen.getByText('Administrative access manages assignment; it does not grant execution authorization.')).toBeTruthy();
  });

  it('lets an eligible operator claim an unassigned order through the assignment contract', async () => {
    const onAssignment = vi.fn(async () => ({ success: true, order: createOrder({ control_sheet: { implementer: { id: 'operator-id', username: 'operator' } } }) } as const));
    renderPanels({
      order: createOrder({ control_sheet: {} }),
      currentUser: { id: 'operator-id', username: 'operator', role: 'Operator' },
      onAssignment,
    });

    fireEvent.click(screen.getByRole('button', { name: 'Claim order' }));
    expect(await screen.findByRole('status')).toBeTruthy();
    expect(onAssignment).toHaveBeenCalledWith('order-1', { action: 'claim' });
  });

  it('submits a reasoned transfer and displays the API detail error', async () => {
    const onAssignment = vi.fn(async () => ({ success: false, message: 'Transfer requires a reason' } as const));
    renderPanels({
      order: createOrder({ control_sheet: { implementer: { id: 'old-implementer', username: 'old' } } }),
      users: [{ id: 'new-implementer', username: 'new', role: 'Operator', change_groups: ['implementer'] }],
      onAssignment,
    });

    fireEvent.click(screen.getByText('Change implementer'));
    fireEvent.change(screen.getByLabelText('Implementer'), { target: { value: 'new-implementer' } });
    fireEvent.change(screen.getByLabelText('Handoff reason'), { target: { value: 'Coverage change' } });
    fireEvent.click(screen.getByRole('button', { name: 'Transfer' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Transfer requires a reason');
    expect(onAssignment).toHaveBeenCalledWith('order-1', {
      action: 'transfer',
      implementer_id: 'new-implementer',
      reason: 'Coverage change',
    });
  });

  it('submits technical failure summaries and evidence, then surfaces API errors', async () => {
    const order = createOrder({
      status: 'implementing',
      control_sheet: { implementer: { id: 'implementer-id', username: 'engineer' } },
      result_detail: { approval_snapshot_hash: 'snapshot-1', approval_snapshot_version: 1 },
    });
    const onVerification = vi.fn(async () => ({ success: false, message: 'Verifier cannot be the implementer' } as const));
    renderPanels({
      order,
      currentUser: { id: 'reviewer-id', username: 'reviewer', role: 'Operator' },
      onVerification,
    });

    const technical = screen.getByRole('region', { name: 'Technical verification' });
    fireEvent.click(within(technical).getByText('Record verification result'));
    fireEvent.click(within(technical).getByRole('radio', { name: 'Failed' }));
    fireEvent.change(within(technical).getByLabelText('Technical verification summary'), { target: { value: 'Interface state did not recover' } });
    fireEvent.change(within(technical).getByLabelText('Technical verification evidence'), { target: { value: 'show interface Gi1/0/1' } });
    fireEvent.click(within(technical).getByRole('button', { name: 'Submit result' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Verifier cannot be the implementer');
    expect(onVerification).toHaveBeenCalledWith('order-1', {
      kind: 'technical',
      result: 'failed',
      summary: 'Interface state did not recover',
      evidence: 'show interface Gi1/0/1',
    });
  });

  it('lets the requester submit business verification and preserves stored verification records', async () => {
    const order = createOrder({
      status: 'implementing',
      control_sheet: {
        implementer: { id: 'implementer-id', username: 'engineer' },
        business_verify: 'Service owner confirms the application works',
        business_confirmer: { id: 'confirmer-id', username: 'service-owner' },
      },
      result_detail: {
        approval_snapshot_hash: 'snapshot-1',
        approval_snapshot_version: 1,
        verification_records: [{ kind: 'technical', result: 'passed', summary: 'Interface and route checks passed', verifier_username: 'reviewer' }],
      },
    });
    const onVerification = vi.fn(async () => ({ success: true, order } as const));
    renderPanels({ order, onVerification });

    expect(screen.getByText('Interface and route checks passed')).toBeTruthy();
    const business = screen.getByRole('region', { name: 'Business verification' });
    fireEvent.click(within(business).getByText('Record verification result'));
    fireEvent.change(within(business).getByLabelText('Business verification summary'), { target: { value: 'User flow completed successfully' } });
    fireEvent.change(within(business).getByLabelText('Business verification evidence'), { target: { value: 'Ticket INC-42' } });
    fireEvent.click(within(business).getByRole('button', { name: 'Submit result' }));

    expect(onVerification).toHaveBeenCalledWith('order-1', {
      kind: 'business',
      result: 'passed',
      summary: 'User flow completed successfully',
      evidence: 'Ticket INC-42',
    });
  });
});
