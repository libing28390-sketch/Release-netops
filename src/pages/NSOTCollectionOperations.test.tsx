import React from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import NSOTCollectionOperations from './NSOTCollectionOperations';

const templates = [{
  id: 'basic',
  name_zh: '基础监控',
  name_en: 'Basic monitoring',
  description_zh: '基础接口状态和接口 IP 事实。',
  description_en: 'Basic interface facts.',
  collector_keys: ['interface_status'],
  builtin: true,
  editable: true,
  deletable: true,
}];

const profiles = [
  {
    id: 'dptech-unknown',
    platform_code: 'dptech_conplat_unknown',
    platform_family: 'dptech_conplat_unknown',
    vendor: '迪普',
    name_zh: '迪普 未知系统',
    status: 'ACTIVE',
  },
  {
    id: 'h3c-v7',
    platform_code: 'h3c_comware_v7',
    platform_family: 'h3c_comware',
    vendor: '华三',
    name_zh: '华三 Comware V7',
    status: 'ACTIVE',
  },
];

const operation = {
  collector_key: 'interface_status',
  label: 'Interface status',
  label_zh: '接口状态与流量',
  label_en: 'Interface status and traffic',
  transport: 'ssh',
  applicable_templates: ['basic'],
  action_code: null,
  action_bound: false,
  commands: [],
};

const installFetch = (availableProfiles = profiles) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    const profileId = url.searchParams.get('platform_profile_id');
    const selectedProfile = availableProfiles.find((profile) => profile.id === profileId) || null;
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          templates,
          profiles: availableProfiles,
          selected_profile: selectedProfile,
          operations: selectedProfile ? [operation] : [],
        },
      }),
    };
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

describe('NSOTCollectionOperations', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('limits the detail profile selector to the row vendor and enables built-in CRUD actions', async () => {
    installFetch();
    const user = userEvent.setup();
    render(<NSOTCollectionOperations language="zh" searchText="" />);

    const row = await screen.findByRole('row', { name: /基础监控.*迪普.*未知系统/ });
    expect(within(row).getByRole('button', { name: '编辑基础监控' }).hasAttribute('disabled')).toBe(false);
    expect(within(row).getByRole('button', { name: '删除基础监控' }).hasAttribute('disabled')).toBe(false);
    expect(screen.getByText('共 2 行')).toBeTruthy();
    expect(screen.getByRole('combobox', { name: '每页条数' })).toBeTruthy();

    await user.click(within(row).getByRole('button', { name: /查看基础监控在迪普/ }));
    const profilePicker = await screen.findByRole('combobox', { name: 'TextFSM 平台 / 版本' });
    const optionLabels = Array.from((profilePicker as HTMLSelectElement).options).map((option) => option.textContent || '');
    expect(optionLabels.some((label) => label.includes('迪普'))).toBe(true);
    expect(optionLabels.some((label) => label.includes('华三'))).toBe(false);
  });

  it('paginates the flattened template and platform rows', async () => {
    installFetch(Array.from({ length: 21 }, (_, index) => ({
      ...profiles[0],
      id: `dptech-profile-${index}`,
    })));
    const user = userEvent.setup();
    render(<NSOTCollectionOperations language="zh" searchText="" />);

    expect(await screen.findByText('共 21 行')).toBeTruthy();
    expect(screen.getAllByRole('row')).toHaveLength(21);
    await user.click(screen.getByTitle('下一页'));
    expect((screen.getByRole('spinbutton', { name: '当前页' }) as HTMLInputElement).value).toBe('2');
    expect(screen.getAllByRole('row')).toHaveLength(2);
  });
});
