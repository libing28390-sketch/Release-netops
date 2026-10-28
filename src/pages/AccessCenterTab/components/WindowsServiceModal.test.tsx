import React, { useState } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WindowsServiceModal from './WindowsServiceModal';
import { getWindowsServices } from '../../../api/windowsManagement';

vi.mock('../../../api/windowsManagement', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../../api/windowsManagement')>(),
  getWindowsServices: vi.fn(),
}));

const getServices = vi.mocked(getWindowsServices);

const WindowsServiceHarness = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>Open Windows services</button>
      <WindowsServiceModal
        isOpen={isOpen}
        assetId="asset-1"
        hostname="edge-01"
        language="en"
        showToast={vi.fn()}
        onClose={() => setIsOpen(false)}
      />
    </>
  );
};

describe('WindowsServiceModal keyboard interaction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getServices.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 });
  });

  afterEach(() => cleanup());

  it('focuses search, contains keyboard focus, and restores it to the opener after Escape', async () => {
    const user = userEvent.setup();
    render(<WindowsServiceHarness />);

    const opener = screen.getByRole('button', { name: 'Open Windows services' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Windows service management' });
    const search = screen.getByRole('searchbox', { name: 'Search service name or display name' });
    expect(document.activeElement).toBe(search);

    await user.tab({ shift: true });
    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Windows service management' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
