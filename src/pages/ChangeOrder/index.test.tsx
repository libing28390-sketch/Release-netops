import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { SessionUser, User } from '../../types';
import type { ChangeOrder } from './types';
import ChangeOrderComponent from './index';

vi.mock('motion/react', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: (props: any) => {
      const divProps = Object.fromEntries(Object.entries(props).filter(([key]) => ![
        'children', 'initial', 'animate', 'exit', 'transition', 'whileHover',
      ].includes(key)));
      return <div {...divProps}>{props.children}</div>;
    },
  },
}));

const renderChangeOrders = (
  users: User[] = [],
  currentUser: SessionUser = { id: 'operator-1', username: 'operator', role: 'Operator', change_groups: [] },
  initialView: 'all' | 'group_todo' | 'my_todo' | 'my_participated' | 'my_focus' | 'my_drafts' | 'create' = 'all',
) => render(
  <MemoryRouter initialEntries={['/change-orders/all']}>
    <ChangeOrderComponent
      language="en"
      t={(key) => key}
      users={users}
      scenarios={[]}
      configTemplates={[]}
      platforms={{}}
      currentUser={currentUser}
      initialView={initialView}
      findMatchingPlatform={() => undefined}
    />
  </MemoryRouter>,
);

const reviewOrder: ChangeOrder = {
  id: 'order-1',
  order_number: 'CO-1',
  title: 'Core switch change',
  description: '',
  order_type: 'config_change',
  priority: 'medium',
  status: 'initial_review',
  requester_id: 'requester-1',
  requester_username: 'requester',
  assigned_initial_reviewer_id: 'reviewer-1',
  assigned_initial_reviewer_username: 'reviewer',
  assigned_final_approver_id: '',
  assigned_final_approver_username: '',
  initial_reviewer_id: '',
  initial_reviewer_username: '',
  final_approver_id: '',
  final_approver_username: '',
  approver_id: '',
  approver_username: '',
  target_devices: [],
  commands: ['show version'],
  rollback_plan: 'Restore previous configuration',
  risk_level: 'low',
  scheduled_start: '2026-10-21T10:00:00Z',
  scheduled_end: '2026-10-21T11:00:00Z',
  actual_start: '',
  actual_end: '',
  result_summary: '',
  result_detail: {},
  rejected_reason: '',
  created_at: '2026-10-21T09:00:00Z',
  updated_at: '2026-10-21T09:00:00Z',
};

describe('ChangeOrder list request states', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    const listResponses: Response[] = [
      { ok: false, status: 403, json: async () => ({ detail: 'Forbidden' }) } as Response,
      { ok: true, status: 200, json: async () => ({ success: true, data: [], total: 0 }) } as Response,
    ];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        return Promise.resolve(listResponses.shift() || { ok: true, status: 200, json: async () => ({ success: true, data: [], total: 0 }) } as Response);
      }
      if (url === '/api/change-orders/summary') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 0, by_status: {}, by_priority: {}, by_type: {} } }) } as Response);
      }
      if (url === '/api/change-orders-bookmarks') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it.each([
    ['pass', 'Accept results and close', 'completed'],
    ['fail', 'Escalate to initial reviewer', 'implementation_result_review'],
  ])('submits a designated result reviewer decision through the result-review contract: %s', async (action, label, nextStatus) => {
    const order: ChangeOrder = { ...reviewOrder, status: 'implementation_review',
      initial_reviewer_id: 'initial-id', initial_reviewer_username: 'initial',
      control_sheet: { implementer: { id: 'implementer', username: 'engineer' }, co_reviewer: { id: 'checker', username: 'checker' } },
    };
    const decisions: unknown[] = [];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      let data: unknown = [];
      if (url.startsWith('/api/change-orders?')) return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [order], total: 1 }) } as Response);
      if (url === '/api/change-orders/summary') data = { total: 1, by_status: { implementation_review: 1 }, by_priority: {}, by_type: {} };
      if (url === '/api/change-orders/order-1') data = order;
      if (url.endsWith('/result-review')) {
        decisions.push(JSON.parse(String(init?.body)));
        data = { ...order, status: nextStatus };
      }
      if (url === '/api/execute') throw new Error('Result review must not execute commands');
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data }) } as Response);
    }));
    renderChangeOrders([], { id: 'checker', username: 'checker', role: 'Viewer' });
    fireEvent.click(await screen.findByRole('button', { name: 'View change order CO-1' }));
    fireEvent.click(await screen.findByRole('button', { name: label }));
    fireEvent.change(screen.getByRole('textbox', { name: label }), { target: { value: 'Verified implementation result' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(decisions).toEqual([{ action, summary: 'Verified implementation result' }]));
    expect(screen.queryByRole('button', { name: 'Push Commands' })).toBeNull();
  });

  it('distinguishes a forbidden response from a healthy empty queue and can retry', async () => {
    renderChangeOrders();

    expect((await screen.findByRole('alert')).textContent).toContain('not authorized to view change orders');
    expect(screen.queryByText('No change orders')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(screen.getByText('No change orders')).toBeTruthy();
  });

  it('does not expose the unused device-login authorization exemption toggle to ordinary or administrator users', () => {
    renderChangeOrders([], { id: 'operator-1', username: 'operator', role: 'Operator' }, 'create');
    expect(screen.queryByText('Device Login Auth Exempt')).toBeNull();
    cleanup();

    renderChangeOrders([], { id: 'admin-1', username: 'admin', role: 'Administrator' }, 'create');
    expect(screen.queryByText('Device Login Auth Exempt')).toBeNull();
  });

  it('keeps the implementer out of co-reviewer and business confirmer choices and clears conflicts when roles change', () => {
    renderChangeOrders([
      { id: 'engineer-1', username: 'engineer', display_name: 'Engineer One', role: 'Operator' },
      { id: 'reviewer-1', username: 'reviewer', display_name: 'Reviewer One', role: 'Operator' },
    ], { id: 'requester-1', username: 'requester', role: 'Operator', change_groups: [] }, 'create');

    fireEvent.click(screen.getByText('Edit control sheet fields'));
    const implementer = screen.getByTitle('Select implementer') as HTMLSelectElement;
    const coReviewer = screen.getByTitle('Select reviewer') as HTMLSelectElement;
    expect(screen.getByText('Reviewer (optional)')).toBeTruthy();
    expect(within(coReviewer).getByRole('option', { name: 'No reviewer' })).toBeTruthy();
    const businessConfirmer = screen.getByTitle('Select business confirmer') as HTMLSelectElement;

    fireEvent.change(coReviewer, { target: { value: 'reviewer-1' } });
    fireEvent.change(businessConfirmer, { target: { value: 'reviewer-1' } });
    fireEvent.change(implementer, { target: { value: 'reviewer-1' } });

    expect(coReviewer.value).toBe('');
    expect(businessConfirmer.value).toBe('');
    expect(within(coReviewer).queryByRole('option', { name: /Reviewer One/ })).toBeNull();
    expect(within(businessConfirmer).queryByRole('option', { name: /Reviewer One/ })).toBeNull();
  });

  it('shows a permission error and retry when full order details are denied', async () => {
    let detailRequests = 0;
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [reviewOrder], total: 1 }) } as Response);
      }
      if (url === '/api/change-orders/summary') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { initial_review: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      }
      if (url === '/api/change-orders-bookmarks') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1/timeline') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        detailRequests += 1;
        return Promise.resolve(detailRequests === 1
          ? { ok: false, status: 403 } as Response
          : { ok: true, json: async () => ({ success: true, data: reviewOrder }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders(
      [{ id: 'approver-1', username: 'alex', display_name: 'Alex Admin', role: 'Administrator', change_groups: ['final_approver'] }],
      { id: 'reviewer-1', username: 'reviewer', role: 'Administrator', change_groups: ['initial_reviewer'] },
    );

    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));
    expect((await screen.findByRole('alert')).textContent).toContain('not authorized to load the full order details');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(detailRequests).toBe(2));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('keeps completion disabled for the assigned implementer until required verification passes', async () => {
    const implementingOrder: ChangeOrder = {
      ...reviewOrder,
      status: 'implementing',
      requester_id: 'requester-id',
      requester_username: 'requester',
      control_sheet: { implementer: { id: 'operator-1', username: 'operator' } },
      result_detail: { verification_records: [] },
    };
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [implementingOrder], total: 1 }) } as Response);
      }
      if (url === '/api/change-orders/summary') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { implementing: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      }
      if (url === '/api/change-orders-bookmarks') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1/timeline') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: implementingOrder }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders([], { id: 'operator-1', username: 'operator', role: 'Operator', change_groups: ['implementer'] });
    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));

    const complete = await screen.findByRole('button', { name: 'Complete' }) as HTMLButtonElement;
    expect(complete.disabled).toBe(true);
    expect(screen.getByText('Complete after technical verification passes')).toBeTruthy();
  });

  it('does not show implementation actions to the final approver or an administrator without an assignment', async () => {
    const implementingOrder: ChangeOrder = {
      ...reviewOrder,
      status: 'implementing',
      requester_id: 'requester-id',
      requester_username: 'requester',
      assigned_final_approver_id: 'approver-id',
      assigned_final_approver_username: 'approver',
      final_approver_id: 'approver-id',
      final_approver_username: 'approver',
      control_sheet: { implementer: { id: 'operator-1', username: 'operator' } },
    };
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [implementingOrder], total: 1 }) } as Response);
      }
      if (url === '/api/change-orders/summary') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { implementing: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      }
      if (url === '/api/change-orders-bookmarks') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1/timeline') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: implementingOrder }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders([], { id: 'approver-id', username: 'approver', role: 'Administrator', change_groups: [] });
    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));

    await screen.findByText('Current owner');
    expect(screen.queryByRole('button', { name: 'Push Commands' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Complete' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Start Implementing' })).toBeNull();
  });

  it('uses normal device credentials for an Operator and blocks blind re-execution after a sent request fails', async () => {
    const implementingOrder: ChangeOrder = {
      ...reviewOrder,
      status: 'implementing',
      requester_id: 'requester-id',
      requester_username: 'requester',
      target_devices: [{ hostname: 'core-sw', ip_address: '10.0.0.1' }],
      commands: ['show ip interface brief'],
      control_sheet: { implementer: { id: 'operator-1', username: 'operator' } },
      result_detail: { approval_snapshot_hash: 'snapshot-1', approval_snapshot_version: 1 },
    };
    const executionBodies: Array<Record<string, unknown>> = [];
    let executionRequests = 0;
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [implementingOrder], total: 1 }) } as Response);
      }
      if (url === '/api/change-orders/summary') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { implementing: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      }
      if (url === '/api/change-orders-bookmarks') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1/timeline') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: implementingOrder }) } as Response);
      }
      if (url === '/api/devices?mode=light') {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 'device-1', hostname: 'core-sw', ip_address: '10.0.0.1' }] }) } as Response);
      }
      if (url === '/api/execute') {
        executionRequests += 1;
        executionBodies.push(JSON.parse(String(init?.body || '{}')) as Record<string, unknown>);
        return Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: 'Authorization already consumed' }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders([], { id: 'operator-1', username: 'operator', role: 'Operator', change_groups: ['implementer'] });
    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Push Commands' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm & Push' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Authorization already consumed');
    expect(screen.getByRole('note').textContent).toContain('Verify the actual device state first');
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
    expect(executionBodies[0]?.auth_role).toBe('normal');

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    const requestSentButton = await screen.findByRole('button', { name: 'Request sent' }) as HTMLButtonElement;
    expect(requestSentButton.disabled).toBe(true);
    expect(screen.queryByRole('button', { name: 'Push Commands' })).toBeNull();
    expect(executionRequests).toBe(1);
  });

  it('clears a temporary final approver selection when its prompt is dismissed with Escape', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [reviewOrder], total: 1 }) } as Response);
      }
      if (url === '/api/change-orders/summary') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { initial_review: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      }
      if (url === '/api/change-orders-bookmarks') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/assignment-options') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [{ id: 'approver-1', username: 'alex', display_name: 'Alex Admin', role: 'Administrator', change_groups: ['final_approver'] }] }) } as Response);
      }
      if (url === '/api/change-orders/order-1/timeline') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: reviewOrder }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders(
      [{ id: 'approver-1', username: 'alex', display_name: 'Alex Admin', role: 'Administrator', change_groups: ['final_approver'] }],
      { id: 'reviewer-1', username: 'reviewer', role: 'Administrator', change_groups: ['initial_reviewer'] },
    );

    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Pass Initial Review' }));

    const finalApproverDialog = await screen.findByRole('dialog', { name: 'Select Final Approver' });
    const firstSelection = screen.getByRole('radio', { name: /Alex Admin/ }) as HTMLInputElement;
    fireEvent.click(firstSelection);
    expect(firstSelection.checked).toBe(true);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Select Final Approver' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Pass Initial Review' }));
    expect(await screen.findByRole('dialog', { name: 'Select Final Approver' })).toBeTruthy();
    expect((screen.getByRole('radio', { name: /Alex Admin/ }) as HTMLInputElement).checked).toBe(false);
    expect(finalApproverDialog).toBeTruthy();
  });

  it('shows a bilingual message for a structured resource-scope 403 after MFA submission without crashing', async () => {
    const approvedOrder: ChangeOrder = {
      ...reviewOrder,
      status: 'approved',
      requester_id: 'operator-1',
      requester_username: 'operator',
      assigned_final_approver_id: 'approver-1',
      assigned_final_approver_username: 'approver',
      final_approver_id: 'approver-1',
      final_approver_username: 'approver',
      approver_id: 'approver-1',
      approver_username: 'approver',
      control_sheet: { implementer: { id: 'operator-1', username: 'operator' } },
      control_sheet_attachments: [{
        id: 'attachment-1',
        file_name: 'change-plan.pdf',
        file_size: 100,
        created_at: '2026-10-26T09:00:00Z',
        sha256: 'digest',
      }],
      result_detail: { approval_snapshot_hash: 'snapshot-1', approval_snapshot_version: 1 },
      scheduled_start: new Date(Date.now() - 60_000).toISOString(),
      scheduled_end: new Date(Date.now() + 60_000).toISOString(),
    };
    const transitionBodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [approvedOrder], total: 1 }) } as Response);
      }
      if (url === '/api/change-orders/summary') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { approved: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      }
      if (url === '/api/change-orders-bookmarks' || url === '/api/change-orders/assignment-options') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1/timeline') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: approvedOrder }) } as Response);
      }
      if (url.endsWith('/transition')) {
        transitionBodies.push(JSON.parse(String(init?.body || '{}')) as Record<string, unknown>);
        return Promise.resolve({
          ok: false,
          status: 403,
          json: async () => ({ detail: {
            code: 'RESOURCE_SCOPE_DENIED',
            message: 'Insufficient permission for this resource scope',
            resource_type: 'command',
            action: 'execute',
          } }),
        } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders([], { id: 'operator-1', username: 'operator', role: 'Operator', change_groups: [] });
    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Start Implementing' }));
    fireEvent.change(screen.getByLabelText('Enter the code from your authenticator'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(await screen.findByText('You are not authorized to execute commands on these devices. Ask an administrator to review access.')).toBeTruthy();
    expect(screen.getByText('Core switch change')).toBeTruthy();
    expect(transitionBodies).toEqual([{ status: 'implementing', mfa_code: '123456' }]);
  });

  it('disables implementation until at least one control sheet attachment is present', async () => {
    const approvedOrder: ChangeOrder = {
      ...reviewOrder,
      status: 'approved',
      control_sheet: { implementer: { id: 'operator-1', username: 'operator' } },
      control_sheet_attachments: [],
      result_detail: { approval_snapshot_hash: 'snapshot-1', approval_snapshot_version: 1 },
      scheduled_start: new Date(Date.now() - 60_000).toISOString(),
      scheduled_end: new Date(Date.now() + 60_000).toISOString(),
    };
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [approvedOrder], total: 1 }) } as Response);
      if (url === '/api/change-orders/summary') return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { approved: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      if (url === '/api/change-orders-bookmarks' || url === '/api/change-orders/assignment-options') return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      if (url === '/api/change-orders/order-1/timeline') return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      if (url === '/api/change-orders/order-1') return Promise.resolve({ ok: true, json: async () => ({ success: true, data: approvedOrder }) } as Response);
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders([], { id: 'operator-1', username: 'operator', role: 'Operator', change_groups: [] });
    fireEvent.click(await screen.findByRole('button', { name: 'View change order CO-1' }));
    const implement = await screen.findByRole('button', { name: 'Start Implementing' }) as HTMLButtonElement;
    expect(implement.disabled).toBe(true);
    expect(implement.title).toBe('Upload at least one control sheet attachment before implementation.');
    expect(screen.getByText('Upload at least one PDF, Word, or Excel control sheet attachment before implementation.')).toBeTruthy();
  });

  it('uploads a control sheet file and refreshes the order, activity timeline, and list', async () => {
    const initialOrder: ChangeOrder = {
      ...reviewOrder,
      status: 'approved',
      requester_id: 'requester-1',
      requester_username: 'requester',
      control_sheet: { pre_check: 'show version' },
      control_sheet_attachments: [],
    };
    const refreshedOrder: ChangeOrder = {
      ...initialOrder,
      status: 'initial_review',
      control_sheet_attachments: [{
        id: 'attachment-1',
        file_name: 'change-plan.pdf',
        file_size: 100,
        created_at: '2026-10-26T09:00:00Z',
        sha256: 'digest',
      }],
    };
    let activeOrder = initialOrder;
    let detailRequests = 0;
    let timelineRequests = 0;
    let listRequests = 0;
    let uploadBody: BodyInit | null | undefined;
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/change-orders?')) {
        listRequests += 1;
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [activeOrder], total: 1 }) } as Response);
      }
      if (url === '/api/change-orders/summary') return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { total: 1, by_status: { [activeOrder.status]: 1 }, by_priority: {}, by_type: {} } }) } as Response);
      if (url === '/api/change-orders-bookmarks' || url === '/api/change-orders/assignment-options') return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      if (url === '/api/change-orders/order-1/timeline') {
        timelineRequests += 1;
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        detailRequests += 1;
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: activeOrder }) } as Response);
      }
      if (url === '/api/change-orders/order-1/control-sheet') {
        uploadBody = init?.body;
        activeOrder = refreshedOrder;
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: { id: 'attachment-1', filename: 'change-plan.pdf' } }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders([], { id: 'requester-1', username: 'requester', role: 'Operator', change_groups: [] });
    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));
    const file = new File(['change plan'], 'change-plan.pdf', { type: 'application/pdf' });
    fireEvent.change(await screen.findByLabelText('Upload control sheet attachment'), { target: { files: [file] } });

    await waitFor(() => expect(activeOrder.status).toBe('initial_review'));
    await waitFor(() => expect(detailRequests).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(timelineRequests).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(listRequests).toBeGreaterThanOrEqual(2));
    expect(uploadBody).toBeInstanceOf(FormData);
    expect(await screen.findByText('change-plan.pdf')).toBeTruthy();
    expect(screen.getAllByText('Initial Review').length).toBeGreaterThan(0);
    expect(screen.getByRole('status').textContent).toContain('needs approval again');
  });
});
