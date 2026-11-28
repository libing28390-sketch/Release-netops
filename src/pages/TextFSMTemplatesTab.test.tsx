import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import TextFSMTemplatesTab from './TextFSMTemplatesTab';

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const builtinTemplate = {
  filename: 'cisco_ios_show_version.textfsm',
  platform: 'cisco_ios',
  platform_family: 'cisco_ios',
  vendor: 'cisco',
  version: 'common',
  command: 'show version',
  source: 'builtin',
  action_code: 'get_version',
};

const actionOptions = [
  {
    action_code: 'get_version',
    name_zh: '版本信息',
    name_en: 'Version information',
    command: 'show version',
    group_zh: '系统状态监控',
    group_en: 'System status monitoring',
    available: true,
  },
  {
    action_code: 'get_interfaces',
    name_zh: '接口信息',
    name_en: 'Interface information',
    command: 'show interfaces',
    group_zh: '基础网络查询',
    group_en: 'Basic network queries',
    available: true,
  },
];

const operatorPermissions = { can_create: true, can_edit: true, can_test: true, can_delete: false };

describe('TextFSMTemplatesTab', () => {
  let fetchMock: Mock<(input: RequestInfo | URL, init?: RequestInit) => Promise<ReturnType<typeof jsonResponse>>>;

  beforeEach(() => {
    fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || 'GET';
      if (url.startsWith('/api/textfsm/templates?')) {
        return jsonResponse({
          success: true,
          data: { total: 1, items: [builtinTemplate], page: 1, page_size: 20, permissions: operatorPermissions },
          message: '',
        });
      }
      if (url === `/api/textfsm/templates/${builtinTemplate.filename}`) {
        if (method === 'PUT') {
          return jsonResponse({
            success: true,
            data: { ...builtinTemplate, source: 'custom' },
            message: '模板已更新',
          });
        }
        return jsonResponse({
          success: true,
          data: {
            ...builtinTemplate,
            content: 'Value VERSION (\\S+)\\n\\nStart\\n  ^Version: \\${VERSION} -> Record\\n',
            default_sample: '',
            content_hash: 'builtin-content-hash',
            source: 'builtin',
          },
          message: '',
        });
      }
      if (url.startsWith('/api/textfsm/action-options?')) {
        return jsonResponse({ success: true, data: actionOptions, message: '' });
      }
      return jsonResponse({ success: true, data: {}, message: '' });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('hides template changes and test controls when the API grants view-only access', async () => {
    const customTemplate = { ...builtinTemplate, filename: 'cisco_ios_custom.textfsm', source: 'custom' as const };
    fetchMock.mockImplementation(async (input) => {
      if (String(input).startsWith('/api/textfsm/templates?')) {
        return jsonResponse({
          success: true,
          data: {
            total: 1,
            items: [customTemplate],
            permissions: { can_create: false, can_edit: false, can_test: false, can_delete: false },
          },
        });
      }
      return jsonResponse({ success: true, data: {} });
    });

    render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);

    await screen.findByText(customTemplate.filename);
    expect(screen.queryByRole('button', { name: '新建' })).toBeNull();
    expect(screen.queryByTitle('编辑')).toBeNull();
    expect(screen.queryByTitle('编辑并创建自定义覆盖')).toBeNull();
    expect(screen.queryByTitle('删除')).toBeNull();
  });

  it('opens built-in templates as editable copy-on-write overrides', async () => {
    const { container } = render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);

    await screen.findByText(builtinTemplate.filename);
    expect(screen.getByTitle('编辑并创建自定义覆盖')).toBeTruthy();

    await screen.getByTitle('编辑并创建自定义覆盖').click();
    expect(await screen.findByRole('heading', { name: /^编辑模板/ })).toBeTruthy();
    expect(screen.getByText('这是内置模板。保存后会在持久化数据目录创建同名的自定义覆盖，不会修改镜像中的内置版本。')).toBeTruthy();

    const editor = Array.from(container.querySelectorAll('textarea')).find((element) => !element.placeholder);
    expect(editor).toBeTruthy();
    expect((editor as HTMLTextAreaElement).readOnly).toBe(false);

    fireEvent.change(editor as HTMLTextAreaElement, {
      target: { value: 'Value VERSION (\\S+)\\n\\nStart\\n  ^Version: \\${VERSION} -> Record\\n' },
    });
    await screen.getByRole('button', { name: '保存模板' }).click();

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => (
        String(input) === `/api/textfsm/templates/${builtinTemplate.filename}`
        && init?.method === 'PUT'
        && JSON.parse(String(init.body)).content.includes('Value VERSION')
        && JSON.parse(String(init.body)).expected_hash === 'builtin-content-hash'
        && JSON.parse(String(init.body)).expected_source === 'builtin'
      ))).toBe(true);
    });
  });

  it('ignores an older template list response when a newer filter has loaded', async () => {
    const slowTemplate = { ...builtinTemplate, filename: 'cisco_ios_slow.textfsm' };
    const fastTemplate = { ...builtinTemplate, filename: 'cisco_ios_fast.textfsm' };
    const defaultFetch = fetchMock.getMockImplementation();
    let resolveSlow!: (response: ReturnType<typeof jsonResponse>) => void;
    const slowResponse = new Promise<ReturnType<typeof jsonResponse>>((resolve) => { resolveSlow = resolve; });

    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/textfsm/templates?')) {
        const query = new URL(url, 'http://localhost').searchParams.get('search');
        if (query === 'slow') return slowResponse;
        if (query === 'fast') {
          return jsonResponse({ success: true, data: { total: 1, items: [fastTemplate], permissions: operatorPermissions } });
        }
      }
      return defaultFetch ? defaultFetch(input, init) : jsonResponse({ success: true, data: {} });
    });

    render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);
    await screen.findByText(builtinTemplate.filename);
    const search = screen.getByRole('searchbox');
    fireEvent.change(search, { target: { value: 'slow' } });
    fireEvent.change(search, { target: { value: 'fast' } });

    await screen.findByText(fastTemplate.filename);
    resolveSlow(jsonResponse({ success: true, data: { total: 1, items: [slowTemplate], permissions: operatorPermissions } }));

    await waitFor(() => {
      expect(screen.getByText(fastTemplate.filename)).toBeTruthy();
      expect(screen.queryByText(slowTemplate.filename)).toBeNull();
    });
  });

  it('ignores an older detail response when another template was opened later', async () => {
    const customTemplate = {
      ...builtinTemplate,
      filename: 'cisco_ios_show_interfaces.textfsm',
      command: 'show interfaces',
      source: 'custom' as const,
    };
    const defaultFetch = fetchMock.getMockImplementation();
    let resolveOld!: (response: ReturnType<typeof jsonResponse>) => void;
    const oldResponse = new Promise<ReturnType<typeof jsonResponse>>((resolve) => { resolveOld = resolve; });

    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith('/api/textfsm/templates?')) {
        return jsonResponse({ success: true, data: { total: 2, items: [builtinTemplate, customTemplate], permissions: operatorPermissions } });
      }
      if (url === `/api/textfsm/templates/${builtinTemplate.filename}`) return oldResponse;
      if (url === `/api/textfsm/templates/${customTemplate.filename}`) {
        return jsonResponse({
          success: true,
          data: { ...customTemplate, content: 'new template', content_hash: 'custom-hash', source: 'custom' },
        });
      }
      return defaultFetch ? defaultFetch(input, init) : jsonResponse({ success: true, data: {} });
    });

    render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);
    await screen.findByText(customTemplate.filename);
    fireEvent.click(screen.getByTitle('编辑并创建自定义覆盖'));
    fireEvent.click(screen.getByTitle('编辑'));

    expect(await screen.findByRole('heading', { name: /show_interfaces/ })).toBeTruthy();
    resolveOld(jsonResponse({
      success: true,
      data: { ...builtinTemplate, content: 'old template', content_hash: 'old-hash', source: 'builtin' },
    }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /show_interfaces/ })).toBeTruthy();
      expect(screen.queryByRole('heading', { name: /show_version/ })).toBeNull();
    });
  });

  it('invalidates a pending test preview when the template content changes', async () => {
    const defaultFetch = fetchMock.getMockImplementation();
    let resolveTest!: (response: ReturnType<typeof jsonResponse>) => void;
    const pendingTest = new Promise<ReturnType<typeof jsonResponse>>((resolve) => { resolveTest = resolve; });
    fetchMock.mockImplementation((input, init) => (
      String(input) === '/api/textfsm/test'
        ? pendingTest
        : defaultFetch?.(input, init) || Promise.resolve(jsonResponse({ success: true, data: {} }))
    ));

    const { container } = render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);
    await screen.findByText(builtinTemplate.filename);
    fireEvent.click(screen.getByTitle('编辑并创建自定义覆盖'));
    await screen.findByRole('heading', { name: /^编辑模板/ });

    fireEvent.change(screen.getByPlaceholderText('粘贴设备真实 CLI 输出...'), { target: { value: 'sample output' } });
    fireEvent.click(screen.getByRole('button', { name: '测试解析' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/textfsm/test')).toBe(true));

    const editor = Array.from(container.querySelectorAll('textarea')).find((element) => !element.placeholder) as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: 'changed template' } });
    resolveTest(jsonResponse({
      success: true,
      data: { count: 1, fields: ['RESULT'], records: [{ RESULT: 'STALE_RECORD' }] },
    }));

    await waitFor(() => {
      expect(screen.queryByText(/STALE_RECORD/)).toBeNull();
      expect(screen.getByText('粘贴样本输出后点击"测试解析"')).toBeTruthy();
    });
  });

  it('shows an object-shaped API conflict detail as a readable toast', async () => {
    const defaultFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input, init) => {
      if (String(input) === `/api/textfsm/templates/${builtinTemplate.filename}` && init?.method === 'PUT') {
        return Promise.resolve(jsonResponse({ success: false, detail: { message: '模板版本已变化，请重新打开' } }, 409));
      }
      return defaultFetch?.(input, init) || Promise.resolve(jsonResponse({ success: true, data: {} }));
    });

    render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);
    await screen.findByText(builtinTemplate.filename);
    fireEvent.click(screen.getByTitle('编辑并创建自定义覆盖'));
    await screen.findByRole('heading', { name: /^编辑模板/ });
    fireEvent.click(screen.getByRole('button', { name: '保存模板' }));

    expect(await screen.findByText('模板版本已变化，请重新打开')).toBeTruthy();
  });

  it('allows changing the action association while editing an existing template', async () => {
    render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);

    await screen.findByText(builtinTemplate.filename);
    await screen.getByTitle('编辑并创建自定义覆盖').click();

    const actionSelect = await screen.findByRole('combobox', { name: '关联 Action' });
    await screen.findByRole('option', { name: /get_interfaces/ });
    expect((actionSelect as HTMLSelectElement).disabled).toBe(false);
    expect((actionSelect as HTMLSelectElement).value).toBe('get_version');

    fireEvent.change(actionSelect, { target: { value: 'get_interfaces' } });
    expect((actionSelect as HTMLSelectElement).value).toBe('get_interfaces');
    await screen.getByRole('button', { name: '保存模板' }).click();

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input) === `/api/textfsm/templates/${builtinTemplate.filename}`
        && init?.method === 'PUT'
      ));
      expect(saveCall).toBeTruthy();
      expect(JSON.parse(String(saveCall?.[1]?.body)).action_code).toBe('get_interfaces');
    });
  });

  it('keeps the action column width and row controls aligned', async () => {
    render(<TextFSMTemplatesTab t={(key) => key} language="zh" />);

    await screen.findByText(builtinTemplate.filename);
    const table = screen.getByRole('table');
    expect(screen.getByRole('heading', { name: 'TextFSM 解析模板' }).className).toContain('nx-page-title');
    expect(screen.getByText('管理设备 CLI 输出解析模板；内置模板可保存为自定义覆盖').className).toContain('nx-page-subtitle');
    expect(table.className).toContain('nx-data-table');
    const actionHeader = screen.getByRole('columnheader', { name: '操作' });
    const actionCell = table.querySelector('tbody tr td:last-child');

    expect(table.className).toContain('table-fixed');
    expect(table.querySelectorAll('col')).toHaveLength(9);
    expect(screen.getByRole('columnheader', { name: '平台系列' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '平台标识' })).toBeTruthy();
    expect(actionHeader.className).toContain('w-28');
    expect((actionHeader as HTMLElement).style.textAlign).toBe('right');
    expect(actionCell?.className).toContain('w-28');
    expect(actionCell?.firstElementChild?.className).toContain('w-full');
  });
});
