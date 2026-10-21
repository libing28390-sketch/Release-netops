import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
      initialView="all"
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

  it('distinguishes a forbidden response from a healthy empty queue and can retry', async () => {
    renderChangeOrders();

    expect((await screen.findByRole('alert')).textContent).toContain('not authorized to view change orders');
    expect(screen.queryByText('No change orders')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(screen.getByText('No change orders')).toBeTruthy();
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
      [{ id: 'approver-1', username: 'alex', display_name: 'Alex Admin', role: 'Administrator' }],
      { id: 'reviewer-1', username: 'reviewer', role: 'Operator', change_groups: [] },
    );

    await screen.findByText('CO-1');
    fireEvent.click(screen.getByRole('button', { name: 'View change order CO-1' }));
    expect((await screen.findByRole('alert')).textContent).toContain('not authorized to load the full order details');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(detailRequests).toBe(2));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
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
      if (url === '/api/change-orders/order-1/timeline') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
      }
      if (url === '/api/change-orders/order-1') {
        return Promise.resolve({ ok: true, json: async () => ({ success: true, data: reviewOrder }) } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, data: [] }) } as Response);
    }));

    renderChangeOrders(
      [{ id: 'approver-1', username: 'alex', display_name: 'Alex Admin', role: 'Administrator' }],
      { id: 'reviewer-1', username: 'reviewer', role: 'Operator', change_groups: [] },
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
});
