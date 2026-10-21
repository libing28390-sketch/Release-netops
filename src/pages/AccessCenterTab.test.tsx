import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AccessCenterTab from './AccessCenterTab';

vi.mock('framer-motion', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
  },
}));
vi.mock('../components/PageHero', () => ({
  default: ({ title, actions, extras }: { title: string; actions?: React.ReactNode; extras?: React.ReactNode }) => <header><h1>{title}</h1>{actions}{extras}</header>,
}));
vi.mock('../components/DataTable', () => ({
  DataTable: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
}));
vi.mock('../components/Pagination', () => ({ default: () => null }));
vi.mock('../components/access/TerminalWindow', () => ({ default: () => null }));
vi.mock('./AccessCenterTab/components/DeviceMfaModal', () => ({ default: () => null }));
vi.mock('./AssetManagement/components/WebAccessRequestModal', () => ({ WebAccessRequestModal: () => null }));
vi.mock('./AccessCenterTab/components/WindowsServiceModal', () => ({ default: () => null }));
vi.mock('../components/access/RemoteDesktopAccessModal', () => ({ default: () => null }));

describe('AccessCenterTab controls', () => {
  afterEach(() => cleanup());

  it('labels asset search and announces the active protocol filter and connection level', () => {
    render(
      <AccessCenterTab
        devices={[{
          id: 'device-1',
          hostname: 'router-1',
          ip_address: '192.0.2.1',
          status: 'online',
          platform: 'Cisco IOS',
          connection_method: 'ssh',
          normal_username: 'netops',
          admin_username: 'admin',
          vendor: 'Cisco',
          site_name: 'DC 1',
        }]}
        assetsTotal={1}
        assetsTotalError={null}
        language="en"
        showToast={vi.fn()}
      />,
    );

    expect(screen.getByRole('searchbox', { name: 'Search asset name or IP address' })).toBeTruthy();
    const allFilter = screen.getByRole('button', { name: 'ALL' });
    const sshFilter = screen.getByRole('button', { name: 'SSH' });
    expect(allFilter.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(sshFilter);
    expect(sshFilter.getAttribute('aria-pressed')).toBe('true');
    expect(allFilter.getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('button', { name: 'Open a local terminal for router-1 with standard credentials' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open a local terminal for router-1 with privileged credentials' })).toBeTruthy();
  });
});
