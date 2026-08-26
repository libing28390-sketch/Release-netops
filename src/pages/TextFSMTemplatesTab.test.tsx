import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
  action_code: '',
};

describe('TextFSMTemplatesTab', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || 'GET';
      if (url.startsWith('/api/textfsm/templates?')) {
        return jsonResponse({
          success: true,
          data: { total: 1, items: [builtinTemplate], page: 1, page_size: 20 },
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
          },
          message: '',
        });
      }
      if (url.startsWith('/api/textfsm/action-options?')) {
        return jsonResponse({ success: true, data: [], message: '' });
      }
      return jsonResponse({ success: true, data: {}, message: '' });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
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
      ))).toBe(true);
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
    expect(table.querySelectorAll('col')).toHaveLength(5);
    expect(actionHeader.className).toContain('w-28');
    expect((actionHeader as HTMLElement).style.textAlign).toBe('right');
    expect(actionCell?.className).toContain('w-28');
    expect(actionCell?.firstElementChild?.className).toContain('w-full');
  });
});
