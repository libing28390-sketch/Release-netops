import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ScheduledJobsTab from './index';

const xlsxMocks = vi.hoisted(() => ({
  aoaToSheet: vi.fn((rows: unknown[][]) => ({ rows })),
  bookNew: vi.fn(() => ({ sheets: [] as unknown[] })),
  appendSheet: vi.fn((book: { sheets: unknown[] }, sheet: unknown) => { book.sheets.push(sheet); }),
  writeFile: vi.fn(),
}));

vi.mock('xlsx', () => ({
  utils: {
    aoa_to_sheet: xlsxMocks.aoaToSheet,
    book_new: xlsxMocks.bookNew,
    book_append_sheet: xlsxMocks.appendSheet,
  },
  writeFile: xlsxMocks.writeFile,
}));

const systemJob = (index: number) => ({
  id: `internal-system-job-${index}`,
  name_zh: `备份计划 ${index}`,
  name_en: `Backup Schedule ${index}`,
  description_zh: `自动配置备份 ${index}`,
  description_en: `Automated configuration backup ${index}`,
  category: 'collection',
  action_type: 'backup',
  deep_link: '/config/schedule',
  trigger: `cron[hour='${index % 24}']`,
  next_run_at: null,
});

const jsonResponse = (payload: unknown) => ({
  ok: true,
  status: 200,
  json: async () => payload,
});

describe('ScheduledJobs system schedule exports', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('exports all locally filtered system schedules using visible business columns only', async () => {
    const allSystemJobs = [
      systemJob(1),
      {
        ...systemJob(2),
        name_zh: '凭据轮换扫描',
        description_zh: '每日检查凭据到期状态',
        action_type: 'password_rotation',
      },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/scheduled-jobs/system') {
        return jsonResponse(allSystemJobs);
      }
      if (url.pathname === '/api/scheduled-jobs') {
        return jsonResponse({ success: true, data: { items: [], total: 0 } });
      }
      return jsonResponse({ success: true, data: [] });
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ScheduledJobsTab t={(key) => key} language="zh" showToast={vi.fn()} />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: /系统计划/ }));
    await screen.findByText('备份计划 1');
    await user.type(screen.getByPlaceholderText('按名称、脚本ID或命令搜索...'), '备份');
    await user.click(await screen.findByRole('button', { name: '导出表格' }));
    await user.click(screen.getByRole('menuitem', { name: '导出 Excel (.xlsx)' }));

    await waitFor(() => expect(xlsxMocks.writeFile).toHaveBeenCalledWith(expect.any(Object), 'scheduled-jobs-system.xlsx'));

    const systemRequests = fetchMock.mock.calls
      .map(([input]) => new URL(String(input), 'http://localhost'))
      .filter((url) => url.pathname === '/api/scheduled-jobs/system');
    expect(systemRequests).toHaveLength(1);
    expect(systemRequests[0].search).toBe('');

    const sheetRows = xlsxMocks.aoaToSheet.mock.calls[0][0];
    expect(sheetRows[0]).toEqual(['任务名称', '任务说明', '触发发条 (CRON)', '预计下次执行']);
    expect(sheetRows).toHaveLength(2);
    expect(sheetRows[1]).toEqual(['备份计划 1', '自动配置备份 1', "cron[hour='1']", '']);
    expect(JSON.stringify(sheetRows)).not.toContain('凭据轮换扫描');
    expect(JSON.stringify(sheetRows)).not.toContain('internal-system-job');
    expect(JSON.stringify(sheetRows)).not.toContain('/config/schedule');
  });
});
