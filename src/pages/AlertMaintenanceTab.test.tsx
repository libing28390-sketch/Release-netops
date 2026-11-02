import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AlertMaintenanceTab from './AlertMaintenanceTab';

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

describe('AlertMaintenanceTab access errors', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.removeItem('netops_token');
  });

  it('shows a persistent permission state when the maintenance list is forbidden', async () => {
    const showToast = vi.fn();
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/alerts/maintenance-windows?')) {
        return Promise.resolve(response({ detail: 'Insufficient permissions' }, 403));
      }
      if (url === '/api/users') return Promise.resolve(response([]));
      return Promise.resolve(response({ items: [] }));
    }));

    render(
      <MemoryRouter>
        <AlertMaintenanceTab
          language="zh"
          currentUsername="operator"
          showToast={showToast}
          activeAlertSection="maintenance"
          onNavigateAlertSection={vi.fn()}
        />
      </MemoryRouter>,
    );

    const permissionState = await screen.findByRole('alert');
    expect(permissionState.textContent).toContain('你没有权限查看维护期。');
    await waitFor(() => expect(showToast).toHaveBeenCalledWith('你没有权限查看维护期。', 'error'));
  });
});
