import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from '../../api/http';
import TemplateBindingModal from './TemplateBindingModal';

vi.mock('../../api/http', () => ({
  apiRequest: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequest);
const template = {
  profile_id: 'profile-custom',
  vendor: 'H3C',
  model: 'S6800',
  category: 'Network Device',
  description: 'Custom template',
  metric_definitions: { cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.1' } },
  interface_config: {},
  source: 'custom',
};

describe('TemplateBindingModal', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('binds selected devices without requesting SNMP credentials', async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockImplementation(async (url) => {
      if (String(url).includes('/bindings')) {
        return { success: true, data: { devices: [{ device_id: 'device-1' }] } } as never;
      }
      return {
        items: [
          { id: 'device-1', hostname: 'sw-01', ip_address: '192.0.2.1', model: 'S6800', vendor: 'H3C', status: 'online' },
          { id: 'device-2', hostname: 'sw-02', ip_address: '192.0.2.2', model: 'S6800', vendor: 'H3C', status: 'offline' },
        ],
      } as never;
    });
    const onConfirm = vi.fn().mockResolvedValue(undefined);

    render(
      <TemplateBindingModal
        open
        template={template}
        language="en"
        showToast={vi.fn()}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(2));
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    await user.click(screen.getByRole('button', { name: 'Confirm binding' }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith(template, ['device-1', 'device-2'], []));
    expect(mockedApiRequest.mock.calls.some(([, options]) => String(options?.body || '').includes('community'))).toBe(false);
  });

  it('allows clearing the last binding and reports it as an unbind', async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockImplementation(async (url) => {
      if (String(url).includes('/bindings')) {
        return { success: true, data: { devices: [{ device_id: 'device-1' }] } } as never;
      }
      return {
        items: [{ id: 'device-1', hostname: 'sw-01', ip_address: '192.0.2.1', model: 'S6800', vendor: 'H3C', status: 'online' }],
      } as never;
    });
    const onConfirm = vi.fn().mockResolvedValue(undefined);

    render(
      <TemplateBindingModal
        open
        template={template}
        language="en"
        showToast={vi.fn()}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: 'Clear visible' }));
    await user.click(screen.getByRole('button', { name: 'Unbind all 1' }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith(template, [], ['device-1']));
  });

  it('does not preselect same-model devices for a new template', async () => {
    const newTemplate = { ...template, profile_id: undefined };
    mockedApiRequest.mockResolvedValue({
      items: [
        { id: 'device-1', hostname: 'sw-01', ip_address: '192.0.2.1', model: 'S6800', vendor: 'H3C', status: 'online' },
        { id: 'device-2', hostname: 'sw-02', ip_address: '192.0.2.2', model: 'S6800', vendor: 'H3C', status: 'offline' },
      ],
    } as never);

    render(
      <TemplateBindingModal
        open
        template={newTemplate}
        language="en"
        showToast={vi.fn()}
        onClose={vi.fn()}
        onConfirm={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(2));
    expect(screen.getAllByRole('checkbox').every(input => !(input as HTMLInputElement).checked)).toBe(true);
  });
});
