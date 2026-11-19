import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../types';
import TopologyUplinkGroups, { buildTopologyUplinkGrouping } from './TopologyUplinkGroups';

vi.mock('../hooks/useTopologyIcons', () => ({
  useTopologyIcons: () => ({ customIconUrl: () => undefined }),
}));

afterEach(cleanup);

const device = (id: string, role: string, hostname = id): Device => ({
  id,
  hostname,
  ip_address: `192.0.2.${id.length}`,
  platform: 'test',
  status: 'online',
  compliance: 'unknown',
  sn: '',
  model: '',
  version: '',
  role,
  site: 'test',
  uptime: '',
  connection_method: 'none',
  config_history: [],
});

const physicalLink = (
  source_device_id: string,
  target_device_id: string,
  source_port = '',
  target_port = '',
) => ({
  source_device_id,
  target_device_id,
  source_port,
  target_port,
  relation_type: 'PHYSICAL',
  inferred: false,
});

describe('TopologyUplinkGroups', () => {
  it('shows a single access device directly while retaining both physical uplinks', () => {
    const devices = [
      device('dist-b', 'distribution', '汇聚二'),
      device('access-1', 'access', '接入一'),
      device('dist-a', 'distribution', '汇聚一'),
    ];
    const links = [
      physicalLink('access-1', 'dist-b'),
      physicalLink('dist-a', 'access-1'),
      { ...physicalLink('access-1', 'dist-b'), id: 'inferred', relation_type: 'HIERARCHICAL', inferred: true },
    ];

    const grouping = buildTopologyUplinkGrouping(devices, links);

    expect(grouping.accessGroups).toHaveLength(1);
    expect(grouping.accessGroups[0].parents.map((parent) => parent.id)).toEqual(['dist-a', 'dist-b']);
    expect(grouping.accessGroups[0].devices.map((item) => item.id)).toEqual(['access-1']);

    const onNodeClick = vi.fn();
    const { container } = render(<TopologyUplinkGroups devices={devices} links={links} language="zh" onNodeClick={onNodeClick} />);
    const group = container.querySelector<HTMLElement>('[data-uplink-group]')!;
    expect(group.textContent).toContain('2 路上联');
    expect(group.textContent).not.toMatch(/汇聚一|汇聚二/);
    expect(group.querySelector('[aria-expanded]')).toBeNull();
    fireEvent.click(within(group).getByRole('button', { name: '接入一' }));
    expect(onNodeClick).toHaveBeenCalledWith(devices[1]);
  });

  it('expands a multi-device access group by its member count', () => {
    const devices = [
      device('dist-a', 'distribution', '汇聚一'),
      device('access-1', 'access', '接入一'),
      device('access-2', 'access', '接入二'),
    ];
    const links = [physicalLink('dist-a', 'access-1'), physicalLink('dist-a', 'access-2')];
    render(<TopologyUplinkGroups devices={devices} links={links} language="zh" selectedNodeId="dist-a" onNodeClick={vi.fn()} />);
    const group = screen.getByRole('button', { name: '2 台接入设备' });
    expect(group.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(group);
    expect(screen.getByRole('button', { name: '接入一' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '接入二' })).toBeTruthy();
  });

  it('keeps inferred-only relationships under uplink pending and lists APs by wired parent', () => {
    const devices = [
      device('access-1', 'access', '接入一'),
      device('ap-1', 'wireless_ap', 'AP 一'),
      device('wlc-1', 'wireless_controller', '控制器一'),
      device('access-2', 'access', '接入二'),
    ];
    const links = [
      { ...physicalLink('access-2', 'access-1'), relation_type: 'HIERARCHICAL', inferred: true },
      { ...physicalLink('access-2', 'access-1'), inferred: true },
      physicalLink('ap-1', 'access-1', 'GigabitEthernet0/0/8', 'GigabitEthernet0/0/18'),
    ];

    const grouping = buildTopologyUplinkGrouping(devices, links);
    expect(grouping.inferredLinkCount).toBe(1);
    expect(grouping.accessGroups.find((group) => group.parents.length === 0)?.devices).toHaveLength(2);

    render(<TopologyUplinkGroups devices={devices} links={links} language="zh" onNodeClick={vi.fn()} />);

    expect(screen.getAllByText('上联待确认').length).toBeGreaterThan(0);
    expect(screen.getByRole('region', { name: '无线控制器' }).textContent).toContain('控制器一');
    const apGroup = screen.getByRole('button', { name: /接入一 · 1 AP/ });
    fireEvent.click(apGroup);
    expect(screen.getByRole('button', { name: /AP 一/ })).toBeTruthy();
    const pending = grouping.accessGroups.find((group) => group.parents.length === 0);
    expect(pending?.devices.map((item) => item.id)).toEqual(['access-1', 'access-2']);
  });

  it('shows selected-device parent ports and routes device clicks to production selection', () => {
    const switchDevice = device('access-1', 'access', '接入一');
    const ap = device('ap-1', 'wireless_ap', 'AP 一');
    const onNodeClick = vi.fn();

    render(
      <TopologyUplinkGroups
        devices={[switchDevice, ap]}
        links={[physicalLink('ap-1', 'access-1', 'GigabitEthernet0/0/8', 'Ten-GigabitEthernet1/0/1')]}
        language="zh"
        selectedNodeId="ap-1"
        onNodeClick={onNodeClick}
      />,
    );

    expect(screen.getByRole('region', { name: '选中设备上联详情' }).textContent).toContain('GigabitEthernet0/0/8 ↔ Ten-GigabitEthernet1/0/1');
    const selectedParent = screen.getByRole('region', { name: '选中设备上联详情' });
    const parentButton = within(selectedParent).getByRole('button', { name: /接入一/ });
    expect(parentButton.getAttribute('data-uplink-parent')).toBe('true');
    fireEvent.click(parentButton);
    expect(onNodeClick).toHaveBeenCalledWith(switchDevice);
  });
});
