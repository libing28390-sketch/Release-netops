import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as XLSX from 'xlsx';
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
      <output data-testid="ssh-profile">{props.form.ssh_algorithm_profile}</output>
      {props.modalError && <p role="alert">{props.modalError}</p>}
      <button type="button" onClick={() => { void props.doSave(); void props.doSave(); }}>Double save</button>
      <button type="button" onClick={() => props.setForm((current: any) => ({ ...current, normal_password: 'synthetic-test-password' }))}>Set synthetic secret</button>
      <button type="button" onClick={() => props.setForm((current: any) => ({
        ...current,
        asset_type: 'network_device',
        vendor: 'H3C',
        platform: 'h3c_comware',
        management_ip: '192.0.2.44',
        enable_password: 'synthetic-enable-secret',
      }))}>Set H3C network fields</button>
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
    vi.mocked(XLSX.utils.sheet_to_json).mockReturnValue([
      { Hostname: 'progressive-import-server', 'Asset Type': 'server', 'Mgmt IP': '192.0.2.220' },
    ]);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('keeps the batch takeover confirmation keyboard-contained and returns focus when cancelled', async () => {
    const asset = {
      id: 'asset-takeover-focus-1',
      asset_type: 'server',
      asset_tag: 'SRV-FOCUS-1',
      hostname: 'batch-focus-1',
      management_ip: '192.0.2.31',
      status: 'active',
      lifecycle_status: 'production',
      tags: [],
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
    await screen.findByText('batch-focus-1');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    const trigger = screen.getByRole('button', { name: 'Takeover' });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = await screen.findByRole('alertdialog', { name: 'Confirm batch takeover' });
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    await waitFor(() => expect(document.activeElement).toBe(cancel));
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('alertdialog', { name: 'Confirm batch takeover' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/assets/takeover/batch')).toBe(false);
    expect(dialog.isConnected).toBe(false);
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
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

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
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[0]);
    fireEvent.change(screen.getByRole('textbox', { name: 'Hostname' }), { target: { value: 'new-device' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(useInventoryStore.getState().assetsTotal).toBe(3));
    expect(fetch).toHaveBeenCalledWith('/api/assets', expect.objectContaining({ method: 'POST' }));
  });

  it('does not send an Enable password when creating an H3C asset', async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [], total: 0 });
      if (url === '/api/assets/summary') return assetSummary(0, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets' && init?.method === 'POST') return response({ ok: true });
      return response({});
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[0]);
    fireEvent.change(screen.getByRole('textbox', { name: 'Hostname' }), { target: { value: 'h3c-device' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set H3C network fields' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      const saveCall = vi.mocked(fetch).mock.calls.find(([input, init]) => String(input) === '/api/assets' && init?.method === 'POST');
      expect(saveCall).toBeDefined();
      expect(JSON.parse(String(saveCall?.[1]?.body)).enable_password).toBe('');
    });
  });

  it('uses the safe automatic SSH profile when copying a legacy-profile asset', async () => {
    const sourceAsset = {
      id: 'asset-copy-legacy-profile',
      asset_type: 'network_device',
      asset_tag: 'SW-COPY-01',
      hostname: 'legacy-profile-switch',
      management_ip: '192.0.2.81',
      status: 'active',
      lifecycle_status: 'staging',
      vendor: 'Cisco',
      platform: 'cisco_ios',
      ssh_algorithm_profile: 'legacy_break_glass',
      tags: [],
    };
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [sourceAsset], total: 1 });
      if (url === '/api/assets/summary') return assetSummary(1, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      return response({});
    });

    renderAssetPage();
    await screen.findByText('legacy-profile-switch');
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    expect((await screen.findByTestId('ssh-profile')).textContent).toBe('auto');
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

  it.each([
    {
      label: 'missing Profile reference',
      result: { created: 0, skipped: 0, failed: 1, failed_items: [{ row: 1, hostname: 'snmp-feedback', code: 'ASSET_SNMP_CREDENTIAL_NOT_FOUND', message: 'generic row failure' }] },
      expected: /credential center/i,
    },
    {
      label: 'missing Community and Profile on a created asset',
      result: { created: 1, skipped: 0, failed: 0, enrichment_pending: true, results: [{ row: 1, status: 'created' }] },
      expected: /lack SNMP Community\/Profile/i,
    },
    {
      label: 'successful SNMP platform binding',
      result: {
        created: 1,
        skipped: 0,
        failed: 0,
        results: [{
          row: 1,
          status: 'created',
          snmp_identification: {
            platform_binding_status: 'auto_bound',
            platform_profile_name: 'H3C Comware V7',
          },
        }],
      },
      expected: /automatically bound from SNMP.*H3C Comware V7/i,
    },
  ])('explains $label in the import feedback', async ({ result, expected }) => {
    vi.mocked(XLSX.utils.sheet_to_json).mockReturnValue([
      { Hostname: 'snmp-feedback', 'Asset Type': 'network_device', 'Mgmt IP': '192.0.2.222' },
    ]);
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [], total: 0 });
      if (url === '/api/assets/summary') return assetSummary(0, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets/import?detailed=true') return response(result);
      return response({});
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [new File(['workbook'], 'snmp-feedback.xlsx')] },
    });

    await screen.findByText(/Import done:/);
    expect(screen.getByRole('alert').textContent).toMatch(expected);
    expect(screen.getByRole('alert').textContent).not.toContain('generic row failure');
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

  it('retries hostname and model sync for selected devices and refreshes the displayed asset', async () => {
    const asset = {
      id: 'asset-manual-snmp-sync-1',
      asset_type: 'network_device',
      asset_tag: 'NET-MANUAL-SYNC-1',
      hostname: 'switch-before-sync',
      management_ip: '192.0.2.81',
      model: '',
      status: 'active',
      lifecycle_status: 'production',
      tags: [],
    };
    let syncCompleted = false;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) {
        return response({
          items: [syncCompleted ? { ...asset, hostname: 'switch-after-sync', model: 'H3C S6850' } : asset],
          total: 1,
        });
      }
      if (url === '/api/assets/summary') return assetSummary(1, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets/batch-snmp-sync' && init?.method === 'POST') {
        syncCompleted = true;
        return response({
          requested: 1,
          synced: 1,
          partial: 0,
          failed: 0,
          skipped: 0,
          results: [{
            asset_id: asset.id,
            device_id: 'device-manual-snmp-sync-1',
            hostname: 'switch-after-sync',
            management_ip: asset.management_ip,
            status: 'synced',
            message: '已获取主机名和型号',
            hostname_sync: { status: 'synced', hostname: 'switch-after-sync', error: '' },
            detected_model: 'H3C S6850',
            synced_model: 'H3C S6850',
            model_source: 'entity_mib',
            rack_sync: { status: 'synced', message: '机柜设备型号已同步' },
          }],
        });
      }
      return response({});
    });

    renderAssetPage();
    await screen.findByText('switch-before-sync');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByRole('button', { name: 'Retry name/model sync' }));

    await screen.findByText('Manual sync results');
    expect(await screen.findAllByText('switch-after-sync')).toHaveLength(2);
    expect(screen.getAllByText('H3C S6850').length).toBeGreaterThan(0);
    expect((screen.getAllByRole('checkbox')[1] as HTMLInputElement).checked).toBe(false);
    const requests = vi.mocked(fetch).mock.calls.filter(([input, init]) =>
      String(input) === '/api/assets/batch-snmp-sync' && init?.method === 'POST',
    );
    expect(requests).toHaveLength(1);
    expect(requests[0][1]?.body).toBe(JSON.stringify({ asset_ids: [asset.id] }));
  });

  it('keeps the in-progress message visible when manual sync takes longer than the toast lifetime', async () => {
    const asset = {
      id: 'asset-manual-snmp-long-running',
      asset_type: 'network_device',
      asset_tag: 'NET-MANUAL-SYNC-LONG',
      hostname: 'switch-long-running',
      management_ip: '192.0.2.83',
      status: 'active',
      lifecycle_status: 'production',
      tags: [],
    };
    let resolveSync!: (value: Response) => void;
    const pendingSync = new Promise<Response>(resolve => { resolveSync = resolve; });
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [asset], total: 1 });
      if (url === '/api/assets/summary') return assetSummary(1, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets/batch-snmp-sync' && init?.method === 'POST') return pendingSync;
      return response({});
    });

    renderAssetPage();
    await screen.findByText('switch-long-running');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByRole('button', { name: 'Retry name/model sync' }));

    const progressMessage = /Retrying hostname and model sync for 1 device/;
    expect(await screen.findByText(progressMessage)).toBeTruthy();
    await new Promise(resolve => setTimeout(resolve, 5200));
    expect(screen.getByText(progressMessage)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Syncing…' }) as HTMLButtonElement).disabled).toBe(true);

    resolveSync(response({
      requested: 1,
      synced: 1,
      partial: 0,
      failed: 0,
      skipped: 0,
      results: [{
        asset_id: asset.id,
        hostname: asset.hostname,
        management_ip: asset.management_ip,
        status: 'synced',
        message: '已同步',
        hostname_sync: { status: 'synced', hostname: asset.hostname, error: '' },
        detected_model: 'H3C S6850',
        synced_model: 'H3C S6850',
        model_source: 'entity_mib',
        rack_sync: { status: 'synced', message: '机柜型号已同步' },
      }],
    }));
    await screen.findByText('Manual sync results');
  }, 10000);

  it('keeps failed sync devices selected so the user can retry them', async () => {
    const asset = {
      id: 'asset-manual-snmp-retry-1',
      asset_type: 'network_device',
      asset_tag: 'NET-MANUAL-RETRY-1',
      hostname: 'switch-retry',
      management_ip: '192.0.2.82',
      status: 'active',
      lifecycle_status: 'production',
      tags: [],
    };
    let attempts = 0;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [asset], total: 1 });
      if (url === '/api/assets/summary') return assetSummary(1, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets/batch-snmp-sync' && init?.method === 'POST') {
        attempts += 1;
        if (attempts === 1) {
          return response({
            requested: 1,
            synced: 0,
            partial: 0,
            failed: 1,
            skipped: 0,
            results: [{
              asset_id: asset.id,
              hostname: asset.hostname,
              management_ip: asset.management_ip,
              status: 'failed',
              message: 'SNMP 查询超时，请检查设备响应后重试',
              hostname_sync: { status: 'failed', hostname: '', error: 'timeout' },
              detected_model: '',
              synced_model: '',
              model_source: '',
              rack_sync: { status: 'skipped', message: '型号未获取' },
            }],
          });
        }
        return response({
          requested: 1,
          synced: 1,
          partial: 0,
          failed: 0,
          skipped: 0,
          results: [{
            asset_id: asset.id,
            hostname: 'switch-retry-new',
            management_ip: asset.management_ip,
            status: 'synced',
            message: '已同步',
            hostname_sync: { status: 'synced', hostname: 'switch-retry-new', error: '' },
            detected_model: 'H3C S6850',
            synced_model: 'H3C S6850',
            model_source: 'entity_mib',
            rack_sync: { status: 'synced', message: '机柜设备型号已同步' },
          }],
        });
      }
      return response({});
    });

    renderAssetPage();
    await screen.findByText('switch-retry');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    const retryButton = screen.getByRole('button', { name: 'Retry name/model sync' });
    fireEvent.click(retryButton);

    expect(await screen.findByText(/SNMP 查询超时/)).toBeTruthy();
    expect((screen.getAllByRole('checkbox')[1] as HTMLInputElement).checked).toBe(true);
    fireEvent.click(retryButton);
    await waitFor(() => expect(attempts).toBe(2));
    await screen.findByText(/Model: H3C S6850/);
    expect((screen.getAllByRole('checkbox')[1] as HTMLInputElement).checked).toBe(false);
  });

  it('submits all selected devices without a client-side batch cap', async () => {
    const assets = Array.from({ length: 11 }, (_unused, index) => ({
      id: `asset-manual-limit-${index + 1}`,
      asset_type: 'network_device',
      asset_tag: `NET-MANUAL-LIMIT-${index + 1}`,
      hostname: `switch-limit-${index + 1}`,
      management_ip: `192.0.2.${90 + index}`,
      status: 'active',
      lifecycle_status: 'production',
      tags: [],
    }));
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: assets, total: assets.length });
      if (url === '/api/assets/summary') return assetSummary(11, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets/batch-snmp-sync' && init?.method === 'POST') {
        return response({
          requested: assets.length,
          synced: assets.length,
          partial: 0,
          failed: 0,
          skipped: 0,
          results: assets.map(asset => ({
            asset_id: asset.id,
            hostname: asset.hostname,
            management_ip: asset.management_ip,
            status: 'synced',
            message: '已同步',
            hostname_sync: { status: 'synced', hostname: asset.hostname, error: '' },
            detected_model: 'H3C S6850',
            synced_model: 'H3C S6850',
            model_source: 'entity_mib',
            rack_sync: { status: 'synced', message: '机柜型号已同步' },
          })),
        });
      }
      return response({});
    });

    renderAssetPage();
    await screen.findByText('switch-limit-11');
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Retry name/model sync' }));

    expect(await screen.findByText(/11 synced/)).toBeTruthy();
    const requests = vi.mocked(fetch).mock.calls.filter(([input, init]) =>
      String(input) === '/api/assets/batch-snmp-sync' && init?.method === 'POST',
    );
    expect(requests).toHaveLength(1);
    expect(requests[0][1]?.body).toBe(JSON.stringify({ asset_ids: assets.map(asset => asset.id) }));
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
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[0]);
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

  it('shows structured asset validation details and redacts entered credentials', async () => {
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [], total: 0 });
      if (url === '/api/assets/summary') return assetSummary(0, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets') {
        return response({
          success: false,
          error: {
            code: 'VALIDATION_ERROR',
            message: 'normal_password: synthetic-test-password does not match policy',
            details: { errors: [] },
          },
        }, 422);
      }
      return response({});
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[0]);
    fireEvent.change(screen.getByRole('textbox', { name: 'Hostname' }), { target: { value: 'validation-test-asset' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set synthetic secret' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('normal_password: [已隐藏] does not match policy');
    expect(alert.textContent).not.toContain('synthetic-test-password');
  });

  it('shows the specific backend detail instead of its generic validation summary', async () => {
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/assets?')) return response({ items: [], total: 0 });
      if (url === '/api/assets/summary') return assetSummary(0, 0);
      if (url === '/api/cmdb/sites') return response({ data: [] });
      if (url === '/api/racks') return response({ success: true, data: [] });
      if (url === '/api/tags/definitions') return response({ data: [] });
      if (url === '/api/assets') {
        return response({
          success: false,
          error: { code: 'VALIDATION_ERROR', message: '保存校验失败，请检查填写内容。' },
          detail: '设备口令上手状态为“待设置凭据”，请先保存凭据并验证连通性。',
        }, 422);
      }
      return response({});
    });

    renderAssetPage();
    await screen.findByText('No asset records');
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[0]);
    fireEvent.change(screen.getByRole('textbox', { name: 'Hostname' }), { target: { value: 'validation-detail-asset' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('设备口令上手状态为“待设置凭据”');
    expect(alert.textContent).not.toContain('保存校验失败，请检查填写内容。');
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
