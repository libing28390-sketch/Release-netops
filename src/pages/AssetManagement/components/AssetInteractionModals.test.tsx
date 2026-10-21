import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BatchTagModal } from './BatchTagModal';
import { DeleteConfirmModal } from './DeleteConfirmModal';
import { AssetImportValidationModal } from './AssetImportValidationModal';
import { TerminalAccessModal } from './TerminalAccessModal';
import { WebAccessRequestModal } from './WebAccessRequestModal';

const DialogHarness: React.FC<{ children: (isOpen: boolean, onClose: () => void) => React.ReactNode }> = ({ children }) => {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>Open dialog</button>
      {children(isOpen, () => setIsOpen(false))}
    </>
  );
};

const openDialog = () => {
  const opener = screen.getByRole('button', { name: 'Open dialog' });
  opener.focus();
  fireEvent.click(opener);
  return opener;
};

const expectEscapeReturn = async (opener: HTMLElement, name: string, role: 'dialog' | 'alertdialog' = 'dialog') => {
  fireEvent.keyDown(document, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole(role, { name })).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(opener));
};

describe('asset page modal interactions', () => {
  afterEach(() => cleanup());

  it('keeps bulk-tag search inside a named modal and returns focus after Escape', async () => {
    render(
      <DialogHarness>
        {(isOpen, onClose) => (
          <BatchTagModal
            isOpen={isOpen}
            onClose={onClose}
            selectedCount={1}
            allTags={[{ id: 'tag-prod', category: 'environment', label: 'Production', label_zh: '生产', code: 'prod', color: '#2563eb' } as any]}
            selectedTagIds={[]}
            setSelectedTagIds={vi.fn()}
            batchTag={vi.fn()}
            language="en"
          />
        )}
      </DialogHarness>,
    );

    const opener = openDialog();
    const dialog = await screen.findByRole('dialog', { name: 'Edit tags in bulk' });
    const search = within(dialog).getByRole('searchbox', { name: 'Search tags' });
    await waitFor(() => expect(document.activeElement).toBe(search));
    await expectEscapeReturn(opener, 'Edit tags in bulk');
  });

  it('uses an alert dialog for asset deletion and focuses the safe cancel action', async () => {
    render(
      <DialogHarness>
        {(isOpen, onClose) => (
          <DeleteConfirmModal
            isOpen={isOpen}
            onClose={onClose}
            deleteTarget={{ id: 'asset-1', hostname: 'edge-01' } as any}
            handleDelete={vi.fn()}
            language="en"
          />
        )}
      </DialogHarness>,
    );

    const opener = openDialog();
    const dialog = await screen.findByRole('alertdialog', { name: 'Confirm Delete' });
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    await waitFor(() => expect(document.activeElement).toBe(cancel));
    await expectEscapeReturn(opener, 'Confirm Delete', 'alertdialog');
  });

  it('traps focus in import rack resolution and returns it after dismissal', async () => {
    render(
      <DialogHarness>
        {(isOpen, onClose) => (
          <AssetImportValidationModal
            isOpen={isOpen}
            onClose={onClose}
            language="en"
            missingRacks={[{ datacenter: 'dc-1', rack: 'rack-1', rowCount: 2 }]}
            existingRacks={[]}
            onConfirm={vi.fn()}
            saving={false}
          />
        )}
      </DialogHarness>,
    );

    const opener = openDialog();
    const dialog = await screen.findByRole('dialog', { name: 'Import Verification: Missing Racks Found' });
    const action = within(dialog).getByRole('combobox', { name: 'Resolution for rack-1' });
    await waitFor(() => expect(document.activeElement).toBe(action));
    await expectEscapeReturn(opener, 'Import Verification: Missing Racks Found');
  });

  it('labels terminal access controls and reports the selected access level', async () => {
    render(
      <DialogHarness>
        {(isOpen, onClose) => (
          <TerminalAccessModal
            isOpen={isOpen}
            onClose={onClose}
            terminalTarget={{ hostname: 'edge-01', management_ip: '192.0.2.1' } as any}
            terminalAccessLevel="normal"
            setTerminalAccessLevel={vi.fn()}
            approvalData={{ ticket: '', reason: '', mfa: '' }}
            setApprovalData={vi.fn()}
            terminalReason=""
            setTerminalReason={vi.fn()}
            terminalRequesting={false}
            systemInfo={{ system_name: 'Nexora' }}
            requestTerminalAccess={vi.fn()}
            setIsApproved={vi.fn()}
            language="en"
          />
        )}
      </DialogHarness>,
    );

    const opener = openDialog();
    const dialog = await screen.findByRole('dialog', { name: 'Access Request' });
    expect(within(dialog).getByRole('group', { name: 'AUTHORIZATION' })).toBeTruthy();
    expect(within(dialog).getByRole('button', { name: 'User' }).getAttribute('aria-pressed')).toBe('true');
    expect(within(dialog).getByRole('button', { name: 'Admin' }).getAttribute('aria-pressed')).toBe('false');
    await expectEscapeReturn(opener, 'Access Request');
  });

  it('labels Web access controls and prevents Escape dismissal while the request is pending', async () => {
    const onClose = vi.fn();
    render(
      <WebAccessRequestModal
        isOpen
        asset={{ hostname: 'edge-01' }}
        profiles={[{ id: 'web-1', profile_name: 'Management', scheme: 'https', port: '443', path: '/' } as any]}
        accessLevel="normal"
        profileId="web-1"
        reason=""
        requesting
        language="en"
        onAccessLevelChange={vi.fn()}
        onProfileChange={vi.fn()}
        onReasonChange={vi.fn()}
        onClose={onClose}
        onSubmit={vi.fn()}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: 'Web Management Access' });
    expect(within(dialog).getByRole('combobox', { name: 'Web entry' })).toBeTruthy();
    expect(within(dialog).getByRole('textbox', { name: 'Reason (optional)' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: 'Web Management Access' })).toBe(dialog);
  });
});
