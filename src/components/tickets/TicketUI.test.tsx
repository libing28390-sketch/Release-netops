import React, { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TicketDialog } from './TicketUI';
import { TicketReviewerDialog } from './TicketReviewerDialog';

afterEach(cleanup);

describe('shared ticket dialogs', () => {
  it('focuses the form and returns focus to its trigger after Escape', async () => {
    const Harness = () => {
      const [open, setOpen] = useState(false);
      return <><button onClick={() => setOpen(true)}>Open form</button>{open && <TicketDialog title="Ticket form" language="en" onClose={() => setOpen(false)} initialFocusSelector="input"><input aria-label="Title" /></TicketDialog>}</>;
    };
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Open form' });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole('dialog', { name: 'Ticket form' })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Title' }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it('closes only the top dialog when two ticket dialogs are stacked', () => {
    const Harness = () => {
      const [top, setTop] = useState(true);
      const [base, setBase] = useState(true);
      return <>{base && <TicketDialog title="Base" onClose={() => setBase(false)}>Base content</TicketDialog>}{top && <TicketDialog title="Top" onClose={() => setTop(false)}>Top content</TicketDialog>}</>;
    };
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Top' })).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Base' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('requires a selected reviewer before confirming', () => {
    const confirm = vi.fn();
    const Harness = () => {
      const [selected, setSelected] = useState('');
      return <TicketReviewerDialog title="Select reviewer" language="en" search="" onSearchChange={() => {}} groups={{ Operations: [{ id: 'reviewer', username: 'alice', display_name: 'Alice', role: 'Administrator' }] }} selectedId={selected} onSelect={setSelected} onConfirm={confirm} onClose={() => {}} emptyMessage="No reviewers" />;
    };
    render(<Harness />);
    expect((screen.getByRole('button', { name: 'Confirm' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('radio', { name: 'Alice (alice)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(confirm).toHaveBeenCalledOnce();
  });
});
