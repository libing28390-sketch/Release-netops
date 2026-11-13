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
  requestSent: false,
});

const ExecutionHarness: React.FC<{ initialPhase: 'confirm' | 'running' | 'done' }> = ({ initialPhase }) => {
  const [executeModal, setExecuteModal] = useState(createExecutionState(initialPhase));
  return (
    <TerminalExecution
      language="en"
      executeModal={executeModal}
      setExecuteModal={setExecuteModal}
      runOrderCommands={vi.fn()}
    />
  );
};

const renderCompletedExecution = (overrides: Partial<ReturnType<typeof createExecutionState>> = {}) => render(
  <TerminalExecution
    language="en"
    executeModal={{
      ...createExecutionState('done'),
      error: 'Request failed',
      ...overrides,
    }}
    setExecuteModal={vi.fn()}
    runOrderCommands={vi.fn()}
  />,
);

describe('TerminalExecution dialog close behavior', () => {
  afterEach(() => cleanup());

  it('keeps the execution dialog open while a command run is active', () => {
    render(<ExecutionHarness initialPhase="running" />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.getByRole('dialog', { name: 'Push commands to target devices' })).toBeTruthy();
  });

  it('allows Escape to dismiss the pre-execution confirmation', () => {
    render(<ExecutionHarness initialPhase="confirm" />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog', { name: 'Push commands to target devices' })).toBeNull();
  });

  it('warns after an execution request is sent and never offers a blind retry', () => {
    renderCompletedExecution({ requestSent: true });

    expect(screen.getByRole('note').textContent).toContain('The authorization has been used');
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
  });

  it('does not claim authorization was consumed for a preflight failure', () => {
    renderCompletedExecution({ requestSent: false });

    expect(screen.queryByRole('note')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
  });

  it('requires verification records before completion after a successful command response', () => {
    renderCompletedExecution({ success: true, requestSent: true, error: '', output: 'Interface is up' });

    expect(screen.getByRole('status').textContent).toContain('record technical and business results');
    expect(screen.queryByRole('button', { name: 'Mark Completed & Save Output' })).toBeNull();
  });
});
