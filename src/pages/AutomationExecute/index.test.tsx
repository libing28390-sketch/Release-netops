import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../../types';
import type { AutomationExecuteTabProps } from './types';
import { AutomationExecuteTab } from './index';

vi.mock('motion/react', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown;
      animate?: unknown;
      exit?: unknown;
      transition?: unknown;
    }>(
      ({ children, initial: _initial, animate: _animate, exit: _exit, transition: _transition, ...props }, ref) => <div ref={ref} {...props}>{children}</div>,
    ),
  },
}));
vi.mock('../../components/PageHero', () => ({ default: () => <header /> }));
vi.mock('./components/DeviceSelectionStep', () => ({
  DeviceSelectionStep: ({ showSelectedDrawer, setShowSelectedDrawer }: { showSelectedDrawer: boolean; setShowSelectedDrawer: (value: boolean) => void }) => (
    <div>
      <button type="button" onClick={() => setShowSelectedDrawer(true)}>Open selected devices</button>
      {showSelectedDrawer && <p>Selected-device drawer open</p>}
    </div>
  ),
}));
vi.mock('./components/ScenarioSelectionStep', () => ({ ScenarioSelectionStep: () => null }));
vi.mock('./components/ParameterConfigStep', () => ({
  ParameterConfigStep: ({ setConfirmAction, setConfirmModalOpen }: { setConfirmAction: (action: 'validate' | 'apply') => void; setConfirmModalOpen: (open: boolean) => void }) => (
    <button type="button" onClick={() => { setConfirmAction('apply'); setConfirmModalOpen(true); }}>Request confirmation</button>
  ),
}));
vi.mock('./components/ExecutionResultsStep', () => ({ ExecutionResultsStep: () => null }));
vi.mock('./components/QuickQueryOverlay', () => ({ QuickQueryOverlay: () => null }));
vi.mock('./components/QuickQueryResultOverlay', () => ({ QuickQueryResultOverlay: () => null }));
vi.mock('./components/TextFSMDebugger', () => ({ TextFSMDebugger: () => null }));

const device = { id: 'device-1', hostname: 'router-1', ip_address: '192.0.2.1', status: 'online' } as Device;
const noop = vi.fn();

const makeProps = (handleClearSelection = vi.fn(), overrides: Partial<AutomationExecuteTabProps> = {}): AutomationExecuteTabProps => ({
  t: (key) => key,
  language: 'en',
  sectionHeaderRowClass: '',
  devices: [device],
  rememberedBatchDevices: [device],
  selectedDevice: null,
  batchMode: true,
  batchDeviceIds: [device.id],
  automationSearch: '',
  scenarioSearch: '',
  savedQueries: [],
  filteredScenarios: [],
  quickPlaybookScenario: null,
  quickPlaybookVars: {},
  quickPlaybookPlatform: 'cisco_ios',
  quickPlaybookDryRun: false,
  quickPlaybookConcurrency: 1,
  quickPlaybookPreview: null,
  quickRiskConfirmed: false,
  hasQuickTargets: false,
  quickMissingRequiredFields: [],
  quickHasMixedPlatforms: false,
  quickPlatformMismatch: false,
  isQuickPlaybookRunning: false,
  quickExecutionResult: null,
  executionStatus: '',
  wsCompleteMsg: null,
  deviceStatusMap: {},
  quickQueryRunning: false,
  quickQueryOutput: '',
  quickQueryLabel: '',
  quickQueryStructured: null,
  quickQueryView: 'terminal',
  quickQueryMaximized: false,
  quickQueryCommands: [],
  quickQueryTable: { category: {}, records: [], columns: [] },
  onNavigate: noop,
  onAutomationSearchChange: noop,
  onScenarioSearchChange: noop,
  onToggleBatchMode: noop,
  onToggleBatchDevice: noop,
  onRememberDevice: noop,
  onSelectDevice: noop,
  handleClearSelection,
  onOpenCustomCommandModal: noop,
  onOpenScenario: noop,
  onClearScenario: noop,
  onQuickPlaybookVarChange: noop,
  onQuickPlaybookConcurrencyChange: noop,
  onQuickRiskConfirmedChange: noop,
  onRunValidation: noop,
  onRunApply: noop,
  onRunQuickQuery: noop,
  onResetQuickQuery: noop,
  onQuickQueryViewChange: noop,
  onQuickQueryMaximizedChange: noop,
  onOpenCommandPreview: noop,
  onExportQuickQueryTable: noop,
  copyTextWithFallback: vi.fn().mockResolvedValue(true),
  showToast: vi.fn(),
  onResetExecutionState: noop,
  getPlatformLabel: (platform) => platform,
  ...overrides,
});

describe('AutomationExecuteTab Escape behavior', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0, page: 1, page_size: 20 }) }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('closes the selected-device drawer before clearing selected devices', () => {
    const clearSelection = vi.fn();
    render(<AutomationExecuteTab {...makeProps(clearSelection)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open selected devices' }));
    expect(screen.getByText('Selected-device drawer open')).toBeTruthy();

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.queryByText('Selected-device drawer open')).toBeNull();
    expect(clearSelection).not.toHaveBeenCalled();
  });

  it('opens the apply confirmation as a labelled modal and restores trigger focus on Escape', async () => {
    const onRunApply = vi.fn();
    render(<AutomationExecuteTab {...makeProps(vi.fn(), {
      quickPlaybookScenario: {
        id: 'scenario-1',
        risk: 'medium',
        name: 'Update interface description',
        name_zh: '更新接口描述',
        description: 'Update an interface description',
        variables: [],
      },
      onRunApply,
    })} />);

    const trigger = screen.getByRole('button', { name: 'Request confirmation' });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Confirm Apply' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(onRunApply).not.toHaveBeenCalled();
  });
});
