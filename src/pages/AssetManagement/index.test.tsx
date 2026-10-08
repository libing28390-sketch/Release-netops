import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AssetManagementTab from './index';

vi.mock('../../hooks/useSystem', () => ({ useSystem: () => ({ systemInfo: {} }) }));
vi.mock('../../components/DataTable', () => ({
  DataTable: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
  DataTableFrame: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('../../components/PageHero', () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock('./components/AssetModal', () => ({
  AssetModal: (props: any) => props.isOpen ? (
    <section role="dialog" aria-label="Asset editor">
      <label>
        Hostname
        <input
          aria-label="Hostname"
          value={props.form.hostname}
          onChange={event => props.setForm((current: any) => ({ ...current, hostname: event.target.value }))}
        />
      </label>
      <output data-testid="secret-values">{JSON.stringify([
        props.form.password,
        props.form.normal_password,
        props.form.admin_password,
        props.form.enable_password,
        props.form.snmp_community,
        ...(props.form.web_profiles || []).flatMap((profile: any) => [profile.normal_password, profile.admin_password]),
      ])}</output>
      {props.modalError && <p role="alert">{props.modalError}</p>}
      <button type="button" onClick={() => { void props.doSave(); void props.doSave(); }}>Double save</button>
      <button type="button" onClick={() => { void props.handleSave(); }}>Save</button>
    </section>
  ) : null,
}));
vi.mock('./components/DeleteConfirmModal', () => ({ DeleteConfirmModal: () => null }));
vi.mock('./components/AssetImportValidationModal', () => ({ AssetImportValidationModal: () => null }));
vi.mock('./components/TerminalAccessModal', () => ({ TerminalAccessModal: () => null }));
vi.mock('./components/AssetDetailDrawer', () => ({ AssetDetailDrawer: () => null }));

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

const renderAssetPage = () => render(
  <AssetManagementTab language="en" t={key => key} />,
);

describe('AssetManagementTab request states', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uses the requested default columns and reveals optional columns on demand', async () => {
    window.localStorage.removeItem('netops:assets:columns:v1');
    const asset = {
      id: 'asset-columns-1',
      asset_type: 'server',
      asset_tag: 'SRV-COLUMNS-1',
      hostname: 'server-columns-1',
      management_ip: '192.0.2.20',
      status: 'active',
      lifecycle_status: 'production',
      tags: [],
    };
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [asset], total: 1 });
      if (url === '/api/assets/summary') return response({ total: 1, online: 1, offline: 0 });
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      return response({});
    });

    renderAssetPage();
    await screen.findByText('server-columns-1');

    for (const column of [
      'Device', 'Asset tag', 'Asset type', 'Category', 'Role', 'Site', 'Status',
      'Vendor', 'Model', 'Serial', 'Management IP', 'Asset status',
    ]) {
      expect(screen.getByRole('columnheader', { name: column })).toBeTruthy();
    }
    expect(screen.queryByRole('columnheader', { name: 'Rack' })).toBeNull();
    expect(screen.queryByRole('columnheader', { name: 'Rack U' })).toBeNull();
    expect(screen.queryByRole('columnheader', { name: 'Tags' })).toBeNull();
    expect(screen.queryByRole('columnheader', { name: 'SSH algorithm' })).toBeNull();
    expect(screen.getByRole('columnheader', { name: 'Actions' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Columns' }));
    const selectedColumns = [
      'Device', 'Asset tag', 'Asset type', 'Category', 'Role', 'Site', 'Status',
      'Vendor', 'Model', 'Serial', 'Management IP', 'Asset status',
    ];
    for (const column of selectedColumns) {
      expect((screen.getByRole('checkbox', { name: column }) as HTMLInputElement).checked).toBe(true);
    }
    for (const column of ['Rack', 'Rack U', 'Tags', 'Created', 'Updated']) {
      expect((screen.getByRole('checkbox', { name: column }) as HTMLInputElement).checked).toBe(false);
    }
    expect(screen.queryByRole('checkbox', { name: 'SSH algorithm' })).toBeNull();

    fireEvent.click(screen.getByRole('checkbox', { name: 'Rack' }));

    expect(await screen.findByRole('columnheader', { name: 'Rack' })).toBeTruthy();
  });

  it('migrates the previously auto-saved default columns', async () => {
    window.localStorage.setItem('netops:assets:columns:v1', JSON.stringify({
      hostname: true,
      asset_tag: false,
      asset_type: true,
      device_category: false,
      device_role: false,
      site: false,
      rack: true,
      rack_unit: true,
      status: true,
      tags: false,
      vendor: false,
      model: false,
      serial_number: false,
      management_ip: true,
      ssh_algorithm_profile: false,
      lifecycle: false,
      created_at: true,
      updated_at: true,
    }));
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [], total: 0 });
      if (url === '/api/assets/summary') return response({ total: 0, online: 0, offline: 0 });
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      return response({});
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    fireEvent.click(screen.getByRole('button', { name: 'Columns' }));

    expect((screen.getByRole('checkbox', { name: 'Asset tag' }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: 'Rack' }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole('checkbox', { name: 'Created' }) as HTMLInputElement).checked).toBe(false);
  });

  it('shows a permission state instead of an empty inventory when the asset API returns 403', async () => {
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ detail: 'forbidden' }, 403);
      if (url === '/api/assets/summary') return response({ total: 0, online: 0, offline: 0 });
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      return response({});
    });

    renderAssetPage();

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('You do not have permission to view asset list.');
    expect(screen.getByText('You do not have permission to view the asset list.')).toBeTruthy();
    expect(screen.queryByText('No asset records')).toBeNull();
  });

  it('deduplicates page saves and keeps the entered hostname after a validation failure', async () => {
    let finishSave!: (result: Response) => void;
    vi.mocked(fetch).mockImplementation(input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return Promise.resolve(response({ items: [], total: 0 }));
      if (url === '/api/assets/summary') return Promise.resolve(response({ total: 0, online: 0, offline: 0 }));
      if (url === '/api/cmdb/sites') return Promise.resolve(response({ data: [] }));
      if (url === '/api/racks') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/tags/definitions') return Promise.resolve(response({ data: [] }));
      if (url === '/api/assets' && (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]?.method === 'POST') {
        return new Promise<Response>(resolve => { finishSave = resolve; });
      }
      return Promise.resolve(response({}));
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    fireEvent.click(screen.getByRole('button', { name: 'Add Asset' }));
    const hostname = screen.getByRole('textbox', { name: 'Hostname' }) as HTMLInputElement;
    fireEvent.change(hostname, { target: { value: 'edge-01' } });

    fireEvent.click(screen.getByRole('button', { name: 'Double save' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/assets', expect.objectContaining({ method: 'POST' })));
    expect(vi.mocked(fetch).mock.calls.filter(([input, init]) => String(input) === '/api/assets' && (init as RequestInit | undefined)?.method === 'POST')).toHaveLength(1);

    finishSave(response({ detail: 'Invalid management address' }, 422));
    await screen.findByText('Invalid management address');
    expect(screen.getByText('Invalid management address').closest('[role="alert"]')).toBeTruthy();
    expect(screen.getByRole('textbox', { name: 'Hostname' })).toHaveProperty('value', 'edge-01');
  });

  it('does not prefill credential or community secrets when opening an existing asset', async () => {
    const asset = {
      id: 'asset-1',
      asset_type: 'server',
      asset_tag: 'SRV-1',
      hostname: 'server-01',
      vendor: 'Dell',
      model: 'R760',
      site_id: '',
      rack: '',
      rack_unit: '',
      u_height: 1,
      management_ip: '192.0.2.10',
      business_ip: '',
      device_role: '',
      status: 'active',
      lifecycle_status: 'staging',
      platform: 'linux',
      connection_method: 'ssh',
      snmp_community: 'must-not-prefill',
      snmp_community_set: true,
      password: 'must-not-prefill',
      normal_password: 'must-not-prefill',
      admin_password: 'must-not-prefill',
      enable_password: 'must-not-prefill',
      web_profiles: [{ id: 'web-1', profile_name: 'BMC', scheme: 'https', port: 443, path: '/', enabled: true, normal_password: 'must-not-prefill', admin_password: 'must-not-prefill' }],
      tags: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [asset], total: 1 });
      if (url === '/api/assets/summary') return response({ total: 1, online: 1, offline: 0 });
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      return response({});
    });

    renderAssetPage();
    await screen.findByText('server-01');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));

    expect(JSON.parse(screen.getByTestId('secret-values').textContent || 'null')).toEqual(['', '', '', '', '', '', '']);
  });
});
