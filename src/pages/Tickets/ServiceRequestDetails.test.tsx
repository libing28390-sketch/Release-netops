import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import ServiceRequestDetails from './ServiceRequestDetails';
import type { ServiceRequestDetail } from './types';

const detail: ServiceRequestDetail = {
  request: {
    id: 'request-1',
    request_number: 'SR-20261024-01',
    ticket_key: 'SR-20261024-01',
    source_type: 'service_request',
    title: 'Create a monitoring account',
    status: 'in_progress',
    requester_username: 'alice',
    current_owner_username: 'netops',
    details: { username: 'poller' },
    catalog_snapshot: { id: 'cat-1', key: 'account', name: 'Monitoring account', version: 2, current_version: 2, request_schema: { fields: [{ key: 'username', label: 'Requested username', type: 'text' }] } },
    allowed_actions: ['deliver'],
  },
  events: [],
  sla: { configured: false, clocks: [{ kind: 'fulfillment', status: 'not_configured', configured: false, deadline_at: null, remaining_seconds: null }] },
};

const props = (onAction = vi.fn().mockResolvedValue(undefined)) => ({
  detail,
  loading: false,
  error: '',
  groups: [],
  actionLoading: false,
  actionError: '',
  onClose: vi.fn(),
  onRetry: vi.fn(),
  onAction,
  onLinkChangeOrder: vi.fn().mockResolvedValue(undefined),
  language: 'en',
});

describe('ServiceRequestDetails', () => {
  afterEach(() => cleanup());

  it('states plainly when a request has no configured time target', () => {
    render(<ServiceRequestDetails {...props()} />);
    expect(screen.getByText('No target configured')).toBeTruthy();
    expect(screen.getByText('Requested username').parentElement?.textContent).toContain('poller');
  });

  it('shows only backend-allowed actions and submits delivery evidence', async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    render(<ServiceRequestDetails {...props(onAction)} />);
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Submit delivery' }));
    fireEvent.change(screen.getByLabelText('Summary'), { target: { value: 'Account provisioned' } });
    fireEvent.change(screen.getByLabelText('Delivery evidence'), { target: { value: 'Username poller is active' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(onAction).toHaveBeenCalledWith('deliver', { summary: 'Account provisioned', evidence: 'Username poller is active' }));
  });

  it('shows visible linked change orders and only offers linking when authorized', async () => {
    const onLinkChangeOrder = vi.fn().mockResolvedValue(undefined);
    const linkedDetail: ServiceRequestDetail = {
      ...detail,
      request: { ...detail.request, allowed_actions: ['link_change_order'] },
      linked_change_orders: [{ id: 'change-1', order_number: 'CO-2026-001', title: 'Add a VLAN', status: 'approved' }],
    };
    render(<ServiceRequestDetails {...props()} detail={linkedDetail} onLinkChangeOrder={onLinkChangeOrder} />);

    const actionPanel = screen.getByText('Next action').closest('section');
    expect(actionPanel).not.toBeNull();
    expect(within(actionPanel as HTMLElement).queryByRole('button')).toBeNull();
    expect(screen.getByText('Use the linked change order section to associate an existing order.')).toBeTruthy();
    expect(screen.getByText(/CO-2026-001 · Add a VLAN/)).toBeTruthy();
    expect(screen.getByText('approved')).toBeTruthy();
    expect(screen.getByText('Configuration changes must use the existing change approval flow. This only links an existing change order.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Link an existing change order'), { target: { value: 'CO-2026-001' } });
    fireEvent.click(screen.getByRole('button', { name: 'Link' }));
    await waitFor(() => expect(onLinkChangeOrder).toHaveBeenCalledWith('CO-2026-001'));
  });

  it('closes the request detail dialog with Escape', () => {
    const onClose = vi.fn();
    render(<ServiceRequestDetails {...props()} onClose={onClose} />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
