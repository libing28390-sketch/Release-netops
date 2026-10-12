import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AssetManagementTab from './index';
import { useInventoryStore } from '../../store/inventoryStore';

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
vi.mock('xlsx', () => ({
  read: vi.fn(() => ({ SheetNames: ['Sheet1'], Sheets: { Sheet1: {} } })),
  utils: {
    sheet_to_json: vi.fn(() => [{ Hostname: 'progressive-import-server', 'Asset Type': 'server', 'Mgmt IP': '192.0.2.220' }]),
  },
}));

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

const assetSummary = (networkDevices: number, servers: number) => response({
  total: networkDevices + servers,
  by_type: { network_device: networkDevices, server: servers },
  by_status: {},
  by_severity: { critical: 0, major: 0, warning: 0, healthy: networkDevices + servers },
  by_vendor: {},
  by_site: {},
  by_department: {},
  warranty_expiring_soon: 0,
});

const renderAssetPage = () => render(
  <AssetManagementTab language="en" t={key => key} />,
);

describe('AssetManagementTab request states', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    useInventoryStore.setState(useInventoryStore.getInitialState());
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
      if (url === '/api/assets/summary') return assetSummary(1, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      return response({});
    });

    renderAssetPage();
    await screen.findByText('server-columns-1');
    await waitFor(() => expect(useInventoryStore.getState().assetsTotal).toBe(1));

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

  it('uses server severity counts and server-side pagination for severity cards', async () => {
    window.localStorage.removeItem('netops:assets:columns:v1');
    const onlineAsset = {
      id: 'asset-online-1', asset_type: 'network_device', asset_tag: 'TAG-ONLINE-1',
      hostname: 'online-device', management_ip: '192.0.2.31', status: 'active',
      lifecycle_status: 'production', online_status: 'online', tags: [],
    };
    const offlineAsset = {
      id: 'asset-offline-1', asset_type: 'network_device', asset_tag: 'TAG-OFFLINE-1',
      hostname: 'offline-device', management_ip: '192.0.2.32', status: 'active',
      lifecycle_status: 'production', online_status: 'offline', tags: [],
    };
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) {
        const severity = new URL(url, 'http://test').searchParams.get('severity');
        return severity === 'critical'
          ? response({ items: [offlineAsset], total: 23 })
          : response({ items: [onlineAsset], total: 30 });
      }
      if (url === '/api/assets/summary') return response({
        total: 30,
        by_type: { network_device: 30, server: 0 },
        by_status: { active: 30 },
        by_severity: { critical: 23, major: 2, warning: 3, healthy: 2 },
        by_vendor: {}, by_site: {}, by_department: {}, warranty_expiring_soon: 0,
      });
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      return response({});
    });

    renderAssetPage();
    expect(await screen.findByText('online-device')).toBeTruthy();
    const criticalCard = screen.getByRole('button', { name: /Critical/ });
    expect(criticalCard.textContent).toContain('23');

    fireEvent.click(criticalCard);

    expect(await screen.findByText('offline-device')).toBeTruthy();
    await waitFor(() => expect(
      vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('severity=critical')),
    ).toBe(true));
    expect(screen.queryByText('online-device')).toBeNull();
    expect(screen.getByText('23 assets')).toBeTruthy();
  });

  it('refreshes the shared device count after an asset is saved', async () => {
    let summaryRequestCount = 0;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [], total: 0 });
      if (url === '/api/assets/summary') {
        summaryRequestCount += 1;
        return summaryRequestCount <= 2 ? assetSummary(0, 0) : assetSummary(2, 1);
      }
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets' && init?.method === 'POST') return response({ ok: true });
      return response({});
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    await waitFor(() => expect(useInventoryStore.getState().assetsTotal).toBe(0));
    fireEvent.click(screen.getByRole('button', { name: 'Add Asset' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Hostname' }), { target: { value: 'new-device' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(useInventoryStore.getState().assetsTotal).toBe(3));
    expect(fetch).toHaveBeenCalledWith('/api/assets', expect.objectContaining({ method: 'POST' }));
  });

  it('refreshes the visible list while a detailed import request is still running', async () => {
    const importedAsset = {
      id: 'asset-progressive-import',
      asset_type: 'server',
      asset_tag: 'progressive-import-server',
      hostname: 'progressive-import-server',
      management_ip: '192.0.2.220',
      status: 'active',
      lifecycle_status: 'staging',
      tags: [],
    };
    let importResolved = false;
    let finishImport!: (result: Response) => void;
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) {
        return Promise.resolve(response({ items: importResolved ? [importedAsset] : [], total: importResolved ? 1 : 0 }));
      }
      if (url === '/api/assets/summary') return Promise.resolve(assetSummary(importResolved ? 1 : 0, 0));
      if (url === '/api/cmdb/sites') return Promise.resolve(response({ data: [] }));
      if (url === '/api/racks') return Promise.resolve(response({ success: true, data: [] }));
      if (url === '/api/tags/definitions') return Promise.resolve(response({ data: [] }));
      if (url === '/api/assets/import?detailed=true') {
        return new Promise<Response>(resolve => { finishImport = resolve; });
      }
      return Promise.resolve(response({}));
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    const file = new File(['workbook'], 'assets.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } });
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/assets/import?detailed=true', expect.any(Object)));

    importResolved = true;
    expect((await screen.findAllByText('progressive-import-server', {}, { timeout: 3500 })).length).toBeGreaterThan(0);
    expect(screen.getByText(/Importing 1 row/)).toBeTruthy();

    finishImport(response({ created: 1, skipped: 0, failed: 0, skipped_items: [], failed_items: [] }));
    await screen.findByText(/Import done: 1 created/);
  });

  it('sends one batch-delete request for the selected assets', async () => {
    const asset = {
      id: 'asset-batch-delete-1',
      asset_type: 'server',
      asset_tag: 'tag-batch-delete-1',
      hostname: 'batch-delete-1',
      management_ip: '192.0.2.21',
      status: 'active',
      lifecycle_status: 'production',
      tags: [],
    };
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [asset], total: 1 });
      if (url === '/api/assets/summary') return assetSummary(0, 1);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets/batch-delete' && init?.method === 'POST') {
        return response({ deleted: 1, deleted_ids: [asset.id], failed: 0, failed_items: [] });
      }
      return response({});
    });

    renderAssetPage();
    await screen.findByText('batch-delete-1');
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[1]);
    fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }));

    await screen.findByText('Delete complete: 1 deleted, 0 failed');
    const batchDeleteCalls = vi.mocked(fetch).mock.calls.filter(([input, init]) =>
      String(input) === '/api/assets/batch-delete' && init?.method === 'POST',
    );
    expect(batchDeleteCalls).toHaveLength(1);
    expect(batchDeleteCalls[0][1]?.body).toBe(JSON.stringify({ asset_ids: [asset.id] }));
    expect(vi.mocked(fetch).mock.calls.some(([input, init]) => String(input) === `/api/assets/${asset.id}` && init?.method === 'DELETE')).toBe(false);
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
      if (url === '/api/assets/summary') return assetSummary(0, 0);
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
      if (url === '/api/assets/summary') return assetSummary(0, 0);
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
      if (url === '/api/assets/summary') return Promise.resolve(assetSummary(0, 0));
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
      if (url === '/api/assets/summary') return assetSummary(0, 1);
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
