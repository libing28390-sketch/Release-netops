import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ScriptManagementTab from './ScriptManagementTab';

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const makeScript = (index: number) => ({
  id: `script-${index}`,
  name: `Script ${index}`,
  content: 'show version',
  description: `Description ${index}`,
  platform: 'Linux',
  category: 'inspection',
  script_type: 'shell',
  author: 'operator',
  version: '1.0.0',
  status: 'released',
});

const renderPage = () => render(
  <MemoryRouter initialEntries={['/automation/scripts']}>
    <ScriptManagementTab language="zh" showToast={vi.fn()} />
  </MemoryRouter>,
);

describe('ScriptManagementTab pagination', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/scripts') {
        const page = Number(url.searchParams.get('page') || 1);
        const items = Array.from({ length: 10 }, (_, index) => makeScript((page - 1) * 10 + index + 1));
        return jsonResponse({ data: { items, total: 20 } });
      }
      if (url.pathname === '/api/scripts/approvers') return jsonResponse({ items: [] });
      if (url.pathname === '/api/session') return jsonResponse({ user: { username: 'operator' } });
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('replaces the previous page rows when the server page changes', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('Script 1')).toBeTruthy();
    expect(screen.getAllByRole('row')).toHaveLength(11);

    await user.click(screen.getByTitle('下一页'));
    expect(await screen.findByText('Script 11')).toBeTruthy();
    await waitFor(() => expect(screen.queryByText('Script 1')).toBeNull());
    expect(screen.getAllByRole('row')).toHaveLength(11);
  });

  it('shows a permission error and allows retrying the list request', async () => {
    let failFirstRequest = true;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/scripts') {
        if (failFirstRequest) {
          failFirstRequest = false;
          return jsonResponse({ detail: 'forbidden' }, 403);
        }
        return jsonResponse({ data: { items: [makeScript(1)], total: 1 } });
      }
      if (url.pathname === '/api/scripts/approvers') return jsonResponse({ items: [] });
      if (url.pathname === '/api/session') return jsonResponse({ user: { username: 'operator' } });
      return jsonResponse({});
    });
    const user = userEvent.setup();
    renderPage();

    const permissionAlert = await screen.findByRole('alert');
    expect(permissionAlert.textContent).toContain('你没有查看操作脚本的权限');
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('Script 1')).toBeTruthy();
  });
});
