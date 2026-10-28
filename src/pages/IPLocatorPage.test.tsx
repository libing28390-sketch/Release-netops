import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IPLocatorPage from './IPLocatorPage';
import { locateIpWithRun } from '../utils/ipLocatorRuns';

vi.mock('../utils/ipLocatorRuns', () => ({ locateIpWithRun: vi.fn() }));

const renderLocator = (mode?: 'diagnose-only' | 'nsot-only' | 'toolbox') => render(
  <MemoryRouter initialEntries={['/ipam/locate']}>
    <IPLocatorPage language="en" t={(key) => key} mode={mode} />
  </MemoryRouter>,
);

describe('IPLocatorPage search controls', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    }));
    vi.mocked(locateIpWithRun).mockResolvedValue({
      target_ip: '198.51.100.25',
      found: false,
      mac: null,
      mac_display: null,
      arp_source: null,
      locations: [],
      searched_devices: { arp: [], mac: [], lldp: [] },
      timestamp: '2026-10-21T00:00:00Z',
      errors: [],
    });
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('labels the IP field and submits a lookup from the visible action', async () => {
    renderLocator();

    const ipInput = screen.getByRole('textbox', { name: 'IP address' });
    const locateButton = screen.getByRole('button', { name: 'Locate' });
    expect((locateButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(ipInput, { target: { value: '198.51.100.25' } });
    expect((locateButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(locateButton);

    await waitFor(() => expect(locateIpWithRun).toHaveBeenCalledWith(expect.objectContaining({
      ip: '198.51.100.25',
      token: 'test-token',
    })));
    expect(await screen.findByText('IP Address Not Found')).toBeTruthy();
  });

  it('ignores a second form submission while a lookup is still loading', async () => {
    let finishLookup: ((value: Awaited<ReturnType<typeof locateIpWithRun>>) => void) | undefined;
    vi.mocked(locateIpWithRun).mockImplementation(() => new Promise((resolve) => {
      finishLookup = resolve;
    }));

    renderLocator();
    const ipInput = screen.getByRole('textbox', { name: 'IP address' });
    fireEvent.change(ipInput, { target: { value: '198.51.100.25' } });
    const searchForm = ipInput.closest('form');
    expect(searchForm).not.toBeNull();

    fireEvent.submit(searchForm as HTMLFormElement);
    await waitFor(() => expect(locateIpWithRun).toHaveBeenCalledTimes(1));
    fireEvent.submit(searchForm as HTMLFormElement);
    expect(locateIpWithRun).toHaveBeenCalledTimes(1);

    finishLookup?.({
      target_ip: '198.51.100.25',
      found: false,
      mac: null,
      mac_display: null,
      arp_source: null,
      locations: [],
      searched_devices: { arp: [], mac: [], lldp: [] },
      timestamp: '2026-10-21T00:00:00Z',
      errors: [],
    });
    expect(await screen.findByText('IP Address Not Found')).toBeTruthy();
  });

  it('exposes the selected tool view to assistive technology', () => {
    renderLocator();

    expect(screen.getByRole('group', { name: 'IP locator views' })).toBeTruthy();
    const locateTab = screen.getByRole('button', { name: 'IP Locate' });
    const probeTab = screen.getByRole('button', { name: 'Connectivity Probe' });
    expect(locateTab.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(probeTab);
    expect(probeTab.getAttribute('aria-pressed')).toBe('true');
    expect(locateTab.getAttribute('aria-pressed')).toBe('false');
  });

  it('opens the NSOT policy modal and restores trigger focus after Escape and cancel', async () => {
    renderLocator('nsot-only');

    const trigger = await screen.findByRole('button', { name: 'Collection Templates' });
    fireEvent.click(trigger);

    const dialog = await screen.findByRole('dialog', { name: 'NSOT Device Collection Templates' });
    const ipInput = screen.getByRole('textbox', { name: 'Find one device by exact IP' });
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(ipInput);

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'NSOT Device Collection Templates' })).toBeNull();
      expect(document.activeElement).toBe(trigger);
    });

    fireEvent.click(trigger);
    await screen.findByRole('dialog', { name: 'NSOT Device Collection Templates' });
    fireEvent.click(screen.getByRole('button', { name: 'Close collection templates' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'NSOT Device Collection Templates' })).toBeNull();
      expect(document.activeElement).toBe(trigger);
    });
  });
});
