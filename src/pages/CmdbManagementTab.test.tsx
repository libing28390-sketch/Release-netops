import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CmdbManagementTab from './CmdbManagementTab';

const fetchSuccess = () => ({
  ok: true,
  status: 200,
  json: async () => ({ success: true, data: [] }),
}) as Response;

describe('CMDB import dialog interaction', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetchSuccess));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('exposes the credential import dialog and closes it with Escape', async () => {
    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    const uploadButton = await screen.findByRole('button', { name: 'Upload credentials' });
    expect(uploadButton).toBeTruthy();

    const file = new File(['not a valid workbook'], 'credentials.csv', { type: 'text/csv' });
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new ArrayBuffer(0) });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).toBeTruthy();
    fireEvent.change(fileInput as HTMLInputElement, { target: { files: [file] } });

    const dialog = await screen.findByRole('dialog', { name: 'Upload Credentials' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm import' }).hasAttribute('disabled')).toBe(true));

    screen.getByRole('button', { name: 'Cancel' }).focus();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Upload Credentials' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(uploadButton));
  });

  it('shows SNMP bindings as collection credentials without SSH binding actions', async () => {
    const credential = {
      id: 'cred-snmp',
      credential_name: 'snmp-ro',
      credential_type: 'snmpv2',
      username: '',
      account_role: 'snmp',
      account_role_label: 'SNMP 采集',
      device_count: 1,
      devices: [{ id: 'device-ac11', hostname: 'AC_11', ip_address: '192.0.2.11', binding_role: 'snmp' }],
      devices_truncated: false,
      enable_password_supported: false,
    };
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/credentials')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ success: true, data: [credential] }),
        } as Response);
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    expect(await screen.findByText('snmp-ro')).toBeTruthy();
    expect(screen.getByText('AC_11')).toBeTruthy();
    expect(screen.getByText('SNMP Collection')).toBeTruthy();
    expect(screen.getByText('SNMP')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'SNMP' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Normal' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Priv' })).toBeNull();
  });
});
