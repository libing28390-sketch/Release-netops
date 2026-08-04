import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ParserRegistryTab from './ParserRegistryTab';

const template = {
  id: 'template-1',
  platform_code: 'cisco_ios',
  template_code: 'CISCO_IOS_SHOW_INTERFACES_STATUS',
  name: 'Cisco status',
  source: 'SYSTEM',
  status: 'ACTIVE',
};

const version = {
  id: 'version-1',
  version_number: 1,
  status: 'PUBLISHED',
  content: 'Value FIELD (.*)\n\nStart\n  ^${FIELD} -> Record\n',
  lock_version: 1,
  field_contract_json: '{}',
  test_summary_json: '{}',
};

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: () => null },
  json: async () => body,
});

interface FetchOptions {
  writeEnabled?: boolean;
  sandboxStatus?: number;
  templates?: unknown[];
  versions?: unknown[];
  samples?: unknown[];
  impact?: unknown;
  failVersionsFor?: string;
  profiles?: unknown[];
}

const installFetchMock = ({
  writeEnabled = true,
  sandboxStatus = 200,
  templates = [template],
  versions = [version],
  samples = [],
  impact = {},
  failVersionsFor = '',
  profiles = [],
}: FetchOptions = {}) => {
  let currentSamples = [...samples];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.includes('/api/parser-templates/capabilities')) {
      return jsonResponse({ success: true, data: { write_enabled: writeEnabled, read_only_sandbox_enabled: true } });
    }
    if (url.endsWith('/api/platform-registry/profiles')) {
      return jsonResponse({ success: true, data: profiles });
    }
    if (url.includes('/api/parser-templates?')) {
      return jsonResponse({ success: true, data: templates, meta: { total: templates.length, page: 1, page_size: 50, pages: 1 } });
    }
    if (/\/api\/parser-templates\/[^/]+$/.test(url) && method === 'PUT') {
      return jsonResponse({ success: true, data: { ...template, lock_version: 2 } });
    }
    if (/\/api\/parser-templates\/[^/]+$/.test(url) && method === 'DELETE') {
      return jsonResponse({ success: true, data: { deleted: true } });
    }
    if (url.endsWith('/versions')) {
      if (failVersionsFor && url.includes(failVersionsFor)) {
        return jsonResponse({ detail: { code: 'VERSION_LOAD_FAILED', message: 'Version unavailable' } }, 503);
      }
      return jsonResponse({ success: true, data: versions });
    }
    if (url.includes('/samples')) {
      if (method === 'DELETE') currentSamples = [];
      return jsonResponse({ success: true, data: currentSamples });
    }
    if (url.includes('/impact') || url.includes('/audit')) {
      return jsonResponse({ success: true, data: url.includes('/impact') ? impact : [] });
    }
    if (url.includes('/sandbox-test')) {
      return sandboxStatus === 200
        ? jsonResponse({
            success: true,
            data: {
              version_id: version.id,
              records: [{ FIELD: 'connected' }],
              fields: ['FIELD'],
              count: 1,
              summary: { fields: ['FIELD'], duration_ms: 4 },
            },
          })
        : jsonResponse({ detail: { code: 'TEMPLATE_NOT_MATCHED', message: 'Parser template failed' } }, sandboxStatus);
    }
    if (url === '/api/parser-templates' && method === 'POST') {
      return jsonResponse({ success: true, data: { id: 'created-template', platform_code: 'cisco_ios', platform_profile_id: 'profile-1', template_code: 'CUSTOM_TEMPLATE', name: 'Custom template', source: 'CUSTOM', status: 'ACTIVE' } }, 201);
    }
    if (url.includes('/versions') && method === 'POST') {
      return jsonResponse({ success: true, data: { ...version, id: 'created-version', status: 'DRAFT' } }, 201);
    }
    return jsonResponse({ success: true, data: [] });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

describe('ParserRegistryTab', () => {
  beforeEach(() => {
    installFetchMock();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders SYSTEM read-only affordances and shows a structured Sandbox result', async () => {
    vi.unstubAllGlobals();
    installFetchMock({ profiles: [{ id: 'profile-1', platform_code: 'cisco_ios', parser_platform: 'cisco_ios', name_zh: 'Cisco IOS', name_en: 'Cisco IOS' }] });
    const user = userEvent.setup();
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Administrator' }} />);

    expect(await screen.findByTestId('parser-template-CISCO_IOS_SHOW_INTERFACES_STATUS')).toBeTruthy();
    expect(screen.getByText('Cisco status')).toBeTruthy();
    expect(screen.getAllByText('CISCO_IOS_SHOW_INTERFACES_STATUS').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('option', { name: '系统' })).toBeTruthy();
    expect(screen.getByRole('option', { name: '自定义' })).toBeTruthy();
    const sandboxButton = screen.getByTestId('parser-sandbox-test') as HTMLButtonElement;
    expect(sandboxButton.disabled).toBe(true);
    expect(screen.getByTestId('parser-sandbox-hint').textContent).toContain('请先填写测试回显');
    expect((screen.getByPlaceholderText('parser_platform') as HTMLInputElement).readOnly).toBe(true);
    expect((screen.getByPlaceholderText('parser_platform') as HTMLInputElement).className).toContain('bg-slate-100');
    await waitFor(() => expect(screen.getByRole('option', { name: /Cisco IOS/ })).toBeTruthy());
    expect(screen.getByTestId('parser-copy-help')).toBeTruthy();
    expect(screen.getByTestId('parser-command-help')).toBeTruthy();
    expect(screen.getByTestId('parser-field-guide')).toBeTruthy();
    await user.click(screen.getByTestId('parser-manual-button'));
    expect(await screen.findByTestId('parser-registration-manual')).toBeTruthy();
    await user.click(screen.getByTitle('关闭注册手册'));
    const forkButton = screen.getByRole('button', { name: '复制为租户模板' }) as HTMLButtonElement;
    expect(forkButton.disabled).toBe(false);
    await user.click(forkButton);
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByRole('textbox', { name: '租户模板编码' })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: '租户模板名称' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '取消' }));

    const sample = screen.getByRole('textbox', { name: /测试回显（Sandbox\/加密样例）/ });
    await user.type(sample, 'Port connected');
    expect(sandboxButton.disabled).toBe(false);
    await user.click(sandboxButton);

    expect(await screen.findByText('解析结果 · 1 条记录')).toBeTruthy();
    expect(screen.getByText('Sandbox 解析通过，共 1 条记录')).toBeTruthy();
    expect(screen.getByText('字段: FIELD · 耗时: 4 ms')).toBeTruthy();
  });

  it('shows a safe failure banner when Sandbox parsing rejects the sample', async () => {
    vi.unstubAllGlobals();
    installFetchMock({ sandboxStatus: 422 });
    const user = userEvent.setup();
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Administrator' }} />);

    await screen.findByTestId('parser-template-CISCO_IOS_SHOW_INTERFACES_STATUS');
    await user.type(screen.getByRole('textbox', { name: /测试回显（Sandbox\/加密样例）/ }), 'not matched');
    await user.click(screen.getByTestId('parser-sandbox-test'));

    expect(await screen.findByText(/Parser template failed/)).toBeTruthy();
    expect(screen.queryByText(/解析结果/)).toBeNull();
  });

  it('does not leave the previous template content visible when the next version request fails', async () => {
    vi.unstubAllGlobals();
    const secondTemplate = {
      ...template,
      id: 'template-2',
      platform_code: 'huawei_vrp',
      template_code: 'HUAWEI_ETH_TRUNK',
      name: 'Huawei Eth-Trunk',
    };
    installFetchMock({ templates: [template, secondTemplate], failVersionsFor: 'template-2' });
    const user = userEvent.setup();
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Administrator' }} />);

    expect(await screen.findByTestId('parser-template-CISCO_IOS_SHOW_INTERFACES_STATUS')).toBeTruthy();
    const editor = screen.getByRole('textbox', { name: 'TextFSM 模板内容' }) as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toContain('Value FIELD'));
    await user.click(screen.getByTestId('parser-template-HUAWEI_ETH_TRUNK'));

    await waitFor(() => expect(editor.value).toBe(''));
    expect(await screen.findByText('Version unavailable')).toBeTruthy();
  });

  it('keeps the SYSTEM read-only Sandbox while hiding write controls when the gate is off', async () => {
    vi.unstubAllGlobals();
    installFetchMock({ writeEnabled: false });
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Administrator' }} />);

    expect(await screen.findByText('当前为只读审查模式：仅允许 SYSTEM（系统）模板只读 Sandbox，不会保存版本或样例。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '新建' })).toBeNull();
    expect(screen.queryByRole('button', { name: '复制为租户模板' })).toBeNull();
    expect((screen.getByTestId('parser-upload-sample') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId('parser-sandbox-test') as HTMLButtonElement).disabled).toBe(true);
  });

  it('requires a platform profile and sends its canonical parser platform for a new template', async () => {
    vi.unstubAllGlobals();
    const fetchMock = installFetchMock({
      templates: [],
      profiles: [{ id: 'profile-1', platform_code: 'acme_lab', parser_platform: 'cisco_ios', name_zh: '测试平台', name_en: 'Test platform', vendor: 'Acme' }],
    });
    const user = userEvent.setup();
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Administrator' }} />);

    await waitFor(() => expect(screen.getByRole('option', { name: /测试平台/ })).toBeTruthy());
    await user.click(await screen.findByTestId('parser-new-template'));
    await user.clear(screen.getByPlaceholderText('TEMPLATE_CODE'));
    await user.type(screen.getByPlaceholderText('TEMPLATE_CODE'), 'CUSTOM_CLOCK');
    await user.click(screen.getByRole('button', { name: '保存草稿' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/parser-templates',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"platform_profile_id":"profile-1"'),
      }),
    ));
    expect(fetchMock.mock.calls.some(([input, init]) => String(input) === '/api/parser-templates' && String(init?.body).includes('"platform_code":"cisco_ios"'))).toBe(true);
  });

  it.each([
    ['Template Developer', true, false],
    ['Release Manager', false, true],
    ['Viewer', false, false],
  ])('applies %s role-profile controls', async (roleProfile, canWrite, canReview) => {
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Operator', role_profile: roleProfile }} />);
    await screen.findByTestId('parser-template-CISCO_IOS_SHOW_INTERFACES_STATUS');
    expect(Boolean(screen.queryByRole('button', { name: '新建' }))).toBe(canWrite);
    if (canReview) {
      expect(await screen.findByText('系统版本为只读，不能废弃或回滚；如需修改或替换，请先复制为租户副本。')).toBeTruthy();
      expect(screen.queryByRole('button', { name: '废弃' })).toBeNull();
    } else {
      expect(screen.queryByRole('button', { name: '废弃' })).toBeNull();
    }
  });

  it('covers tenant draft metadata, persistent Sandbox, samples and lifecycle affordances', async () => {
    const user = userEvent.setup();
    const tenantTemplate = {
      ...template,
      id: 'tenant-template-1',
      source: 'CUSTOM',
      template_code: 'TENANT_STATUS',
      name: 'Tenant status',
    };
    const draftVersion = {
      ...version,
      id: 'tenant-version-2',
      version_number: 2,
      status: 'DRAFT',
      content: 'Value FIELD (.*)\n\nStart\n  ^${FIELD} -> Record\n',
      test_summary_json: '{"fields":["FIELD"]}',
    };
    const publishedVersion = {
      ...version,
      id: 'tenant-version-1',
      version_number: 1,
      status: 'PUBLISHED',
      content: 'Value OLD (.*)\n\nStart\n  ^${OLD} -> Record\n',
      test_summary_json: '{"fields":["OLD"]}',
    };
    installFetchMock({
      templates: [tenantTemplate],
      versions: [draftVersion, publishedVersion],
      samples: [{ id: 'sample-1', sample_name: 'baseline', created_at: '2026-08-04T00:00:00Z' }],
      impact: { action_count: 2, release_count: 1, profile_count: 1, device_count: 3, playbook_count: 1, version_count: 2 },
    });
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Operator' }} />);

    expect(await screen.findByText('Diff · v1 → 当前编辑内容')).toBeTruthy();
    expect(screen.getByText(/Actions:/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '保存修改' })).toBeTruthy();
    expect(screen.getByTestId('parser-delete-template')).toBeTruthy();
    expect(screen.getByRole('button', { name: '历史回归' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '提交审核' })).toBeTruthy();
    expect(await screen.findByTitle('删除样例')).toBeTruthy();

    await user.type(screen.getByRole('textbox', { name: /测试回显（Sandbox\/加密样例）/ }), 'Port connected');
    await user.click(screen.getByTestId('parser-sandbox-test'));
    expect(await screen.findByText('Sandbox 解析通过，共 1 条记录')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '上传加密样例' }));
    expect(await screen.findByText('样例已加密保存')).toBeTruthy();
    await user.click(screen.getByTitle('删除样例'));
    expect(await screen.findByText('样例已删除')).toBeTruthy();
  });

  it('saves draft identity changes and confirms tenant template deletion', async () => {
    vi.unstubAllGlobals();
    const tenantTemplate = {
      ...template,
      id: 'tenant-template-delete',
      source: 'FORKED',
      template_code: 'TENANT_DELETE_ME',
      name: 'Delete me',
      lock_version: 1,
    };
    const draftVersion = { ...version, id: 'tenant-delete-version', status: 'DRAFT' };
    const fetchMock = installFetchMock({ templates: [tenantTemplate], versions: [draftVersion] });
    const user = userEvent.setup();
    render(<ParserRegistryTab language="zh" currentUser={{ role: 'Operator' }} />);

    await screen.findByTestId('parser-template-TENANT_DELETE_ME');
    await user.click(await screen.findByRole('button', { name: '保存修改' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/api/parser-templates/tenant-template-delete') && init?.method === 'PUT')).toBe(true));

    await user.click(screen.getByTestId('parser-delete-template'));
    expect(await screen.findByRole('dialog')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/api/parser-templates/tenant-template-delete') && init?.method === 'DELETE')).toBe(true));
  });
});
