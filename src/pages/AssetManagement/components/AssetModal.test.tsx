import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { AssetModal } from './AssetModal';
import { EMPTY_FORM } from '../constants';

const lookupResponse = (url: string, status = 200) => {
  const data = url === '/api/racks'
    ? [{ id: 'rack-1', name: 'A-01', site_id: 'site-1' }]
    : url === '/api/cmdb/sites'
      ? [{ id: 'site-1', site_name: 'Beijing DC', site_code: 'BJ-1' }]
      : [{ id: 'cred-1', credential_name: 'Operations', username: 'operator', credential_type: 'ssh', account_role: 'normal' }];
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: vi.fn().mockResolvedValue(status === 403 ? { detail: 'forbidden' } : { success: true, data }),
  } as unknown as Response;
};

const makeProps = (overrides: Record<string, unknown> = {}) => ({
  isOpen: true,
  onClose: vi.fn(),
  isEditMode: false,
  editingAsset: null,
  form: { ...EMPTY_FORM, hostname: 'asset-01' },
  setForm: vi.fn(),
  saving: false,
  modalError: null,
  setModalError: vi.fn(),
  showEnableSecret: false,
  setShowEnableSecret: vi.fn(),
  showProductionConfirm: false,
  setShowProductionConfirm: vi.fn(),
  handleSave: vi.fn(),
  doSave: vi.fn(),
  language: 'en',
  setFeedbackMsg: vi.fn(),
  allTags: [],
  ...overrides,
}) as any;

describe('AssetModal lookup states', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows the form shell and loading state before lookup options finish, then displays loaded location options', async () => {
    const pending: Array<() => void> = [];
    vi.mocked(fetch).mockImplementation(input => new Promise<Response>((resolve) => {
      const url = String(input);
      pending.push(() => resolve(lookupResponse(url)));
    }));
    render(<AssetModal {...makeProps()} />);

    expect(screen.getByRole('heading', { name: 'Add Asset' })).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('Loading sites, racks, and credential options');

    await act(async () => {
      pending.forEach(resolve => resolve());
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole('button', { name: /More details \(optional\)/ }));
    expect(await screen.findByRole('option', { name: 'Beijing DC' })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /BJ-1/ })).toBeNull();
    expect(document.querySelector('#rack-options option[value="A-01"]')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows permission failure and distinguishes it from successfully empty options', async () => {
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      if (url === '/api/credentials') return lookupResponse(url, 403);
      const emptyResponse = {
        ok: true,
        status: 200,
        headers: new Headers(),
        json: vi.fn().mockResolvedValue({ success: true, data: [] }),
      } as unknown as Response;
      return emptyResponse;
    });
    render(<AssetModal {...makeProps({ language: 'zh' })} />);

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('你没有权限读取以下表单选项：凭据');
    expect(screen.getByRole('status').textContent).toContain('没有可用的机柜、站点选项');
    expect(screen.queryByText('没有可用的凭据选项。')).toBeNull();
  });

  it('keeps Enable Secret Cisco-only and collapses optional asset details by default', async () => {
    vi.mocked(fetch).mockImplementation(async input => lookupResponse(String(input)));
    const nonCiscoProps = makeProps({
      form: { ...EMPTY_FORM, asset_type: 'network_device', vendor: 'H3C', platform: 'h3c_comware', enable_password: 'stale-secret' },
      showEnableSecret: true,
    });
    render(<AssetModal {...nonCiscoProps} />);

    expect(screen.queryByRole('checkbox', { name: 'Cisco Enable Secret' })).toBeNull();
    expect(screen.queryByText('Serial Number')).toBeNull();
    expect(screen.queryByText('SSH algorithm profile')).toBeNull();
    expect(screen.queryByText('Power (W)')).toBeNull();
    await waitFor(() => expect(nonCiscoProps.setShowEnableSecret).toHaveBeenCalledWith(false));
    const clearEnablePassword = nonCiscoProps.setForm.mock.calls
      .map((call: unknown[]) => call[0])
      .find((update: unknown) => typeof update === 'function') as ((form: typeof EMPTY_FORM & { enable_password: string }) => typeof EMPTY_FORM) | undefined;
    expect(clearEnablePassword?.({ ...EMPTY_FORM, enable_password: 'stale-secret' }).enable_password).toBe('');

    fireEvent.click(screen.getByRole('button', { name: /More details \(optional\)/ }));
    expect(screen.getByText('Serial Number')).toBeTruthy();
    expect(screen.getByText('Power (W)')).toBeTruthy();
  });

  it('shows Enable Secret for Cisco network platforms', async () => {
    vi.mocked(fetch).mockImplementation(async input => lookupResponse(String(input)));
    render(<AssetModal {...makeProps({
      form: { ...EMPTY_FORM, asset_type: 'network_device', vendor: 'Cisco', platform: 'cisco_ios' },
    })} />);

    expect(await screen.findByRole('checkbox', { name: 'Cisco Enable Secret' })).toBeTruthy();
  });

  it('shows Enable Secret when a Cisco network platform is selected even before a vendor is chosen', async () => {
    vi.mocked(fetch).mockImplementation(async input => lookupResponse(String(input)));
    render(<AssetModal {...makeProps({
      form: { ...EMPTY_FORM, asset_type: 'network_device', vendor: '', platform: 'cisco_ios' },
    })} />);

    expect(await screen.findByRole('checkbox', { name: 'Cisco Enable Secret' })).toBeTruthy();
  });

  it('does not imply Cisco is selected before choosing a vendor or platform', async () => {
    vi.mocked(fetch).mockImplementation(async input => lookupResponse(String(input)));
    const StatefulAssetModal = () => {
      const [form, setForm] = useState({ ...EMPTY_FORM, asset_type: 'network_device', vendor: '', platform: '' });
      return <AssetModal {...makeProps({ form, setForm })} />;
    };
    render(<StatefulAssetModal />);

    const platform = screen.getByTitle('Platform') as HTMLSelectElement;
    expect(platform.value).toBe('');
    expect(screen.getByRole('option', { name: 'Choose a vendor or platform…' })).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: 'Cisco Enable Secret' })).toBeNull();

    fireEvent.change(screen.getByTitle('Vendor'), { target: { value: 'Cisco' } });
    await waitFor(() => expect(platform.value).toBe('cisco_ios'));
    expect(await screen.findByRole('checkbox', { name: 'Cisco Enable Secret' })).toBeTruthy();
  });

  it('shows both production paths while keeping them unavailable until onboarding is verified', async () => {
    vi.mocked(fetch).mockImplementation(async input => lookupResponse(String(input)));
    render(<AssetModal {...makeProps({
      isEditMode: true,
      editingAsset: { ...EMPTY_FORM, id: 'asset-ubuntu', asset_origin: 'legacy', lifecycle_status: 'staging', onboarding_status: 'pending_credentials' },
      form: { ...EMPTY_FORM, hostname: 'ubuntu-nexora', lifecycle_status: 'production', asset_origin: 'legacy' },
      showProductionConfirm: true,
      language: 'zh',
    })} />);

    expect(await screen.findByText('口令上收并投产')).toBeTruthy();
    expect(screen.getByText('免上收投产，保留现有口令')).toBeTruthy();
    expect(screen.getByRole('button', { name: '完成凭据保存和连通性验证后可用' })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: '免上收投产（验证通过后启用）' })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: '保存表单并保持待投产' })).toBeTruthy();
  });

  it('guards rapid duplicate submissions while the save request is pending', async () => {
    vi.mocked(fetch).mockImplementation(async input => lookupResponse(String(input)));
    let finishSave!: () => void;
    const handleSave = vi.fn(() => new Promise<void>(resolve => { finishSave = resolve; }));
    render(<AssetModal {...makeProps({ handleSave })} />);
    const saveButton = screen.getAllByRole('button', { name: 'Save' })[0];

    act(() => {
      fireEvent.click(saveButton);
      fireEvent.click(saveButton);
    });
    expect(handleSave).toHaveBeenCalledTimes(1);

    await act(async () => { finishSave(); await waitFor(() => expect(handleSave).toHaveBeenCalledTimes(1)); });
  });
});
