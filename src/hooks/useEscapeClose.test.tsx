import React, { useState } from 'react';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useEscapeClose } from './useEscapeClose';

const TestDialog: React.FC<{ open: boolean; label: string; onClose: () => void }> = ({ open, label, onClose }) => {
  useEscapeClose(open, onClose);
  return open ? <div role="dialog" aria-label={label} /> : null;
};

describe('useEscapeClose', () => {
  afterEach(() => cleanup());

  it('closes stacked dialogs from top to bottom one at a time', () => {
    const closeCalls = { background: vi.fn(), foreground: vi.fn() };
    const StackedDialogs = () => {
      const [backgroundOpen, setBackgroundOpen] = useState(true);
      const [foregroundOpen, setForegroundOpen] = useState(true);
      return (
        <>
          <TestDialog open={backgroundOpen} label="Background dialog" onClose={() => { closeCalls.background(); setBackgroundOpen(false); }} />
          <TestDialog open={foregroundOpen} label="Foreground dialog" onClose={() => { closeCalls.foreground(); setForegroundOpen(false); }} />
        </>
      );
    };

    render(<StackedDialogs />);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closeCalls.foreground).toHaveBeenCalledTimes(1);
    expect(closeCalls.background).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closeCalls.background).toHaveBeenCalledTimes(1);
  });
});
