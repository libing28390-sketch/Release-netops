import React, { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { TerminalExecution } from './TerminalExecution';

vi.mock('motion/react', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: (props: any) => {
      const divProps = Object.fromEntries(Object.entries(props).filter(([key]) => ![
        'children', 'initial', 'animate', 'exit', 'transition', 'whileHover',
      ].includes(key)));
      return <div {...divProps}>{props.children}</div>;
    },
  },
}));

const createExecutionState = (phase: 'confirm' | 'running' | 'done') => ({
  order: { id: 'order-1', order_number: 'CO-1', target_devices: [], commands: [] },
  phase,
  output: '',
  error: '',
  success: false,
});

const ExecutionHarness: React.FC<{ initialPhase: 'confirm' | 'running' | 'done' }> = ({ initialPhase }) => {
  const [executeModal, setExecuteModal] = useState(createExecutionState(initialPhase));
  return (
    <TerminalExecution
      language="en"
      executeModal={executeModal}
      setExecuteModal={setExecuteModal}
      runOrderCommands={vi.fn()}
      handleTransition={vi.fn()}
    />
  );
};

describe('TerminalExecution dialog close behavior', () => {
  afterEach(() => cleanup());

  it('keeps the execution dialog open while a privileged command run is active', () => {
    render(<ExecutionHarness initialPhase="running" />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.getByRole('dialog', { name: 'Push commands to target devices' })).toBeTruthy();
  });

  it('allows Escape to dismiss the pre-execution confirmation', () => {
    render(<ExecutionHarness initialPhase="confirm" />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog', { name: 'Push commands to target devices' })).toBeNull();
  });
});
