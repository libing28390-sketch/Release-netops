import React, { useState } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { CopilotInspectorDrawer } from './CopilotInspectorDrawer';

const InspectorHarness = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>打开 Inspector</button>
      <CopilotInspectorDrawer
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        activeMessage={{ intent: 'GENERAL_QA' }}
      />
    </>
  );
};

describe('CopilotInspectorDrawer keyboard interaction', () => {
  afterEach(() => cleanup());

  it('contains focus and returns it to the opener after Escape', async () => {
    const user = userEvent.setup();
    render(<InspectorHarness />);

    const opener = screen.getByRole('button', { name: '打开 Inspector' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: '开发者调试 Trace (Inspector)' });
    const closeButton = screen.getByRole('button', { name: '关闭调试 Trace' });
    expect(document.activeElement).toBe(closeButton);

    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
