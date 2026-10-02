import type { TableExportData } from '../../components/ui/TableExportMenu';

export interface AccessCenterExportDevice {
  hostname: string;
  ip_address: string;
  status: 'online' | 'offline' | 'pending';
  platform?: string;
  management_port?: number;
  site?: string;
  site_name?: string;
  web_access_enabled?: boolean;
  web_http_enabled?: boolean;
  web_https_enabled?: boolean;
  connection_method?: string;
  vendor?: string;
}

export type AccessCenterExportCategory = 'ALL' | 'SSH' | 'RDP' | 'WEB';

export function buildAccessCenterExportData(
  devices: AccessCenterExportDevice[],
  category: AccessCenterExportCategory,
  isZh: boolean,
): TableExportData {
  const headers = isZh
    ? ['设备名称', '平台', '厂商', '在线状态', '管理 IP', '端口', '站点', ...(category === 'WEB' ? ['HTTP', 'HTTPS'] : category === 'ALL' ? ['SSH', 'RDP', 'HTTP', 'HTTPS'] : ['协议'])]
    : ['Device', 'Platform', 'Vendor', 'Status', 'Management IP', 'Port', 'Site', ...(category === 'WEB' ? ['HTTP', 'HTTPS'] : category === 'ALL' ? ['SSH', 'RDP', 'HTTP', 'HTTPS'] : ['Protocol'])];

  const enabled = (value: boolean | undefined) => value ? (isZh ? '已启用' : 'Enabled') : (isZh ? '未启用' : 'Disabled');
  const rows = devices.map((device) => {
    const protocol = category === 'RDP' ? 'RDP' : category === 'SSH' ? 'SSH' : '';
    const common = [
      device.hostname,
      device.platform || 'General Linux',
      device.vendor || '',
      device.status === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline'),
      device.ip_address,
      device.management_port || 22,
      device.site_name || device.site || (isZh ? '未分配站点' : 'Unassigned site'),
    ];
    if (category === 'WEB') return [...common, enabled(device.web_http_enabled), enabled(device.web_https_enabled)];
    if (category === 'ALL') {
      const methods = device.connection_method === 'web' || device.connection_method === 'none'
        ? []
        : [device.platform?.toLowerCase().includes('windows') ? 'RDP' : 'SSH'];
      return [
        ...common,
        methods.includes('SSH') ? enabled(true) : enabled(false),
        methods.includes('RDP') ? enabled(true) : enabled(false),
        enabled(device.web_http_enabled),
        enabled(device.web_https_enabled),
      ];
    }
    return [...common, protocol];
  });
  return { headers, rows };
}
