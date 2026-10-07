import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

    expect(await screen.findByRole('option', { name: 'Beijing DC (BJ-1)' })).toBeTruthy();
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
