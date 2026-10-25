import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
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

const scriptedJob = (enabled = 1) => ({
  id: 'job-1',
  name: 'linux',
  job_type: 'cron',
  action_type: 'script_run',
  cron_expr: '0 * * * *',
  scheduled_at: '',
  device_scope: 'ip',
  device_filter: '192.0.2.10',
  commands: '',
  script_id: 'script-1',
  is_config: 0,
  config_reason: '',
  enabled,
  status: 'approved',
  approved_by: 'lisan',
  approved_at: '2026-10-16T00:00:00Z',
  last_run_at: '',
  last_run_status: '',
  run_count: 0,
  authorization_mode: 'manual',
  created_by: 'admin',
  created_at: '2026-10-15T00:00:00Z',
  updated_by: 'admin',
  updated_at: '2026-10-16T00:00:00Z',
});

const scriptedJobFetch = (job: ReturnType<typeof scriptedJob>) => vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
  const url = new URL(String(input), 'http://localhost');
  if (url.pathname === '/api/scheduled-jobs/system') return jsonResponse([]);
  if (url.pathname === '/api/scheduled-jobs') {
    return jsonResponse({ success: true, data: { items: [job], total: 1 } });
  }
  if (url.pathname === `/api/scheduled-jobs/${job.id}`) {
    return jsonResponse({ success: true, data: job });
  }
  if (url.pathname === '/api/scripts') {
    return jsonResponse({
      success: true,
      data: { items: [{ id: 'script-1', name: 'Linux 综合巡检', content: 'SCRIPT_BODY_MUST_NOT_APPEAR', status: 'released', category: 'inspection' }] },
    });
  }
  if (url.pathname === '/api/config-approval/approvers') {
    return jsonResponse([{ id: 'user-lisan', username: 'lisan', role: 'admin', tenant_id: 't1', verification_methods: ['mfa'] }]);
  }
  if (url.pathname === '/api/devices') {
    return jsonResponse({ success: true, data: { items: [], total: 0 } });
  }
  return jsonResponse({ success: true, data: [] });
});

const RouterLocation = () => {
  const location = useLocation();
  return <output data-testid="router-location">{location.pathname}{location.search}</output>;
};

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

describe('ScheduledJobs user row actions', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  const renderJob = (job = scriptedJob()) => {
    const fetchMock = scriptedJobFetch(job);
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter initialEntries={['/automation/scheduled-jobs']}>
        <ScheduledJobsTab t={(key) => key} language="zh" showToast={vi.fn()} />
        <RouterLocation />
      </MemoryRouter>,
    );
    return fetchMock;
  };

  it('keeps script source out of the job preview and jumps to the matching script by clicking its name', async () => {
    const user = userEvent.setup();
    renderJob();
    await user.click(await screen.findByRole('button', { name: '查看详情' }));

    expect(await screen.findByText('执行方式')).toBeTruthy();
    expect(await screen.findByRole('button', { name: '打开脚本：Linux 综合巡检' })).toBeTruthy();
    expect(screen.queryByText('SCRIPT_BODY_MUST_NOT_APPEAR')).toBeNull();
    expect(screen.queryByRole('button', { name: '查看脚本详情' })).toBeNull();

    await user.click(screen.getByRole('button', { name: '打开脚本：Linux 综合巡检' }));
    expect(screen.getByTestId('router-location').textContent).toBe('/automation/scripts?q=script-1');
  });

  it('opens each available row action without submitting a change', async () => {
    const user = userEvent.setup();
    const fetchMock = renderJob();

    await user.click(await screen.findByRole('button', { name: '查看详情' }));
    expect(await screen.findByRole('heading', { name: 'linux' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '关闭' }));

    await user.click(screen.getByRole('button', { name: '编辑作业' }));
    expect(await screen.findByRole('heading', { name: '编辑定时作业' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '取消' }));

    await user.click(screen.getByRole('button', { name: '停用作业' }));
    expect(await screen.findByRole('heading', { name: '停用作业审批' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '取消' }));

    await user.click(screen.getByRole('button', { name: '删除作业' }));
    await user.click(await screen.findByRole('button', { name: '确认删除' }));
    expect(await screen.findByRole('heading', { name: '删除安全校验与工单授权' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '取消' }));

    const writeRequests = fetchMock.mock.calls.filter(([, init]) => ['POST', 'PUT', 'DELETE'].includes(String((init as RequestInit | undefined)?.method || 'GET').toUpperCase()));
    expect(writeRequests).toHaveLength(0);
  }, 20_000);

  it('opens the enable approval flow for a disabled job without enabling it', async () => {
    const user = userEvent.setup();
    const fetchMock = renderJob(scriptedJob(0));
    await user.click(await screen.findByRole('button', { name: '启用作业' }));

    expect(await screen.findByRole('heading', { name: '启用作业审批' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '取消' }));

    const writeRequests = fetchMock.mock.calls.filter(([, init]) => ['POST', 'PUT', 'DELETE'].includes(String((init as RequestInit | undefined)?.method || 'GET').toUpperCase()));
    expect(writeRequests).toHaveLength(0);
  });
});
