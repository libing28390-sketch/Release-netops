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
});
