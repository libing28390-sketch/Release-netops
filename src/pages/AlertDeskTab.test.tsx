import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AlertDeskTab from './AlertDeskTab';

vi.mock('motion/react', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
  },
}));
vi.mock('../components/DataTable', () => ({
  DataTable: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
}));
vi.mock('../components/PageHero', () => ({
  default: ({ title, actions }: { title: string; actions?: React.ReactNode }) => <header><h1>{title}</h1>{actions}</header>,
}));
vi.mock('../components/Pagination', () => ({ default: () => null }));
vi.mock('./useAlertSiteLabels', () => ({ useAlertSiteLabels: () => new Map() }));

const response = (title: string) => ({
  ok: true,
  json: async () => ({
    items: [{
      id: `alert-${title}`,
      dedupe_key: `dedupe-${title}`,
      source: 'network_monitor',
      severity: 'warning',
      title,
      message: `Message for ${title}`,
      created_at: '2026-10-12T00:00:00Z',
      workflow_status: 'open',
      duration_seconds: 30,
    }],
    total: 1,
    page: 1,
    page_size: 10,
    status_counts: { open: 1 },
  }),
}) as unknown as Response;

const renderAlertDesk = (showToast = vi.fn()) => render(
  <AlertDeskTab
    language="en"
    currentUsername="operator"
    showToast={showToast}
    activeAlertSection="alerts"
    onNavigateAlertSection={vi.fn()}
  />,
);

describe('AlertDeskTab search request control', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('debounces rapid typing and ignores a stale response after a newer search completes', async () => {
    let resolveRouterSearch: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation((input) => {
      const search = new URL(String(input), window.location.origin).searchParams.get('search') || '';
      if (search === '') return Promise.resolve(response('initial-alert'));
      if (search === 'router') {
        return new Promise<Response>((resolve) => { resolveRouterSearch = resolve; });
      }
      if (search === 'switch') return Promise.resolve(response('switch-result'));
      return Promise.resolve(response(`unexpected-${search}`));
    });

    renderAlertDesk();
    await screen.findByText('initial-alert');
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    const searchInput = screen.getByRole('searchbox', { name: 'Search alert title, device, interface, or IP' });
    fireEvent.change(searchInput, { target: { value: 'r' } });
    fireEvent.change(searchInput, { target: { value: 'rou' } });
    fireEvent.change(searchInput, { target: { value: 'router' } });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2), { timeout: 1000 });
    expect(new URL(String(vi.mocked(fetch).mock.calls[1][0]), window.location.origin).searchParams.get('search')).toBe('router');
    expect(resolveRouterSearch).toBeTypeOf('function');

    fireEvent.change(searchInput, { target: { value: 'switch' } });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3), { timeout: 1000 });
    await screen.findByText('switch-result');

    await act(async () => {
      resolveRouterSearch?.(response('stale-router-result'));
    });
    expect(screen.getByText('switch-result')).toBeTruthy();
    expect(screen.queryByText('stale-router-result')).toBeNull();
  });

  it('shows a retryable list error instead of the empty state when the request fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(fetch)
      .mockResolvedValueOnce({ ok: false, status: 503 } as Response)
      .mockResolvedValueOnce(response('recovered-alert'));

    renderAlertDesk();

    expect((await screen.findByRole('alert')).textContent).toContain('Could not load alerts.');
    expect(screen.queryByText('No alerts found for the current filter.')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('recovered-alert')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('identifies an authorization failure as a permission state', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 403 } as Response);

    renderAlertDesk();

    expect((await screen.findByRole('alert')).textContent).toContain('You are not authorized to view alerts');
  });

  it('shows a permission error and retry action when alert details cannot be loaded', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/activity')) {
        return Promise.resolve({ ok: true, json: async () => ({ items: [] }) } as Response);
      }
      if (url.includes('/api/alerts?')) return Promise.resolve(response('detail-alert'));
      return Promise.resolve({ ok: false, status: 403 } as Response);
    });

    renderAlertDesk();
    await screen.findByText('detail-alert');
    fireEvent.click(screen.getByRole('button', { name: 'View alert detail-alert' }));

    const detailError = await screen.findByRole('alert');
    expect(detailError.textContent).toContain('You are not authorized to view this alert');
    expect(screen.queryByRole('status')).toBeNull();
    const detailRequestsBeforeRetry = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).includes('/api/alerts/alert-detail-alert')).length;
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).includes('/api/alerts/alert-detail-alert')).length).toBeGreaterThan(detailRequestsBeforeRetry));
  });

  it('gives alert selection controls accessible names and pressed state', async () => {
    vi.mocked(fetch).mockResolvedValue(response('router-down'));
    renderAlertDesk();

    await screen.findByText('router-down');
    const selectAlert = screen.getByRole('button', { name: 'Select alert router-down' });
    expect(selectAlert.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(selectAlert);
    expect(selectAlert.getAttribute('aria-pressed')).toBe('true');

    const selectAll = screen.getByRole('button', { name: 'Select all alerts on this page' });
    expect(selectAll.getAttribute('aria-pressed')).toBe('true');
  });

  it('contains focus in alert details and returns focus after Escape', async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/activity')) return Promise.resolve({ ok: true, json: async () => ({ items: [] }) } as Response);
      if (url.includes('/api/alerts?')) return Promise.resolve(response('router-down'));
      if (url.endsWith('/api/alerts/alert-router-down')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            item: {
              id: 'alert-router-down',
              dedupe_key: 'dedupe-router-down',
              source: 'network_monitor',
              severity: 'warning',
              title: 'router-down',
              message: 'Message for router-down',
              created_at: '2026-10-12T00:00:00Z',
              workflow_status: 'open',
              duration_seconds: 30,
              note: '',
              assignee: null,
            },
            timeline: [],
          }),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404 } as Response);
    });
    renderAlertDesk();

    await screen.findByText('router-down');
    const user = userEvent.setup();
    const openDetails = screen.getByRole('button', { name: 'View alert router-down' });
    await user.click(openDetails);

    const dialog = await screen.findByRole('dialog', { name: 'Alert details' });
    expect(document.activeElement).toBe(dialog);
    await user.keyboard('{Escape}');

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Alert details' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(openDetails));
  });
});
