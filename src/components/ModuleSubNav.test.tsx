import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import ModuleSubNav from './ModuleSubNav';

vi.mock('../hooks/useSystem', () => ({ useSystem: () => ({ systemInfo: { version: 'test' } }) }));

function CurrentRoute() {
  const location = useLocation();
  return <output data-testid="route">{location.pathname}{location.search}</output>;
}

afterEach(cleanup);

function setup() {
  render(<MemoryRouter initialEntries={['/ipam/prefixes?prefix_id=prefix-example']}>
    <ModuleSubNav language="zh" userRole="Administrator" />
    <CurrentRoute />
  </MemoryRouter>);
  return within(screen.getByRole('navigation'));
}

describe('IPAM module navigation', () => {
  it('keeps both groups usable and independently collapsible', () => {
    const nav = setup();
    const workspace = nav.getByRole('button', { name: 'IPAM 工作台' });
    const addressSpace = nav.getByRole('button', { name: '地址空间' });
    expect(workspace.compareDocumentPosition(addressSpace) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(addressSpace.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(workspace);
    expect(workspace.getAttribute('aria-expanded')).toBe('true');
    expect(addressSpace.getAttribute('aria-expanded')).toBe('true');
    expect(nav.getByRole('button', { name: 'IP 地址' })).toBeTruthy();
    expect(nav.getByRole('button', { name: '网段' })).toBeTruthy();
    fireEvent.click(addressSpace);
    expect(nav.queryByRole('button', { name: '网段' })).toBeNull();
    expect(nav.getByRole('button', { name: 'IP 地址' })).toBeTruthy();
    fireEvent.click(workspace);
    expect(nav.queryByRole('button', { name: 'IP 地址' })).toBeNull();
    fireEvent.click(addressSpace);
    expect(nav.getByRole('button', { name: '网段' })).toBeTruthy();
  });

  it('moves IP addresses into the workspace while preserving prefix context', () => {
    const nav = setup();
    const workspace = nav.getByRole('button', { name: 'IPAM 工作台' });
    fireEvent.click(workspace);
    const region = document.getElementById(workspace.getAttribute('aria-controls')!);
    expect(region).toBeTruthy();
    fireEvent.click(within(region!).getByRole('button', { name: 'IP 地址' }));
    expect(screen.getByTestId('route').textContent).toBe('/ipam/ips?prefix_id=prefix-example');
    expect(workspace.getAttribute('aria-expanded')).toBe('true');
    expect(nav.getByRole('button', { name: '网段' })).toBeTruthy();
  });

  it('places discovered endpoints directly after IP addresses in the IPAM workbench', () => {
    const nav = setup();
    const workspace = nav.getByRole('button', { name: 'IPAM 工作台' });
    fireEvent.click(workspace);
    const region = document.getElementById(workspace.getAttribute('aria-controls')!);
    expect(region).toBeTruthy();
    const ipAddresses = within(region!).getByRole('button', { name: 'IP 地址' });
    const endpoints = within(region!).getByRole('button', { name: '发现终端' });
    expect(ipAddresses.compareDocumentPosition(endpoints) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(endpoints);
    expect(screen.getByTestId('route').textContent).toBe('/ipam/endpoints');
  });
});
