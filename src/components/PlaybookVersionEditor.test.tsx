import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PlaybookVersionEditor from './PlaybookVersionEditor';

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: () => null },
  json: async () => body,
});

describe('PlaybookVersionEditor', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ success: true, data: [] })));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('only exposes declarative step templates and reports malformed JSON locally', async () => {
    const user = userEvent.setup();
    render(<PlaybookVersionEditor language="zh" scenarios={[{ id: 'pb-1', name: 'Interface audit', name_zh: '接口巡检' }]} currentUser={{ role: 'Operator' }} />);
    expect(await screen.findByText('受控 Playbook 版本编辑')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '+ action' }));
    expect((screen.getByRole('textbox', { name: 'Playbook 版本定义 JSON' }) as HTMLTextAreaElement).value).toContain('"type": "action"');
    expect(screen.queryByRole('button', { name: /Python|Shell|原始命令/ })).toBeNull();

    const definition = screen.getByRole('textbox', { name: 'Playbook 版本定义 JSON' });
    await user.clear(definition);
    await user.click(screen.getByRole('button', { name: '+ branch' }));
    expect(await screen.findByText('请先修正 JSON，再添加步骤模板')).toBeTruthy();
  });
});

