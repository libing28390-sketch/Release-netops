import React, { useRef, useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useFocusTrap } from './useFocusTrap';

const FocusDialog: React.FC<{ onClose: () => void; label: string }> = ({ onClose, label }) => {
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, true, 'input');

  return (
    <div ref={dialogRef} role="dialog" aria-label={label} tabIndex={-1}>
      <input aria-label={`${label} search`} />
      <button type="button">Last action</button>
      <button type="button" onClick={onClose}>Close</button>
    </div>
  );
};

const DialogHarness: React.FC = () => {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open dialog</button>
      {open && <FocusDialog label="Primary dialog" onClose={() => setOpen(false)} />}
    </>
  );
};

const StackedDialogHarness: React.FC = () => {
  const [childOpen, setChildOpen] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);
  useFocusTrap(parentRef, true, 'button');

  return (
    <div ref={parentRef} role="dialog" aria-label="Parent dialog" tabIndex={-1}>
      <button type="button">Parent first action</button>
      <button type="button" onClick={() => setChildOpen(true)}>Open child dialog</button>
      {childOpen && <FocusDialog label="Child dialog" onClose={() => setChildOpen(false)} />}
    </div>
  );
};

describe('useFocusTrap', () => {
  afterEach(() => cleanup());

  it('moves focus into the dialog, wraps Tab, and restores focus to the opener', async () => {
    render(<DialogHarness />);
    const opener = screen.getByRole('button', { name: 'Open dialog' });
    opener.focus();
    fireEvent.click(opener);

    const search = screen.getByRole('textbox', { name: 'Primary dialog search' });
    const close = screen.getByRole('button', { name: 'Close' });
    expect(document.activeElement).toBe(search);

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(search);

    fireEvent.click(close);
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it('traps only the topmost dialog and restores focus to its opener when it closes', async () => {
    render(<StackedDialogHarness />);
    const openChild = screen.getByRole('button', { name: 'Open child dialog' });
    openChild.focus();
    fireEvent.click(openChild);

    const childSearch = screen.getByRole('textbox', { name: 'Child dialog search' });
    const childClose = screen.getByRole('button', { name: 'Close' });
    expect(document.activeElement).toBe(childSearch);
    childClose.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(childSearch);

    fireEvent.click(childClose);
    await waitFor(() => expect(document.activeElement).toBe(openChild));
  });
});
