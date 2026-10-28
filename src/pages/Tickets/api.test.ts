import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildIncidentTicketPath, createOrOpenIncidentTicket, getTicketSummary, linkServiceRequestChangeOrder, listUnifiedTickets } from './api';

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

describe('incident ticket creation from monitoring', () => {
  beforeEach(() => localStorage.setItem('netops_token', 'test-token'));
  afterEach(() => {
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('creates or opens the incident ticket and builds a deep link to the returned ticket', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, data: { id: 'ticket-7', title: 'Link down' }, created: false }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await createOrOpenIncidentTicket('incident/7');

    expect(fetchMock).toHaveBeenCalledWith('/api/tickets/from-incident/incident%2F7', expect.objectContaining({ method: 'POST' }));
    expect(result.created).toBe(false);
    expect(result.ticket.id).toBe('ticket-7');
    expect(buildIncidentTicketPath(result.ticket.id)).toBe('/tickets?ticket_id=ticket-7');
  });

  it('shows the backend error detail when ticket creation fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: 'Incident already closed' }, 409)));
    await expect(createOrOpenIncidentTicket('incident-8')).rejects.toThrow('Incident already closed');
  });
});

describe('unified ticket list', () => {
  beforeEach(() => localStorage.setItem('netops_token', 'test-token'));
  afterEach(() => {
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('sends source type, status, search, and page arguments to the unified list', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      success: true,
      data: [{ source_type: 'service_request', source_id: 'request-2', ticket_key: 'SR-2', title: 'New account', status: 'submitted' }],
      total: 1,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await listUnifiedTickets({ page: 2, pageSize: 10, type: 'service_request', status: 'submitted', search: 'account', myTodo: true });
    const requestUrl = String(fetchMock.mock.calls[0][0]);

    expect(requestUrl).toContain('/api/tickets?');
    expect(requestUrl).toContain('type=service_request');
    expect(requestUrl).toContain('page=2');
    expect(requestUrl).toContain('page_size=10');
    expect(requestUrl).toContain('status=submitted');
    expect(requestUrl).toContain('search=account');
    expect(requestUrl).toContain('my_todo=true');
    expect(result.items[0].source_type).toBe('service_request');
    expect(result.total).toBe(1);
  });
});

describe('service request change order links', () => {
  beforeEach(() => localStorage.setItem('netops_token', 'test-token'));
  afterEach(() => {
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('links an existing change order by its number without creating or executing it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, data: { id: 'link-1' } }));
    vi.stubGlobal('fetch', fetchMock);

    await linkServiceRequestChangeOrder('request/12', 'CO-2026-001');

    expect(fetchMock).toHaveBeenCalledWith('/api/service-requests/request%2F12/change-orders', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ change_order_number: 'CO-2026-001' }),
    }));
  });
});

describe('ticket summary API', () => {
  beforeEach(() => localStorage.setItem('netops_token', 'test-token'));
  afterEach(() => {
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('requests a bounded UTC date range and returns the server summary unchanged', async () => {
    const summary = {
      from: '2026-10-01', to: '2026-10-30',
      totals: { all: 8, incident: 5, service_request: 3, active: 2, closed: 6 },
      by_priority: [{ priority: 'P1', count: 0 }, { priority: 'P2', count: 2 }],
      by_assignment_group: [{ id: null, name: '未分组', count: 1 }],
      durations_seconds: { first_response_avg: null, incident_restore_avg: 3600, service_fulfillment_avg: null, close_avg: 5400 },
      sample_counts: { first_response_avg: 0, incident_restore_avg: 2, service_fulfillment_avg: 0, close_avg: 2 },
      duration_basis: 'elapsed_utc_ticket_events',
    };
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, data: summary }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await getTicketSummary('2026-10-01', '2026-10-30');

    expect(fetchMock).toHaveBeenCalledWith('/api/tickets/summary?from=2026-10-01&to=2026-10-30', expect.any(Object));
    expect(result).toEqual(summary);
  });
});
