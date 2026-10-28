import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TextFSMDebugger } from './TextFSMDebugger';

const DebuggerHarness = () => {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open parser debugger</button>
      <TextFSMDebugger
        isOpen={open}
        onClose={() => setOpen(false)}
        platform="cisco_ios"
        command="show version"
        sampleOutput=""
        onSaveSuccess={() => undefined}
      />
    </>
  );
};

describe('TextFSMDebugger accessibility', () => {
  afterEach(() => cleanup());

  it('opens as a labelled dialog and returns focus after Escape', async () => {
    render(<DebuggerHarness />);
    const opener = screen.getByRole('button', { name: 'Open parser debugger' });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole('dialog', { name: '🧩 自定义命令 TextFSM 解析调试器' });
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(dialog, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
