import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CmdbManagementTab, { calculatePageCount } from './CmdbManagementTab';

const fetchSuccess = () => ({
  ok: true,
  status: 200,
  json: async () => ({ success: true, data: [] }),
}) as Response;

const pagedResponse = (items: unknown[], total: number, page: number, pageSize = 10) => ({
  ok: true,
  status: 200,
  json: async () => ({
    success: true,
    data: { items, total, page, page_size: pageSize, total_pages: Math.max(1, Math.ceil(total / pageSize)) },
  }),
}) as Response;

const vlanRow = (id: string, vlanId: number, name: string) => ({
  id,
  vlan_id: vlanId,
  name,
  site_id: 'site-a',
  site_name: 'Site A',
  status: 'active',
  prefixes: '',
  gateway: '',
  port_count: 0,
  device_count: 0,
});

describe('CMDB import dialog interaction', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetchSuccess));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('exposes the credential import dialog and closes it with Escape', async () => {
    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    const uploadButton = await screen.findByRole('button', { name: 'Upload credentials' });
    expect(uploadButton).toBeTruthy();

    const file = new File(['not a valid workbook'], 'credentials.csv', { type: 'text/csv' });
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new ArrayBuffer(0) });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).toBeTruthy();
    fireEvent.change(fileInput as HTMLInputElement, { target: { files: [file] } });

    const dialog = await screen.findByRole('dialog', { name: 'Upload Credentials' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm import' }).hasAttribute('disabled')).toBe(true));

    screen.getByRole('button', { name: 'Cancel' }).focus();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Upload Credentials' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(uploadButton));
  });

  it('shows SNMP bindings as collection credentials without SSH binding actions', async () => {
    const credential = {
      id: 'cred-snmp',
      credential_name: 'snmp-ro',
      credential_type: 'snmpv2',
      username: '',
      account_role: 'snmp',
      account_role_label: 'SNMP 采集',
      device_count: 1,
      devices: [{ id: 'device-ac11', hostname: 'AC_11', ip_address: '192.0.2.11', binding_role: 'snmp' }],
      devices_truncated: false,
      enable_password_supported: false,
    };
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/credentials')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ success: true, data: [credential] }),
        } as Response);
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    expect(await screen.findByText('snmp-ro')).toBeTruthy();
    expect(screen.getByText('AC_11')).toBeTruthy();
    expect(screen.getByText('SNMP Collection')).toBeTruthy();
    expect(screen.getByText('SNMP')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'SNMP' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Normal' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Priv' })).toBeNull();
  });
});

describe('CMDB server-side pagination', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetchSuccess));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('calculates page count from the server total, not the current page rows', () => {
    expect(calculatePageCount(25, 10)).toBe(3);
    expect(calculatePageCount(0, 10)).toBe(1);
    expect(calculatePageCount(25, 0)).toBe(1);
  });

  it('keeps VLAN page 2 selected and submits search only when requested', async () => {
    const vlanRequests: URL[] = [];
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') {
        vlanRequests.push(url);
        const page = Number(url.searchParams.get('page') || 1);
        const query = url.searchParams.get('q') || '';
        const row = query ? vlanRow('vlan-search', 42, 'VLAN search result')
          : page === 1 ? vlanRow('vlan-page-1', 10, 'VLAN page 1')
            : vlanRow('vlan-page-2', 20, 'VLAN page 2');
        return Promise.resolve(pagedResponse([row], query ? 1 : 25, page, Number(url.searchParams.get('page_size') || 10)));
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="vlans" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    expect(await screen.findByText('VLAN page 1')).toBeTruthy();
    expect(vlanRequests).toHaveLength(1);
    expect(vlanRequests[0].searchParams.get('page_size')).toBe('10');

    fireEvent.click(screen.getByTitle('Next page'));
    expect(await screen.findByText('VLAN page 2')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('spinbutton', { name: 'Current page' })).toHaveProperty('value', '2'));
    expect(vlanRequests.map(url => url.searchParams.get('page'))).toEqual(['1', '2']);

    const searchInput = screen.getByRole('textbox', { name: 'Search VLAN ID or name' });
    fireEvent.change(searchInput, { target: { value: '42' } });
    expect(vlanRequests).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByText('VLAN search result')).toBeTruthy();
    await waitFor(() => expect(vlanRequests).toHaveLength(3));
    expect(vlanRequests[2].searchParams.get('q')).toBe('42');
    expect(vlanRequests[2].searchParams.get('page')).toBe('1');

    fireEvent.click(screen.getByRole('button', { name: 'Refresh VLAN list' }));
    await waitFor(() => expect(vlanRequests).toHaveLength(4));
    expect(vlanRequests[3].searchParams.get('q')).toBe('42');
    expect(vlanRequests[3].searchParams.get('page')).toBe('1');
  });

  it('keeps interface server pages intact without applying client-side slicing', async () => {
    const interfaceRequests: URL[] = [];
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/interfaces') {
        interfaceRequests.push(url);
        const page = Number(url.searchParams.get('page') || 1);
        return Promise.resolve(pagedResponse([{
          id: `interface-${page}`,
          device_hostname: 'router-a',
          device_ip: '192.0.2.10',
          interface_name: page === 1 ? 'Ethernet1/0/1' : 'Ethernet1/0/2',
          interface_ip: `192.0.2.${page}/24`,
          oper_status: 'up',
          admin_status: 'up',
        }], 25, page));
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="interfaces" currentUser={{ role: 'Viewer' }} />
      </MemoryRouter>,
    );

    expect(await screen.findByText('Ethernet1/0/1')).toBeTruthy();
    fireEvent.click(screen.getByTitle('Next page'));
    expect(await screen.findByText('Ethernet1/0/2')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('spinbutton', { name: 'Current page' })).toHaveProperty('value', '2'));
    expect(interfaceRequests.map(url => url.searchParams.get('page'))).toEqual(['1', '2']);
    expect(interfaceRequests.every(url => url.searchParams.get('has_ip') === 'true')).toBe(true);
  });

  it('cancels an older VLAN search without allowing it to replace the latest result', async () => {
    const vlanRequests: URL[] = [];
    let oldSearchSignal: AbortSignal | undefined;
    let resolveOldSearch: ((response: Response) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') {
        vlanRequests.push(url);
        const query = url.searchParams.get('q') || '';
        if (query === 'older') {
          oldSearchSignal = init?.signal as AbortSignal | undefined;
          return new Promise<Response>(resolve => { resolveOldSearch = resolve; });
        }
        const row = query ? vlanRow(`vlan-${query}`, 42, `VLAN ${query} result`) : vlanRow('vlan-base', 1, 'VLAN initial result');
        return Promise.resolve(pagedResponse([row], 1, 1));
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="vlans" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    expect(await screen.findByText('VLAN initial result')).toBeTruthy();
    const searchInput = screen.getByRole('textbox', { name: 'Search VLAN ID or name' });
    fireEvent.change(searchInput, { target: { value: 'older' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(vlanRequests).toHaveLength(2));

    fireEvent.change(searchInput, { target: { value: 'newer' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByText('VLAN newer result')).toBeTruthy();
    expect(oldSearchSignal?.aborted).toBe(true);

    resolveOldSearch?.(pagedResponse([vlanRow('vlan-older', 41, 'VLAN older result')], 1, 1));
    await waitFor(() => expect(screen.getByText('VLAN newer result')).toBeTruthy());
    expect(screen.queryByText('VLAN older result')).toBeNull();
  });

  it('uses the vlan-business tab contract and loads VLAN choices only when its form opens', async () => {
    const bindingRequests: URL[] = [];
    const vlanRequests: URL[] = [];
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlan-business-bindings') {
        bindingRequests.push(url);
        const page = Number(url.searchParams.get('page') || 1);
        const item = {
          id: `binding-${page}`,
          vlan_id: page === 1 ? 10 : 20,
          site_id: 'site-a',
          site_name: 'Site A',
          business_system: page === 1 ? 'Finance platform' : 'Payroll platform',
          department: 'Finance',
          owner: 'Operator',
          status: 'active',
        };
        return Promise.resolve(pagedResponse([item], 25, page));
      }
      if (url.pathname === '/api/cmdb/vlans') {
        vlanRequests.push(url);
        return Promise.resolve(pagedResponse([vlanRow('vlan-form', 10, 'Form VLAN')], 1, 1, 100));
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="vlan-business" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    expect(await screen.findByText('Finance platform')).toBeTruthy();
    expect(bindingRequests).toHaveLength(1);
    expect(bindingRequests[0].pathname).toBe('/api/cmdb/vlan-business-bindings');
    expect(bindingRequests[0].searchParams.get('page')).toBe('1');
    expect(bindingRequests[0].searchParams.get('page_size')).toBe('10');
    expect(vlanRequests).toHaveLength(0);

    fireEvent.click(screen.getByTitle('Next page'));
    expect(await screen.findByText('Payroll platform')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('spinbutton', { name: 'Current page' })).toHaveProperty('value', '2'));
    expect(bindingRequests.map(url => url.searchParams.get('page'))).toEqual(['1', '2']);

    fireEvent.change(screen.getByRole('textbox', { name: 'Search VLAN business bindings' }), { target: { value: 'Payroll' } });
    expect(bindingRequests).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(bindingRequests).toHaveLength(3));
    expect(bindingRequests[2].searchParams.get('q')).toBe('Payroll');
    expect(bindingRequests[2].searchParams.get('page')).toBe('1');

    fireEvent.change(screen.getByRole('combobox', { name: 'Binding status' }), { target: { value: 'active' } });
    await waitFor(() => expect(bindingRequests).toHaveLength(4));
    expect(bindingRequests[3].searchParams.get('q')).toBe('Payroll');
    expect(bindingRequests[3].searchParams.get('status')).toBe('active');

    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    await waitFor(() => expect(vlanRequests).toHaveLength(1));
    expect(vlanRequests[0].searchParams.get('page')).toBe('1');
    expect(vlanRequests[0].searchParams.get('page_size')).toBe('100');
    expect(vlanRequests[0].searchParams.get('site_id')).toBe('unassigned');

    const dialog = screen.getByRole('dialog', { name: /New Record/ });
    const vlanSearch = within(dialog).getByRole('searchbox', { name: 'Search VLAN ID or name' });
    fireEvent.change(vlanSearch, { target: { value: '20' } });
    expect(vlanRequests).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(vlanRequests).toHaveLength(2));
    expect(vlanRequests[1].searchParams.get('q')).toBe('20');
    expect(vlanRequests[1].searchParams.get('site_id')).toBe('unassigned');
  });

  it('shows loading and permission errors for the VLAN list', async () => {
    let resolveVlanRequest: ((response: Response) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') {
        return new Promise<Response>(resolve => { resolveVlanRequest = resolve; });
      }
      return Promise.resolve(fetchSuccess());
    }));

    const view = render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="vlans" currentUser={{ role: 'Viewer' }} />
      </MemoryRouter>,
    );
    expect(await screen.findByText('Loading VLAN data...')).toBeTruthy();
    resolveVlanRequest?.({
      ok: false,
      status: 403,
      json: async () => ({ success: false, detail: 'Insufficient permission for VLAN inventory' }),
    } as Response);
    expect(await screen.findByText('Insufficient permission for VLAN inventory')).toBeTruthy();
    view.unmount();
  });
});

describe('CMDB VLAN lazy details', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-vlan-token');
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetchSuccess));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.removeItem('netops_token');
  });

  const renderVlanTab = () => render(
    <MemoryRouter>
      <CmdbManagementTab language="en" cmdbPage="vlans" currentUser={{ role: 'Administrator' }} />
    </MemoryRouter>,
  );

  const openDetailsFor = (name: string) => {
    const row = screen.getByText(name).closest('tr');
    expect(row).toBeTruthy();
    fireEvent.click(within(row as HTMLElement).getByRole('button', { name: 'View details' }));
  };

  it('loads detail data on demand with the scoped authenticated request and reuses it on reopen', async () => {
    const detailRequests: Array<{ url: URL; init?: RequestInit }> = [];
    let resolveDetails: ((response: Response) => void) | undefined;
    const row = { ...vlanRow('vlan-lazy', 37, 'Lazy VLAN'), device_id: 'device-a' };
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') return Promise.resolve(pagedResponse([row], 1, 1));
      if (url.pathname.startsWith('/api/cmdb/vlans/') && url.pathname.endsWith('/details')) {
        detailRequests.push({ url, init });
        return new Promise<Response>(resolve => { resolveDetails = resolve; });
      }
      return Promise.resolve(fetchSuccess());
    }));

    renderVlanTab();
    expect(await screen.findByText('Lazy VLAN')).toBeTruthy();
    expect(detailRequests).toHaveLength(0);

    openDetailsFor('Lazy VLAN');
    expect(await screen.findByText('Loading VLAN details...')).toBeTruthy();
    expect(detailRequests).toHaveLength(1);
    expect(detailRequests[0].url.pathname).toBe('/api/cmdb/vlans/vlan-lazy/details');
    expect(detailRequests[0].url.searchParams.get('site_id')).toBe('site-a');
    expect(detailRequests[0].url.searchParams.get('device_id')).toBe('device-a');
    expect((detailRequests[0].init?.headers as Record<string, string>).Authorization).toBe('Bearer test-vlan-token');

    resolveDetails?.({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          port_detail_rows: [{ device_hostname: 'switch-lazy', interface_name: 'GigabitEthernet0/1', description: 'uplink' }],
          endpoint_details: [],
          meta: { detail_count: 1 },
        },
        message: '',
      }),
    } as Response);
    expect(await screen.findByText('GigabitEthernet0/1')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    openDetailsFor('Lazy VLAN');
    expect(await screen.findByText('GigabitEthernet0/1')).toBeTruthy();
    expect(detailRequests).toHaveLength(1);
  });

  it('shows permission errors, retries, and distinguishes a successful empty response', async () => {
    let detailRequestCount = 0;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') return Promise.resolve(pagedResponse([vlanRow('vlan-retry', 41, 'Retry VLAN')], 1, 1));
      if (url.pathname.endsWith('/details')) {
        detailRequestCount += 1;
        return Promise.resolve(detailRequestCount === 1
          ? {
            ok: false,
            status: 403,
            json: async () => ({ success: false, detail: 'Insufficient permission to view VLAN details' }),
          } as Response
          : {
            ok: true,
            status: 200,
            json: async () => ({ success: true, data: { port_detail_rows: [], endpoint_details: [], meta: {} }, message: '' }),
          } as Response);
      }
      return Promise.resolve(fetchSuccess());
    }));

    renderVlanTab();
    expect(await screen.findByText('Retry VLAN')).toBeTruthy();
    openDetailsFor('Retry VLAN');
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('You do not have permission to view this VLAN’s details.')).toBeTruthy();
    expect(screen.getByText('Insufficient permission to view VLAN details')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No interface or ARP/MAC details')).toBeTruthy();
    expect(detailRequestCount).toBe(2);
  });

  it('requests full VLAN details for export while keeping the ordinary list light', async () => {
    const vlanRequests: URL[] = [];
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') {
        vlanRequests.push(url);
        return Promise.resolve(pagedResponse([vlanRow('vlan-export', 44, 'Export VLAN')], 1, Number(url.searchParams.get('page') || 1), Number(url.searchParams.get('page_size') || 10)));
      }
      return Promise.resolve(fetchSuccess());
    }));

    renderVlanTab();
    expect(await screen.findByText('Export VLAN')).toBeTruthy();
    expect(vlanRequests[0].searchParams.get('include_details')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Export table' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Export CSV (.csv)' }));
    await waitFor(() => expect(vlanRequests.some(url => url.searchParams.get('include_details') === 'true')).toBe(true));
    expect(vlanRequests.filter(url => url.searchParams.get('include_details') === 'true')).toHaveLength(1);
  });

  it('aborts and ignores a previous VLAN response after closing and opening another row', async () => {
    let firstRequestSignal: AbortSignal | undefined;
    let resolveFirstDetails: ((response: Response) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') {
        return Promise.resolve(pagedResponse([
          vlanRow('vlan-first', 51, 'First VLAN'),
          vlanRow('vlan-second', 52, 'Second VLAN'),
        ], 2, 1));
      }
      if (url.pathname.endsWith('/vlan-first/details')) {
        firstRequestSignal = init?.signal as AbortSignal | undefined;
        return new Promise<Response>(resolve => { resolveFirstDetails = resolve; });
      }
      if (url.pathname.endsWith('/vlan-second/details')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            success: true,
            data: { port_detail_rows: [{ interface_name: 'Second interface' }], endpoint_details: [], meta: {} },
            message: '',
          }),
        } as Response);
      }
      return Promise.resolve(fetchSuccess());
    }));

    renderVlanTab();
    expect(await screen.findByText('First VLAN')).toBeTruthy();
    openDetailsFor('First VLAN');
    expect(await screen.findByText('Loading VLAN details...')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(firstRequestSignal?.aborted).toBe(true);

    openDetailsFor('Second VLAN');
    expect(await screen.findByText('Second interface')).toBeTruthy();
    resolveFirstDetails?.({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: { port_detail_rows: [{ interface_name: 'Stale first interface' }], endpoint_details: [], meta: {} },
        message: '',
      }),
    } as Response);
    expect(screen.queryByText('Stale first interface')).toBeNull();
    expect(screen.getByText('Second interface')).toBeTruthy();
  });
});

describe('CMDB observed-only row actions', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetchSuccess));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows interface profile editing only for shared interface rows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/interfaces') {
        return Promise.resolve(pagedResponse([
          {
            id: 'shared-interface-1',
            profile_editable: true,
            device_hostname: 'router-a',
            device_ip: '192.0.2.10',
            interface_name: 'Ethernet1/0/1',
          },
          {
            id: 'cmdb-interface-observed:router-a:Ethernet1/0/2',
            profile_editable: false,
            device_hostname: 'router-a',
            device_ip: '192.0.2.10',
            interface_name: 'Ethernet1/0/2',
          },
        ], 2, 1));
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="interfaces" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    const sharedRow = await screen.findByText('Ethernet1/0/1').then(element => element.closest('tr'));
    const observedRow = await screen.findByText('Ethernet1/0/2').then(element => element.closest('tr'));
    expect(sharedRow).toBeTruthy();
    expect(observedRow).toBeTruthy();
    expect(within(sharedRow as HTMLElement).getByRole('button', { name: 'Edit monitoring profile' })).toBeTruthy();
    expect(within(observedRow as HTMLElement).queryByRole('button', { name: 'Edit monitoring profile' })).toBeNull();
  });

  it('keeps VLAN details visible and hides edits for CLI-only VLAN rows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/vlans') {
        return Promise.resolve(pagedResponse([
          vlanRow('vlan-shared', 10, 'Shared VLAN'),
          { ...vlanRow('vlan-observed', 20, 'Observed VLAN'), cmdb_observed_only: true },
        ], 2, 1));
      }
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="vlans" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    const sharedRow = await screen.findByText('Shared VLAN').then(element => element.closest('tr'));
    const observedRow = screen.getByText('Observed VLAN').closest('tr');
    expect(sharedRow).toBeTruthy();
    expect(observedRow).toBeTruthy();
    expect(within(sharedRow as HTMLElement).getByRole('button', { name: 'View details' })).toBeTruthy();
    expect(within(sharedRow as HTMLElement).getByRole('button', { name: 'Edit' })).toBeTruthy();
    expect(within(sharedRow as HTMLElement).getByRole('button', { name: 'Delete' })).toBeTruthy();
    expect(within(observedRow as HTMLElement).getByRole('button', { name: 'View details' })).toBeTruthy();
    expect(within(observedRow as HTMLElement).queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(within(observedRow as HTMLElement).queryByRole('button', { name: 'Delete' })).toBeNull();
  });

  it('retains the terminal interface collection summary after polling stops and a later start fails', async () => {
    const terminalJob = {
      job_id: 'interface-job-final',
      status: 'succeeded',
      total_targets: 2,
      success_count: 2,
      failed_count: 0,
      target_status_counts: { queued: 0, running: 0, succeeded: 2, failed: 0, timeout: 0, cancelled: 0 },
      targets: [],
    };
    let launchAttempts = 0;

    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/cmdb/interfaces/sync' && init?.method === 'POST') {
        launchAttempts += 1;
        if (launchAttempts > 1) {
          return Promise.resolve({
            ok: false,
            status: 403,
            json: async () => ({ detail: 'Permission denied' }),
          } as Response);
        }
        return Promise.resolve({
          ok: true,
          status: 202,
          json: async () => ({ success: true, data: { job_id: terminalJob.job_id, job: { ...terminalJob, status: 'running', success_count: 0, target_status_counts: { queued: 1, running: 1, succeeded: 0, failed: 0, timeout: 0, cancelled: 0 } } } }),
        } as Response);
      }
      if (url.pathname === `/api/cmdb/interfaces/sync/${terminalJob.job_id}`) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ success: true, data: terminalJob }) } as Response);
      }
      if (url.pathname === '/api/cmdb/interfaces') return Promise.resolve(pagedResponse([], 0, 1));
      return Promise.resolve(fetchSuccess());
    }));

    render(
      <MemoryRouter>
        <CmdbManagementTab language="en" cmdbPage="interfaces" currentUser={{ role: 'Administrator' }} />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Collect Interfaces' }));
    expect(await screen.findByText('Completed 2 / 2')).toBeTruthy();
    expect(screen.getByText('Interface collection finished: 2 succeeded, 0 failed.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'View details' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Collect Interfaces' }));
    expect(await screen.findByText('Permission denied')).toBeTruthy();
    expect(screen.getByText('Completed 2 / 2')).toBeTruthy();
  });
});
