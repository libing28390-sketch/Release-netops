import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DeviceMfaModal from './DeviceMfaModal';

vi.mock('framer-motion', () => ({
  motion: {
    div: React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown;
      animate?: unknown;
      exit?: unknown;
    }>(({ children, initial: _initial, animate: _animate, exit: _exit, ...props }, ref) => (
      <div ref={ref} {...props}>{children}</div>
    )),
  },
}));

const target = {
  device: { hostname: 'router-1', ip_address: '192.0.2.1', management_port: 22 },
  appType: 'xshell' as const,
  identity: 'privileged' as const,
};

const MfaHarness = ({ onVerify }: { onVerify: () => void }) => {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open privileged session</button>
      {open && (
        <DeviceMfaModal
          isZh={false}
          currentUsername="operator"
          target={target}
          fixedPin="123456"
          dynamicCode=""
          showFixedPin={false}
          onFixedPinChange={vi.fn()}
          onDynamicCodeChange={vi.fn()}
          onToggleFixedPin={vi.fn()}
          onClose={() => setOpen(false)}
          onVerify={onVerify}
        />
      )}
    </>
  );
};

describe('DeviceMfaModal accessibility', () => {
  afterEach(() => cleanup());

  it('masks the fixed PIN and restores focus to its opener after Escape', async () => {
    const onVerify = vi.fn();
    render(<MfaHarness onVerify={onVerify} />);
    const opener = screen.getByRole('button', { name: 'Open privileged session' });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole('dialog', { name: 'Administrator verification' });
    const fixedPin = screen.getByLabelText('Fixed PIN (6 digits)') as HTMLInputElement;
    expect(fixedPin.type).toBe('password');
    expect(fixedPin.value).toBe('123456');
    expect(document.activeElement).toBe(fixedPin);

    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(opener));
    expect(onVerify).not.toHaveBeenCalled();
  });
});
