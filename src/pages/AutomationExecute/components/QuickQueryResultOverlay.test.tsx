import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../../../types';
import { formatParserLabel, QuickQueryResultOverlay } from './QuickQueryResultOverlay';

vi.mock('../../../components/OutputActions', () => ({ default: () => null }));
vi.mock('../../../components/ui/TableExportMenu', () => ({ TableExportMenu: () => null }));

const device = { id: 'device-1', hostname: 'router-1', ip_address: '192.0.2.1', status: 'online' as const } as Device;

const QuickQueryHarness = () => {
  const [output, setOutput] = React.useState('');
  return (
    <>
      <button type="button" onClick={() => setOutput('show version output')}>Open quick query</button>
      <QuickQueryResultOverlay
        isZh={false}
        quickQueryRunning={false}
        quickQueryOutput={output}
        quickQueryMaximized={false}
        quickQueryLabel="Show version"
        targetDevices={[device]}
        onQuickQueryMaximizedChange={vi.fn()}
        onResetQuickQuery={() => setOutput('')}
        quickQueryCommands={[]}
        copyTextWithFallback={vi.fn().mockResolvedValue(true)}
        showToast={vi.fn()}
        quickQueryStructured={null}
        quickQueryView="terminal"
        quickQueryTable={{ category: {}, records: [], columns: [] }}
        quickQuerySearch=""
        setQuickQuerySearch={vi.fn()}
        filteredQuickQueryRecords={[]}
        onQuickQueryViewChange={vi.fn()}
      />
    </>
  );
};

afterEach(() => cleanup());

describe('formatParserLabel', () => {
  it('shows the concrete versioned TextFSM template when the backend reports it', () => {
    expect(formatParserLabel(
      'textfsm:h3c_comware_v7_display_interface_brief.textfsm',
      true,
    )).toBe('TextFSM 自动匹配 · h3c_comware_v7_display_interface_brief.textfsm');
  });

  it('does not present the legacy NTC catalog wording', () => {
    expect(formatParserLabel('ntc-templates', true)).toBe('TextFSM 解析（模板未回传）');
  });

  it('moves focus into the result dialog and restores it after Escape', async () => {
    render(<QuickQueryHarness />);
    const opener = screen.getByRole('button', { name: 'Open quick query' });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole('dialog', { name: /Quick query result: Show version, router-1/ });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(dialog, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
