import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import type { SessionUser, User } from '../../types';
import TicketsPage from './index';

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

const ticket = (overrides: Record<string, unknown> = {}) => ({
  id: 'ticket-1',
  ticket_number: 'INC-001',
  title: 'Core link is down',
  source_type: 'incident',
  source_id: 'ticket-1',
  ticket_key: 'INC-001',
  ticket_type: 'network',
  priority: 'high',
  status: 'open',
  requester_id: 'requester-1',
  requester_username: 'requester',
  assignment_group_id: 'group-1',
  assignment_group_name: 'Network Operations',
  assignee_id: 'operator-1',
  assignee_username: 'operator',
  incident_id: 'monitor-incident-1',
  ...overrides,
});

const currentUser: SessionUser = { id: 'operator-1', username: 'operator', role: 'Operator' };
const users: User[] = [{ id: 'operator-1', username: 'operator', role: 'Operator', status: 'active' }];

const LocationOutput = () => {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
};

const renderPage = (initialEntry = '/tickets', user: SessionUser = currentUser, pageUsers: User[] = users, language = 'en') => render(
  <MemoryRouter initialEntries={[initialEntry]}>
    <TicketsPage language={language} currentUser={user} users={pageUsers} />
    <LocationOutput />
  </MemoryRouter>,
);

describe('Tickets page list and detail workflow', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [ticket()], total: 1 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [{ id: 'group-1', name: 'Network Operations', active: true }] }));
      if (url === '/api/tickets/incidents/ticket-1') return Promise.resolve(response({ success: true, data: { ticket: ticket(), events: [], linked_change_orders: [] } }));
      return Promise.resolve(response({ success: true, data: ticket() }));
    }));
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('requests the first page with the default page size of ten', async () => {
    renderPage();
    expect(await screen.findByText('Core link is down')).toBeTruthy();
    const requestUrl = String(vi.mocked(fetch).mock.calls.find(([input]) => String(input).startsWith('/api/tickets?'))?.[0]);
    expect(requestUrl).toContain('page=1');
    expect(requestUrl).toContain('page_size=10');
    expect(requestUrl).toContain('type=all');
    expect((screen.getByLabelText('Items per page') as HTMLSelectElement).value).toBe('10');
  });

  it('shows the person and group together, but does not repeat a group-only owner', async () => {
    const tickets = [
      ticket({ id: 'person-ticket', title: 'Personal owner', assignee_id: 'operator-1', assignee_username: 'operator', current_owner_username: 'operator' }),
      ticket({ id: 'group-ticket', title: 'Group only', assignee_id: '', assignee_username: '', current_owner_username: 'Network Operations' }),
      ticket({ id: 'unassigned-ticket', title: 'Unassigned', assignee_id: '', assignee_username: '', current_owner_username: '', assignment_group_name: '' }),
    ];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: tickets.map((item) => ({ ...item, source_type: 'incident', source_id: item.id, ticket_key: item.ticket_number })), total: tickets.length }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      return Promise.resolve(response({ success: true, data: ticket() }));
    }));
    renderPage();

    await screen.findByText('Personal owner');
    const personRow = screen.getByRole('row', { name: /Personal owner/ });
    const groupRow = screen.getByRole('row', { name: /Group only/ });
    const unassignedRow = screen.getByRole('row', { name: /Unassigned/ });
    expect(personRow.textContent).toContain('operator · Network Operations');
    expect(personRow.textContent).toContain('Start work');
    expect(groupRow.textContent?.match(/Network Operations/g)).toHaveLength(1);
    expect(groupRow.textContent).toContain('Assign or claim');
    expect(unassignedRow.textContent).toContain('Unassigned');
  });

  it('shows the assignment group as the current owner in details when no person is assigned', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/tickets/incidents/ticket-1') return Promise.resolve(response({ success: true, data: {
        ticket: ticket({ assignee_id: '', assignee_username: '', current_owner_username: 'Network Operations' }),
        events: [],
        linked_change_orders: [],
      } }));
      return Promise.resolve(response({ success: true, data: ticket() }));
    }));
    renderPage('/tickets?ticket_id=ticket-1');

    expect(await screen.findByRole('dialog')).toBeTruthy();
    await waitFor(() => {
      const currentOwnerLabel = within(screen.getByRole('dialog')).getByText('Current owner');
      expect(currentOwnerLabel.parentElement?.textContent).toContain('Network Operations');
    });
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('opens a selected ticket, renders recovery actions, and links authorized change orders', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [ticket()], total: 1 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/tickets/incidents/ticket-1') return Promise.resolve(response({ success: true, data: {
        ticket: ticket({ status: 'in_progress', recovery_evidence: 'Ping stable for 15 minutes' }),
        events: [
          { id: 'event-1', action: 'started', actor_username: 'operator', summary: 'Started investigation', created_at: '2026-10-24T08:00:00Z' },
          { id: 'event-2', event_type: 'request_confirmation', actor_username: 'operator', details: { summary: 'Recovery submitted for review', evidence: 'Packet loss is 0%' } },
        ],
        linked_change_orders: [{ id: 'change-9', order_number: 'CO-9', title: 'Replace uplink', status: 'approved' }],
      } }));
      return Promise.resolve(response({ success: true, data: ticket({ status: 'pending_confirmation' }) }));
    }));
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Core link is down' }));
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(await screen.findByText('Ping stable for 15 minutes')).toBeTruthy();
    expect(screen.getByText('Started investigation')).toBeTruthy();
    expect(screen.getByText('Recovery submitted for review')).toBeTruthy();
    expect(screen.getByText('Packet loss is 0%')).toBeTruthy();
    expect(screen.queryByText('request_confirmation')).toBeNull();
    expect(screen.getByRole('button', { name: /CO-9 · Replace uplink/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Create a change order/ }));
    expect(screen.getByTestId('location').textContent).toContain('/change-orders/new?incident_ticket_id=ticket-1&incident_id=monitor-incident-1');
  });

  it('requests confirmation with a recovery summary and evidence', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [ticket()], total: 1 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/tickets/incidents/ticket-1') return Promise.resolve(response({ success: true, data: { ticket: ticket({ status: 'in_progress' }), events: [], linked_change_orders: [] } }));
      if (url.endsWith('/actions')) return Promise.resolve(response({ success: true, data: ticket({ status: 'pending_confirmation' }) }));
      return Promise.resolve(response({ success: true, data: ticket() }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage('/tickets?ticket_id=ticket-1');

    expect(await screen.findByRole('dialog')).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: 'Request confirmation' }));
    fireEvent.change(screen.getByLabelText('Summary'), { target: { value: 'Link recovered' } });
    fireEvent.change(screen.getByLabelText('Recovery evidence'), { target: { value: 'Ping and packet loss are stable' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));

    await waitFor(() => {
      const actionCall = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/actions') && init?.method === 'POST');
      expect(actionCall).toBeTruthy();
      expect(JSON.parse(String(actionCall?.[1]?.body))).toEqual({ action: 'request_confirmation', summary: 'Link recovered', evidence: 'Ping and packet loss are stable' });
    });
  });

  it('starts an open ticket with the start action body', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/tickets/incidents/ticket-1') return Promise.resolve(response({ success: true, data: { ticket: ticket(), events: [], linked_change_orders: [] } }));
      if (url.endsWith('/actions') && init?.method === 'POST') return Promise.resolve(response({ success: true, data: ticket({ status: 'in_progress' }) }));
      return Promise.resolve(response({ success: true, data: ticket() }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage('/tickets?ticket_id=ticket-1');

    fireEvent.click(await screen.findByRole('button', { name: 'Start work' }));
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));

    await waitFor(() => {
      const actionCall = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/actions') && init?.method === 'POST');
      expect(JSON.parse(String(actionCall?.[1]?.body))).toEqual({ action: 'start' });
    });
  });

  it('allows the requester to confirm a pending ticket closed', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/tickets/incidents/ticket-1') return Promise.resolve(response({ success: true, data: { ticket: ticket({ status: 'pending_confirmation' }), events: [], linked_change_orders: [] } }));
      if (url.endsWith('/actions') && init?.method === 'POST') return Promise.resolve(response({ success: true, data: ticket({ status: 'closed' }) }));
      return Promise.resolve(response({ success: true, data: ticket() }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage('/tickets?ticket_id=ticket-1', { id: 'requester-1', username: 'requester', role: 'Viewer' });

    fireEvent.click(await screen.findByRole('button', { name: 'Confirm close' }));
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));

    await waitFor(() => {
      const actionCall = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/actions') && init?.method === 'POST');
      expect(JSON.parse(String(actionCall?.[1]?.body))).toEqual({ action: 'confirm_close' });
    });
  });

  it('shows the backend error for a failed workflow action', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/tickets/incidents/ticket-1') return Promise.resolve(response({ success: true, data: { ticket: ticket({ status: 'in_progress' }), events: [], linked_change_orders: [] } }));
      if (url.endsWith('/actions') && init?.method === 'POST') return Promise.resolve(response({ detail: 'Recovery evidence is required' }, 422));
      return Promise.resolve(response({ success: true, data: ticket() }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage('/tickets?ticket_id=ticket-1');

    fireEvent.click(await screen.findByRole('button', { name: 'Request confirmation' }));
    fireEvent.change(screen.getByLabelText('Summary'), { target: { value: 'Service restored' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Recovery evidence is required');
  });

  it('does not expose state-changing actions to a viewer', async () => {
    renderPage('/tickets?ticket_id=ticket-1', { id: 'viewer-1', username: 'viewer', role: 'Viewer' });
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByText('This account can view this ticket but cannot change it.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Claim' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Start work' })).toBeNull();
  });

  it('loads assignment candidates from the selected responsibility group only', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [{ id: 'group-network', name: '网络运维组', active: true }] }));
      if (url === '/api/ticket-assignment-groups/group-network/members?ticket_id=m3-ticket-1') return Promise.resolve(response({ success: true, data: [
        { id: 'member-1', username: 'netops-oncall', display_name: '网络值班员' },
        { id: 'member-2', username: 'network-engineer', display_name: '网络工程师' },
      ] }));
      if (url === '/api/tickets/incidents/m3-ticket-1') return Promise.resolve(response({ success: true, data: { ticket: ticket({ id: 'm3-ticket-1', assignment_group_id: 'group-network', assignment_group_name: '网络运维组', assignee_id: '', assignee_username: '' }), events: [], linked_change_orders: [] } }));
      return Promise.resolve(response({ success: true, data: ticket() }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage('/tickets?ticket_id=m3-ticket-1', currentUser, [
      ...users,
      { id: 'unrelated-user', username: 'unrelated', display_name: 'Unrelated User', role: 'Operator', status: 'active' },
    ]);

    fireEvent.click(await screen.findByRole('button', { name: 'Assign' }));
    const assigneeSelect = await screen.findByLabelText('Group member') as HTMLSelectElement;
    await waitFor(() => {
      expect(assigneeSelect.disabled).toBe(false);
      expect(Array.from(assigneeSelect.options).some((option) => option.textContent === '网络值班员')).toBe(true);
      expect(Array.from(assigneeSelect.options).some((option) => option.textContent === '网络工程师')).toBe(true);
    });
    expect(Array.from(assigneeSelect.options).some((option) => option.textContent === 'Unrelated User')).toBe(false);
    expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/ticket-assignment-groups/group-network/members?ticket_id=m3-ticket-1')).toBe(true);
  });

  it('refreshes service catalog group member counts after adding and removing members', async () => {
    const groupMembers: Array<{ id: string; user_id: string; username: string; display_name: string }> = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups' && !init?.method) {
        return Promise.resolve(response({ success: true, data: [{ id: 'group-1', name: 'Network Operations', active: true, member_count: groupMembers.length }] }));
      }
      if (url === '/api/ticket-assignment-groups/group-1/members' && init?.method === 'POST') {
        groupMembers.push({ id: 'operator-1', user_id: 'operator-1', username: 'operator', display_name: 'Operator One' });
        return Promise.resolve(response({ success: true, data: {} }));
      }
      if (url === '/api/ticket-assignment-groups/group-1/members/operator-1' && init?.method === 'DELETE') {
        groupMembers.splice(0, groupMembers.length);
        return Promise.resolve(response({ success: true, data: {} }));
      }
      if (url === '/api/ticket-assignment-groups/group-1/members') return Promise.resolve(response({ success: true, data: groupMembers }));
      if (url === '/api/service-catalog' || url === '/api/ticket-sla-policies') return Promise.resolve(response({ success: true, data: [] }));
      return Promise.resolve(response({ success: true, data: {} }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage('/tickets', { id: 'admin-1', username: 'admin', role: 'Administrator' });

    const groupListRefreshCount = () => fetchMock.mock.calls.filter(([input, init]) => String(input) === '/api/ticket-assignment-groups' && !init?.method).length;
    await waitFor(() => expect(groupListRefreshCount()).toBe(1));
    fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
    const groupDialog = await screen.findByRole('dialog', { name: 'Assignment groups' });
    fireEvent.change(within(groupDialog).getByLabelText('Add member'), { target: { value: 'operator-1' } });
    fireEvent.click(within(groupDialog).getByRole('button', { name: 'Add' }));
    expect(await within(groupDialog).findByText('Operator One')).toBeTruthy();
    await waitFor(() => expect(groupListRefreshCount()).toBe(2));

    fireEvent.click(within(groupDialog).getByLabelText('Close'));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Assignment groups' })).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Service catalog' }));
    const catalogDialog = await screen.findByRole('dialog', { name: 'Service catalog' });
    const fulfillmentGroup = await within(catalogDialog).findByLabelText('Fulfillment group') as HTMLSelectElement;
    expect((within(fulfillmentGroup).getByRole('option', { name: 'Network Operations' }) as HTMLOptionElement).disabled).toBe(false);

    fireEvent.click(within(catalogDialog).getByLabelText('Close'));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Service catalog' })).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
    const reopenedGroupDialog = await screen.findByRole('dialog', { name: 'Assignment groups' });
    fireEvent.click(within(reopenedGroupDialog).getByRole('button', { name: 'Remove member operator' }));
    expect(await within(reopenedGroupDialog).findByText('This group has no members yet.')).toBeTruthy();
    await waitFor(() => expect(groupListRefreshCount()).toBe(3));

    fireEvent.click(within(reopenedGroupDialog).getByLabelText('Close'));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Assignment groups' })).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Service catalog' }));
    const refreshedCatalogDialog = await screen.findByRole('dialog', { name: 'Service catalog' });
    const refreshedFulfillmentGroup = await within(refreshedCatalogDialog).findByLabelText('Fulfillment group') as HTMLSelectElement;
    expect((within(refreshedFulfillmentGroup).getByRole('option', { name: 'Network Operations (no active members)' }) as HTMLOptionElement).disabled).toBe(true);
  }, 15000);

  it('lets an administrator create groups and add or remove group members', async () => {
    const directoryGroups = [{ id: 'group-1', name: 'Network Operations', description: 'Network', active: true }];
    const groupMembers: Record<string, Array<{ id: string; user_id: string; username: string; display_name: string }>> = { 'group-1': [] };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups' && init?.method === 'POST') {
        directoryGroups.push({ id: 'group-2', name: 'Application Operations', description: 'Apps', active: true });
        groupMembers['group-2'] = [];
        return Promise.resolve(response({ success: true, data: directoryGroups[1] }));
      }
      if (url === '/api/ticket-assignment-groups/group-2' && init?.method === 'PUT') {
        directoryGroups[1].name = JSON.parse(String(init.body)).name;
        directoryGroups[1].description = JSON.parse(String(init.body)).description;
        return Promise.resolve(response({ success: true, data: directoryGroups[1] }));
      }
      if (url === '/api/ticket-assignment-groups/group-2' && init?.method === 'DELETE') {
        directoryGroups.splice(1, 1);
        return Promise.resolve(response({ success: true, data: {} }));
      }
      if (url === '/api/ticket-assignment-groups' && !init?.method) return Promise.resolve(response({ success: true, data: directoryGroups }));
      if (url.endsWith('/members') && url.includes('/group-1/') && init?.method === 'POST') {
        groupMembers['group-1'].push({ id: 'operator-1', user_id: 'operator-1', username: 'operator', display_name: 'Operator One' });
        return Promise.resolve(response({ success: true, data: {} }));
      }
      if (url.endsWith('/members') && init?.method === 'POST') {
        groupMembers['group-2'].push({ id: 'operator-1', user_id: 'operator-1', username: 'operator', display_name: 'Operator One' });
        return Promise.resolve(response({ success: true, data: {} }));
      }
      if (url.endsWith('/members/operator-1') && init?.method === 'DELETE') {
        const groupId = url.includes('/group-1/') ? 'group-1' : 'group-2';
        groupMembers[groupId] = [];
        return Promise.resolve(response({ success: true, data: {} }));
      }
      const memberPath = url.match(/\/api\/ticket-assignment-groups\/([^/]+)\/members$/);
      if (memberPath) return Promise.resolve(response({ success: true, data: groupMembers[decodeURIComponent(memberPath[1])] || [] }));
      return Promise.resolve(response({ success: true, data: {} }));
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage('/tickets', { id: 'admin-1', username: 'admin', role: 'Administrator' }, [
      ...users,
      { id: 'disabled-user', username: 'disabled-user', display_name: 'Disabled User', role: 'Operator', status: 'disabled' },
      { id: 'legacy-user', username: 'legacy-user', display_name: 'Legacy User', role: 'Operator' },
    ]);

    await waitFor(() => expect((screen.getByRole('button', { name: 'Groups' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
    expect(await screen.findByRole('dialog', { name: 'Assignment groups' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Assignment groups' })).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
    expect(await screen.findByRole('dialog', { name: 'Assignment groups' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    fireEvent.change(screen.getByLabelText('Group name'), { target: { value: 'Application Operations' } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Apps' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create group' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input) === '/api/ticket-assignment-groups' && init?.method === 'POST')).toBe(true));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Assignment groups' })).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
    const groupPicker = await screen.findByLabelText('Select a group');
    fireEvent.change(groupPicker, { target: { value: 'group-2' } });
    fireEvent.change(screen.getByLabelText('Group name'), { target: { value: 'Application Operations Updated' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input) === '/api/ticket-assignment-groups/group-2' && init?.method === 'PUT')).toBe(true));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Assignment groups' })).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
    fireEvent.change(await screen.findByLabelText('Select a group'), { target: { value: 'group-2' } });
    const addMemberSelect = await screen.findByLabelText('Add member');
    expect(within(addMemberSelect).queryByRole('option', { name: 'Disabled User' })).toBeNull();
    expect(within(addMemberSelect).getByRole('option', { name: 'Legacy User' })).toBeTruthy();
    fireEvent.change(addMemberSelect, { target: { value: 'operator-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('Operator One')).toBeTruthy();
    expect(screen.getByRole('dialog', { name: 'Assignment groups' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Remove member operator' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/members/operator-1') && init?.method === 'DELETE')).toBe(true));
    expect(await screen.findByText('This group has no members yet.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Delete group' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input) === '/api/ticket-assignment-groups/group-2' && init?.method === 'DELETE')).toBe(true));
  }, 15000);

  it('filters to service requests and opens the source-specific detail view', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?') && url.includes('type=service_request')) return Promise.resolve(response({ success: true, data: [{
        source_type: 'service_request', request_id: 'request-2', ticket_key: 'SR-20261024-02', title: 'Create monitoring account',
        status: 'pending_confirmation', priority: 'P3', requester_username: 'alice', assignment_group_name: 'Platform Ops',
        current_owner_username: 'operator', assignee_username: 'operator', next_step: '等待申请人确认',
      }], total: 1 }));
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/service-requests/request-2') return Promise.resolve(response({ success: true, data: {
        request: {
          id: 'request-2', request_number: 'SR-20261024-02', ticket_key: 'SR-20261024-02', source_type: 'service_request',
          title: 'Create monitoring account', status: 'pending_confirmation', requester_username: 'alice',
          assignment_group_name: 'Platform Ops', assignee_username: 'operator', allowed_actions: [],
          catalog_snapshot: { id: 'catalog-1', key: 'account', name: 'Monitoring account', version: 1 }, details: {},
        },
        events: [],
        sla: { configured: true, clocks: [{ kind: 'fulfillment', status: 'running', configured: true, deadline_at: '2026-10-25T09:00:00Z', remaining_seconds: 3600, calendar_timezone: 'Asia/Shanghai' }] },
      } }));
      return Promise.resolve(response({ success: true, data: {} }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Service requests' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Create monitoring account' }));

    expect(await screen.findByRole('dialog', { name: 'Create monitoring account' })).toBeTruthy();
    expect(screen.getByText('Fulfillment')).toBeTruthy();
    expect(screen.getByText(/Asia\/Shanghai/)).toBeTruthy();
    expect(screen.getByTestId('location').textContent).toContain('/tickets?source_type=service_request&request_id=request-2');
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('type=service_request'))).toBe(true);
    expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/service-requests/request-2')).toBe(true);
  });

  it('shows incident time targets from the server and labels missing targets clearly', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/tickets/incidents/incident-sla') return Promise.resolve(response({ success: true, data: {
        ticket: ticket({
          id: 'incident-sla',
          title: 'SLA configured incident',
          sla: { configured: true, clocks: [{ kind: 'response', status: 'running', configured: true, deadline_at: '2026-10-25T09:00:00Z', remaining_seconds: 900, calendar_timezone: 'Asia/Shanghai' }] },
        }),
        events: [], linked_change_orders: [],
      } }));
      if (url === '/api/tickets/incidents/incident-no-sla') return Promise.resolve(response({ success: true, data: {
        ticket: ticket({ id: 'incident-no-sla', title: 'Unconfigured incident', sla: { configured: false, clocks: [{ kind: 'response', status: 'not_configured', configured: false, deadline_at: null, remaining_seconds: null, calendar_timezone: null }] } }),
        events: [], linked_change_orders: [],
      } }));
      return Promise.resolve(response({ success: true, data: [] }));
    }));

    renderPage('/tickets?ticket_id=incident-sla');
    expect(await screen.findByText('First response')).toBeTruthy();
    expect(screen.getByText(/15 min remaining/)).toBeTruthy();
    expect(screen.getByText('Asia/Shanghai')).toBeTruthy();
    cleanup();

    renderPage('/tickets?ticket_id=incident-no-sla', currentUser, users, 'zh');
    expect(await screen.findByText('未配置时限')).toBeTruthy();
  });

  it('keeps the expanded summary inside the page scroll area without clipping the ticket list', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/tickets/summary?')) return Promise.resolve(response({ success: true, data: {
        from: '2026-10-01', to: '2026-10-30',
        totals: { all: 0, incident: 0, service_request: 0, active: 0, closed: 0 },
        by_priority: [{ priority: 'P1', count: 0 }], by_assignment_group: [],
        durations_seconds: { first_response_avg: null, incident_restore_avg: null, service_fulfillment_avg: null, close_avg: null },
        sample_counts: { first_response_avg: 0, incident_restore_avg: 0, service_fulfillment_avg: 0, close_avg: 0 },
        duration_basis: 'elapsed_utc_ticket_events',
      } }));
      if (url.startsWith('/api/tickets?')) return Promise.resolve(response({ success: true, data: [], total: 0 }));
      if (url === '/api/ticket-assignment-groups') return Promise.resolve(response({ success: true, data: [] }));
      return Promise.resolve(response({ success: true, data: [] }));
    }));
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Ticket summary/ }));
    expect(await screen.findByText('Average durations')).toBeTruthy();
    expect(await screen.findByText('No tickets match these filters.')).toBeTruthy();
    const scrollArea = screen.getByTestId('tickets-main-scroll');
    const summaryPanel = screen.getByTestId('ticket-summary-panel');
    expect(scrollArea.className).toContain('overflow-auto');
    expect(summaryPanel.className).toContain('shrink-0');
    expect(summaryPanel.className).toContain('overflow-visible');
  });

  it('shows empty and loading states', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
    renderPage();
    expect(screen.getByText('Loading tickets…')).toBeTruthy();
    cleanup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ success: true, data: [], total: 0 })));
    renderPage();
    expect(await screen.findByText('No tickets match these filters.')).toBeTruthy();
  });
});
