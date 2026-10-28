import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import InspectionItemsTab from './InspectionItemsTab';

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const getTableRow = (name: RegExp): HTMLTableRowElement => (
  screen.getByRole('row', { name }) as HTMLTableRowElement
);

const openMetricDetails = async (user: ReturnType<typeof userEvent.setup>, row: HTMLElement) => {
  await user.click(within(row).getByRole('button', { name: '查看指标详情' }));
  return screen.findByRole('dialog');
};

const closeMetricDetails = async (user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) => {
  await user.click(within(dialog).getAllByRole('button', { name: '关闭' })[0]);
};

const fanMetric = {
  id: 'fan-status',
  name: 'Fan status',
  name_zh: '风扇状态',
  category: 'Health',
  check_key: 'hardware_fan',
  description: 'SNMP fan status',
  method: 'SNMP',
  command: '',
  vendor: 'Cisco',
  oid: '1.3.6.1.4.1.9.9.13.1.3',
  parse_type: 'status',
  unit: 'status',
  warning_threshold: null,
  critical_threshold: null,
  created_at: '',
  updated_at: '',
};

const temperatureMetric = {
  id: 'temperature',
  name: 'Temperature',
  name_zh: '设备温度',
  category: 'Health',
  check_key: 'device_temp',
  description: 'Device temperature',
  method: 'SNMP',
  command: '',
  vendor: 'Cisco',
  oid: '1.3.6.1.4.1.9.9.13.1.3.1',
  parse_type: 'numeric',
  unit: '°C',
  warning_threshold: -5,
  critical_threshold: 80,
  created_at: '',
  updated_at: '',
};

const psuMetric = {
  ...fanMetric,
  id: 'psu-status',
  name: 'PSU status',
  name_zh: '电源状态',
  check_key: 'hardware_psu',
};

const latencyMetric = {
  ...temperatureMetric,
  id: 'latency',
  name: 'Latency',
  name_zh: '延迟',
  check_key: 'service_latency',
  unit: 'ms',
  warning_threshold: -1,
  critical_threshold: 50,
};

const countMetric = {
  ...temperatureMetric,
  id: 'route-count',
  name: 'Route count',
  name_zh: '路由数量',
  check_key: 'route_count',
  parse_type: 'count',
  unit: 'count',
  warning_threshold: 5,
  critical_threshold: 20,
};

const syslogCountMetric = {
  ...countMetric,
  id: 'syslog-host-count',
  name: 'Syslog hosts',
  name_zh: '日志主机数',
  check_key: 'syslog_host_count',
  unit: '个日志主机',
  warning_threshold: 1,
  critical_threshold: 2,
  threshold_direction: 'below',
};

const unitlessMetric = {
  ...temperatureMetric,
  id: 'unitless',
  name: 'Unitless metric',
  name_zh: '无单位指标',
  check_key: 'unitless_metric',
  unit: '',
  warning_threshold: 8,
  critical_threshold: 10,
};

const diffMetric = {
  ...unitlessMetric,
  id: 'diff-metric',
  name: 'Change percent',
  name_zh: '变化率',
  check_key: 'change_rate',
  parse_type: 'diff',
  warning_threshold: 10,
  critical_threshold: 20,
};

const facets = {
  all: 94,
  categories: { health: 80, compliance: 14 },
  methods: { SNMP: 58, CLI: 11, ICMP: 1, SHELL: 22, SSH: 1, TCP: 1 },
  vendors: { cisco_ios: 58, huawei_vrp: 36 },
};

const renderPage = () => render(
  <InspectionItemsTab t={(key) => key} language="zh" showToast={vi.fn()} />,
);

describe('InspectionItemsTab', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    window.localStorage.removeItem('netops:inspection-items:columns:v1');
    fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/inspections/items/all') {
        const page = Number(url.searchParams.get('page') || 1);
        const items = page === 1
          ? [fanMetric, psuMetric, temperatureMetric, latencyMetric, countMetric, unitlessMetric, diffMetric]
          : [{ ...temperatureMetric, id: 'temperature-page-2', name_zh: '第二页温度' }];
        return jsonResponse({ success: true, data: { items, total: 94, page, page_size: 10, facets } });
      }
      if (url.pathname === '/api/scripts') return jsonResponse({ data: { items: [], total: 0 } });
      return jsonResponse({ success: true, data: {} });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    window.localStorage.removeItem('netops:inspection-items:columns:v1');
    vi.unstubAllGlobals();
  });

  it('uses full server facets across pages and renders status rules without percent thresholds', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('风扇状态')).toBeTruthy();
    const totalCard = screen.getByText('当前结果总数').parentElement;
    const snmpCard = screen.getByText('SNMP 指标').parentElement;
    const cliSshCard = screen.getByText('CLI / SSH 指标').parentElement;
    const shellCard = screen.getByText('SHELL 指标').parentElement;
    const otherMethodsCard = screen.getByText('其他采集方式').parentElement?.parentElement;
    expect(totalCard?.textContent).toContain('94');
    expect(snmpCard?.textContent).toContain('58');
    expect(cliSshCard?.textContent).toContain('12');
    expect(shellCard?.textContent).toContain('22');
    expect(otherMethodsCard?.textContent).toContain('2');
    expect(otherMethodsCard?.textContent).toContain('ICMP 1 · TCP 1');
    const methodTotal = [snmpCard, cliSshCard, shellCard, otherMethodsCard]
      .reduce((total, card) => total + Number(card?.querySelector('span')?.textContent || 0), 0);
    expect(methodTotal).toBe(94);

    const fanRow = getTableRow(/风扇状态/);
    let details = await openMetricDetails(user, fanRow);
    expect(within(details).getByText(/组件状态码：0=正常，1=告警，2=严重，3=未知\/未采集/)).toBeTruthy();
    expect(within(details).getByText(/状态码 2 或 fail\/failed\/failure 触发严重告警/)).toBeTruthy();
    expect(details.textContent).not.toContain('%');
    await closeMetricDetails(user, details);

    const psuRow = screen.getAllByRole('row')
      .map((row) => row as HTMLTableRowElement)
      .find((row) => row.cells[0]?.textContent?.trim() === '电源状态');
    expect(psuRow).toBeTruthy();
    details = await openMetricDetails(user, psuRow!);
    expect(details.textContent).not.toContain('%');
    await closeMetricDetails(user, details);

    const numericRules: Array<[RegExp, string]> = [
      [/设备温度/, '-5°C时触发告警'],
      [/延迟/, '-1 ms时触发告警'],
      [/路由数量/, '5 个时触发告警'],
      [/无单位指标/, '8 无单位时触发告警'],
      [/变化率/, '10%时触发告警'],
    ];
    for (const [rowPattern, expectedRule] of numericRules) {
      details = await openMetricDetails(user, getTableRow(rowPattern));
      expect(details.textContent).toContain(expectedRule);
      await closeMetricDetails(user, details);
    }

    await user.click(screen.getByTitle('下一页'));
    expect(await screen.findByText('第二页温度')).toBeTruthy();
    expect(screen.getByText('当前结果总数').parentElement?.textContent).toContain('94');
    expect(screen.getByText('SNMP 指标').parentElement?.textContent).toContain('58');
    expect(screen.getByText('CLI / SSH 指标').parentElement?.textContent).toContain('12');
    expect(screen.getByText('SHELL 指标').parentElement?.textContent).toContain('22');
    expect(screen.getByText('其他采集方式').parentElement?.parentElement?.textContent).toContain('2');
  }, 15_000);

  it('keeps raw vendor options from server facets across pages and filters by raw vendor', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/inspections/items/all') {
        const page = Number(url.searchParams.get('page') || 1);
        const vendor = page === 1 ? 'cisco_ios' : 'huawei_vrp';
        return jsonResponse({
          success: true,
          data: { items: [{ ...fanMetric, id: `fan-${page}`, vendor }], total: 94, page, page_size: 10, facets },
        });
      }
      if (url.pathname === '/api/scripts') return jsonResponse({ data: { items: [], total: 0 } });
      return jsonResponse({ success: true, data: {} });
    });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('风扇状态');
    const vendorSelect = screen.getByRole('combobox', { name: '适用平台' });
    expect(within(vendorSelect).getByRole('option', { name: 'Cisco' }).getAttribute('value')).toBe('cisco_ios');
    expect(within(vendorSelect).getByRole('option', { name: 'Huawei' }).getAttribute('value')).toBe('huawei_vrp');

    await user.click(screen.getByTitle('下一页'));
    await waitFor(() => expect(screen.getByRole('row', { name: /风扇状态/ }).textContent).toContain('huawei_vrp'));
    expect(within(vendorSelect).getByRole('option', { name: 'Cisco' })).toBeTruthy();
    await user.selectOptions(vendorSelect, 'cisco_ios');

    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([input]) => {
        const url = new URL(String(input), 'http://localhost');
        return url.pathname === '/api/inspections/items/all' && url.searchParams.get('vendor') === 'cisco_ios';
      });
      expect(request).toBeTruthy();
    });
  });

  it('matches category facet keys case-insensitively while keeping the API filter value', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('风扇状态');
    const complianceTab = screen.getByRole('tab', { name: /合规性检查/ });
    expect(complianceTab.textContent).toContain('14');
    await user.click(complianceTab);

    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([input]) => {
        const url = new URL(String(input), 'http://localhost');
        return url.pathname === '/api/inspections/items/all' && url.searchParams.get('category') === 'Compliance';
      });
      expect(request).toBeTruthy();
    });
  });

  it('keeps unit and negative threshold values in the edit payload', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('设备温度')).toBeTruthy();
    const temperatureRow = getTableRow(/设备温度/);
    await user.click(within(temperatureRow).getByRole('button', { name: '编辑指标' }));

    const warningInput = await screen.findByRole('spinbutton', { name: '告警阈值' });
    fireEvent.change(warningInput, { target: { value: '-7' } });
    await user.click(within(screen.getByRole('row', { name: /设备温度/ })).getByRole('button', { name: '保存' }));

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input) === '/api/inspections/items/temperature' && init?.method === 'PUT'
      ));
      expect(saveCall).toBeTruthy();
      const payload = JSON.parse(String(saveCall?.[1]?.body));
      expect(payload.warning_threshold).toBe(-7);
      expect(payload.unit).toBe('°C');
      expect(payload.parse_type).toBe('numeric');
    });
  });

  it('shows and saves expected state values for non-compliance SNMP status items', async () => {
    const metricWithExpected = { ...fanMetric, expected_value: 'ok' };
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/inspections/items/all') {
        return jsonResponse({ success: true, data: { items: [metricWithExpected], total: 1, facets } });
      }
      if (url.pathname === '/api/scripts') return jsonResponse({ data: { items: [], total: 0 } });
      return jsonResponse({ success: true, data: {} });
    });
    const user = userEvent.setup();
    renderPage();

    const fanRow = await screen.findByRole('row', { name: /风扇状态/ }) as HTMLTableRowElement;
    const details = await openMetricDetails(user, fanRow);
    expect(within(details).getByText('ok', { exact: true })).toBeTruthy();
    expect(within(details).getByText(/期望状态“ok”按精确值匹配/)).toBeTruthy();
    expect(within(details).getByText(/状态码 2（故障）或 fail\/failed\/failure 触发严重告警/)).toBeTruthy();
    await closeMetricDetails(user, details);
    await user.click(within(fanRow).getByRole('button', { name: '编辑指标' }));
    const expectedInput = await screen.findByRole('textbox', { name: '期望状态值' });
    expect((expectedInput as HTMLInputElement).value).toBe('ok');
    await user.clear(expectedInput);
    await user.type(expectedInput, 'failed');
    await user.click(within(screen.getByRole('row', { name: /风扇状态/ })).getByRole('button', { name: '保存' }));

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input) === '/api/inspections/items/fan-status' && init?.method === 'PUT'
      ));
      expect(saveCall).toBeTruthy();
      expect(JSON.parse(String(saveCall?.[1]?.body)).expected_value).toBe('failed');
    });
  });

  it('allows setting an expected state when creating any status metric', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: '新建' }));
    await user.selectOptions(screen.getByLabelText('解析类型'), 'status');
    const expectedInput = screen.getByRole('textbox', { name: '期望状态值' });
    expect(expectedInput).toBeTruthy();
    expect((screen.getByLabelText('单位') as HTMLInputElement).value).toBe('status');
    expect((screen.getByLabelText('单位') as HTMLInputElement).disabled).toBe(true);

    await user.type(screen.getByLabelText('英文名称'), 'Link status');
    await user.type(screen.getByLabelText('中文名称'), '链路状态');
    await user.type(screen.getByLabelText('检查 Key'), 'link_status');
    await user.type(expectedInput, 'up');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input) === '/api/inspections/items' && init?.method === 'POST'
      ));
      expect(saveCall).toBeTruthy();
      const payload = JSON.parse(String(saveCall?.[1]?.body));
      expect(payload.parse_type).toBe('status');
      expect(payload.unit).toBe('status');
      expect(payload.expected_value).toBe('up');
    });
  });

  it('keeps custom existing units editable and saves them unchanged unless updated', async () => {
    const metricWithCustomUnit = { ...temperatureMetric, id: 'connection-count', unit: '个连接' };
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/inspections/items/all') {
        return jsonResponse({ success: true, data: { items: [metricWithCustomUnit], total: 1, facets } });
      }
      if (url.pathname === '/api/scripts') return jsonResponse({ data: { items: [], total: 0 } });
      return jsonResponse({ success: true, data: {} });
    });
    const user = userEvent.setup();
    renderPage();

    const row = await screen.findByRole('row', { name: /设备温度/ });
    await user.click(within(row).getByRole('button', { name: '编辑指标' }));
    const unitInput = await screen.findByRole('textbox', { name: '单位' });
    expect((unitInput as HTMLInputElement).value).toBe('个连接');
    await user.clear(unitInput);
    await user.type(unitInput, '个会话');
    await user.click(within(screen.getByRole('row', { name: /设备温度/ })).getByRole('button', { name: '保存' }));

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input) === '/api/inspections/items/connection-count' && init?.method === 'PUT'
      ));
      expect(saveCall).toBeTruthy();
      expect(JSON.parse(String(saveCall?.[1]?.body)).unit).toBe('个会话');
    });
  });

  it('shows and saves below threshold direction with the metric unit', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/inspections/items/all') {
        return jsonResponse({ success: true, data: { items: [syslogCountMetric], total: 1, facets } });
      }
      if (url.pathname === '/api/scripts') return jsonResponse({ data: { items: [], total: 0 } });
      return jsonResponse({ success: true, data: {} });
    });
    const user = userEvent.setup();
    renderPage();

    const row = await screen.findByRole('row', { name: /日志主机数/ }) as HTMLTableRowElement;
    const details = await openMetricDetails(user, row);
    expect(details.textContent).toContain('低于 1 个日志主机时触发告警');
    await closeMetricDetails(user, details);
    await user.click(within(row).getByRole('button', { name: '编辑指标' }));
    const editingRow = screen.getByRole('row', { name: /日志主机数/ });
    const directionSelect = await screen.findByRole('combobox', { name: '阈值比较方式' });
    expect((directionSelect as HTMLSelectElement).value).toBe('below');
    await user.selectOptions(directionSelect, 'above');
    await user.selectOptions(directionSelect, 'below');
    await user.click(within(editingRow).getByRole('button', { name: '保存' }));

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input) === '/api/inspections/items/syslog-host-count' && init?.method === 'PUT'
      ));
      expect(saveCall).toBeTruthy();
      const payload = JSON.parse(String(saveCall?.[1]?.body));
      expect(payload.threshold_direction).toBe('below');
      expect(payload.warning_threshold).toBe(1);
    });
  });

  it('shows permission state and retries a failed list request', async () => {
    let denyFirstRequest = true;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/inspections/items/all') {
        if (denyFirstRequest) {
          denyFirstRequest = false;
          return jsonResponse({ detail: 'forbidden' }, 403);
        }
        return jsonResponse({ success: true, data: { items: [fanMetric], total: 1, facets } });
      }
      if (url.pathname === '/api/scripts') return jsonResponse({ data: { items: [], total: 0 } });
      return jsonResponse({ success: true, data: {} });
    });
    const user = userEvent.setup();
    renderPage();

    const permissionAlert = await screen.findByRole('alert');
    expect(permissionAlert.textContent).toContain('你没有查看巡检指标的权限');
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('风扇状态')).toBeTruthy();
  });

  it('ignores an older filter response after a newer result arrives', async () => {
    let resolveOldResponse: ((value: ReturnType<typeof jsonResponse>) => void) | undefined;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/inspections/items/all') {
        const query = url.searchParams.get('q') || '';
        if (query === 'old') {
          return new Promise((resolve) => { resolveOldResponse = resolve; });
        }
        const item = query === 'new'
          ? { ...temperatureMetric, name: 'new query result', name_zh: '新查询结果' }
          : fanMetric;
        return Promise.resolve(jsonResponse({ success: true, data: { items: [item], total: 1, facets: { ...facets, all: 1 } } }));
      }
      if (url.pathname === '/api/scripts') return Promise.resolve(jsonResponse({ data: { items: [], total: 0 } }));
      return Promise.resolve(jsonResponse({ success: true, data: {} }));
    });
    renderPage();

    expect(await screen.findByText('风扇状态')).toBeTruthy();
    const search = screen.getByPlaceholderText('搜索指标...');
    fireEvent.change(search, { target: { value: 'old' } });
    await waitFor(() => expect(resolveOldResponse).toBeTypeOf('function'));
    fireEvent.change(search, { target: { value: 'new' } });
    expect(await screen.findByText('新查询结果')).toBeTruthy();

    await act(async () => {
      resolveOldResponse?.(jsonResponse({ success: true, data: { items: [{ ...fanMetric, name: 'old query result', name_zh: '旧查询结果' }], total: 1, facets: { ...facets, all: 1 } } }));
    });
    expect(screen.queryByText('旧查询结果')).toBeNull();
    expect(screen.getByText('新查询结果')).toBeTruthy();
  });
});
