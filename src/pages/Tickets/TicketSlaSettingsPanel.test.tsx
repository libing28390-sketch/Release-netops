import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import TicketSlaSettingsPanel from './TicketSlaSettingsPanel';

const response = (body: unknown) => ({ ok: true, status: 200, json: vi.fn().mockResolvedValue(body) }) as unknown as Response;

describe('TicketSlaSettingsPanel', () => {
  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('requires a versioned work calendar and leaves service targets unconfigured by default', async () => {
    localStorage.setItem('netops_token', 'test-token');
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ticket-work-calendars' && init?.method === 'POST') return Promise.resolve(response({ success: true, data: { id: 'calendar-1', version_id: 'calendar-version-1' } }));
      if (url === '/api/ticket-sla-policies' && init?.method === 'POST') return Promise.resolve(response({ success: true, data: { id: 'policy-1', version_id: 'policy-version-1' } }));
      if (url === '/api/ticket-work-calendars') return Promise.resolve(response({ success: true, data: [{ id: 'calendar-1', version_id: 'calendar-version-1', name: 'Business hours', version: 2, timezone: 'Asia/Shanghai', schedule: { monday: [{ start: '09:00', end: '18:00' }] }, holidays: [] }] }));
      if (url === '/api/ticket-sla-policies') return Promise.resolve(response({ success: true, data: [] }));
      return Promise.resolve(response({ success: true, data: [] }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<TicketSlaSettingsPanel open onClose={vi.fn()} language="en" />);

    const targetName = await screen.findByLabelText('Target name');
    const nearDue = screen.getByLabelText('Near-due reminder (minutes before)') as HTMLInputElement;
    expect((screen.getByLabelText('First response (minutes)') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Restoration target (minutes)') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Fulfillment target (minutes)') as HTMLInputElement).value).toBe('');
    expect(nearDue.value).toBe('');
    fireEvent.change(targetName, { target: { value: 'P2 service request' } });
    fireEvent.change(screen.getByLabelText('Work calendar'), { target: { value: 'calendar-version-1' } });
    fireEvent.change(screen.getByLabelText('First response (minutes)'), { target: { value: '30' } });
    fireEvent.change(nearDue, { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create target' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([input, init]) => String(input) === '/api/ticket-sla-policies' && init?.method === 'POST');
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        name: 'P2 service request',
        source_type: 'service_request',
        priority: 'P3',
        response_target_minutes: 30,
        warning_before_minutes: 10,
        calendar_version_id: 'calendar-version-1',
      });
    });
  });

  it('closes with Escape when settings are idle', async () => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(response({ success: true, data: [] }))));
    const onClose = vi.fn();
    render(<TicketSlaSettingsPanel open onClose={onClose} language="en" />);

    expect(await screen.findByRole('dialog', { name: 'Ticket targets' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
