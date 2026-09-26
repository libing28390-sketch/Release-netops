import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiRequest } from '../api/http';
import NotificationChannelSettingsPage from './NotificationChannelSettingsPage';

vi.mock('../api/http', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/http')>();
  return { ...actual, apiRequest: vi.fn() };
});

const mockedApiRequest = vi.mocked(apiRequest);
const savedSmtpSettings = {
  id: 'email',
  display_name: '告警邮件',
  enabled: true,
  host: 'smtp.example.net',
  port: 587,
  security: 'starttls',
  username: 'alerts',
  from_address: 'alerts@example.net',
  from_name: 'Nexora Ops',
  reply_to: '',
  connect_timeout_seconds: 10,
  send_timeout_seconds: 20,
  rate_limit_per_minute: 60,
  has_password: true,
  configured: true,
  recipient_targets: [],
  inherited: false,
  legacy_primary: false,
};

describe('NotificationChannelSettingsPage', () => {
  beforeEach(() => {
    mockedApiRequest.mockImplementation(async (url) => {
      if (url === '/api/alerts/notification-channels/email/profiles') {
        return { items: [savedSmtpSettings] } as never;
      }
      if (url === '/api/alerts/notification-channels/email/recipients') {
        return { groups: [], users: [] } as never;
      }
      return {} as never;
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads the saved SMTP channel and sends a test through the selected channel', async () => {
    const user = userEvent.setup();
    const showToast = vi.fn();
    render(<NotificationChannelSettingsPage language="zh" showToast={showToast} />);

    expect(await screen.findByRole('heading', { name: '邮件通知' })).toBeTruthy();
    expect(mockedApiRequest).toHaveBeenCalledWith('/api/alerts/notification-channels/email/profiles');
    expect(mockedApiRequest).toHaveBeenCalledWith('/api/alerts/notification-channels/email/recipients');
    const testButton = screen.getByRole('button', { name: '测试' });
    expect(testButton.hasAttribute('disabled')).toBe(false);

    await user.click(testButton);
    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledWith('/api/alerts/notification-channels/email/profiles/email/test', expect.objectContaining({ method: 'POST' })));
  });

  it('shows a clear permission error and hides retry when the account is forbidden', async () => {
    mockedApiRequest.mockRejectedValueOnce(new ApiError(403, 'forbidden'));
    render(<NotificationChannelSettingsPage language="zh" showToast={vi.fn()} />);

    expect(await screen.findByText('你没有管理 SMTP 邮件通道的权限。')).toBeTruthy();
    expect(screen.getByText('当前账号没有管理 SMTP 配置的权限，请联系管理员。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '重试' })).toBeNull();
  });
});
