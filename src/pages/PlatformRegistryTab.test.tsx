import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PlatformRegistryTab from './PlatformRegistryTab';

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: () => null },
  json: async () => body,
});

const installPlatformFetch = (
  writeEnabled: boolean,
  profiles: unknown[] = [],
  detail: unknown = {},
  actions: unknown[] = [],
  parserVersions: unknown[] = [],
) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/platform-registry/capabilities')) {
      return jsonResponse({ success: true, data: { write_enabled: writeEnabled, allowed_connection_drivers: ['netmiko'], legacy_textfsm_fallback_enabled: false, legacy_command_catalog_enabled: false } });
    }
    if (url.endsWith('/profiles')) return jsonResponse({ success: true, data: profiles });
    if (url.includes('/parser-versions')) return jsonResponse({ success: true, data: parserVersions });
    if (url.includes('/actions')) return jsonResponse({ success: true, data: actions });
    if (url.match(/\/profiles\/[^/]+$/)) return jsonResponse({ success: true, data: detail });
    if (url.includes('/identification-conflicts')) return jsonResponse({ success: true, data: [] });
    return jsonResponse({ success: true, data: {} });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

describe('PlatformRegistryTab', () => {
  beforeEach(() => installPlatformFetch(false));

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders the default read-only state for Viewer', async () => {
    render(<MemoryRouter><PlatformRegistryTab language="zh" currentUser={{ role: 'Viewer' }} /></MemoryRouter>);
    expect(await screen.findByText('平台注册表')).toBeTruthy();
    expect(screen.getByText('当前阶段为只读审查模式')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '新建平台' })).toBeNull();
  });

  it('opens and completes the three-step create wizard for Platform Maintainer', async () => {
    vi.unstubAllGlobals();
    installPlatformFetch(true);
    const user = userEvent.setup();
    render(<MemoryRouter><PlatformRegistryTab language="zh" currentUser={{ role: 'Operator', role_profile: 'Platform Maintainer' }} /></MemoryRouter>);

    await screen.findByText('平台注册表');
    await user.click(screen.getByRole('button', { name: '新建平台' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByText(/连接与解析/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByText(/确认/)).toBeTruthy();
    expect(screen.getByText('自定义 / 启用 / 草稿 Release')).toBeTruthy();
    expect(screen.getAllByRole('option', { name: '系统' }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByRole('option', { name: '自定义' }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('button', { name: '创建平台' })).toBeTruthy();
  });

  it('offers only compatible published parser versions and sends the replacement id', async () => {
    vi.unstubAllGlobals();
    const profile = {
      id: 'profile-1',
      platform_code: 'acme_lab',
      parser_platform: 'cisco_ios',
      name_zh: '测试平台',
      name_en: 'Test platform',
      vendor: 'Acme',
      source: 'CUSTOM',
      status: 'ACTIVE',
      current_release_id: 'release-1',
    };
    const release = { id: 'release-1', profile_id: 'profile-1', release_number: 1, status: 'DRAFT', parser_platform: 'cisco_ios', connection_driver: 'netmiko' };
    const action = { action_code: 'get_clock', name_zh: '获取时钟', name_en: 'Get clock', command: 'show clock', parser_template_version_id: 'version-old', field_contract_json: '{}' };
    const fetchMock = installPlatformFetch(true, [profile], { ...profile, releases: [release], current_release_id: 'release-1' }, [action], [
      { id: 'version-new', template_id: 'template-new', template_code: 'CUSTOM_CLOCK', version_number: 2, status: 'PUBLISHED', source: 'CUSTOM', platform_code: 'cisco_ios', field_contract_json: '{"required":["clock"]}' },
    ]);
    const user = userEvent.setup();
    render(<MemoryRouter><PlatformRegistryTab language="zh" currentUser={{ role: 'Operator' }} /></MemoryRouter>);

    await screen.findByRole('heading', { name: '测试平台' });
    await user.click(screen.getByRole('button', { name: '命令映射' }));
    expect(await screen.findByText('get_clock')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '编辑命令/解析版本' }));
    const parserSelect = screen.getByRole('combobox', { name: '动作 get_clock 的解析版本' }) as HTMLSelectElement;
    expect(parserSelect).toBeTruthy();
    await user.selectOptions(parserSelect, 'version-new');
    expect(screen.getByRole('button', { name: '打开模板' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/platform-registry/releases/release-1/actions/get_clock',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          command: 'show clock',
          parser_template_version_id: 'version-new',
          field_contract: { required: ['clock'] },
        }),
      }),
    ));
  });
});
