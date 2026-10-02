import type { TableExportData } from './ui/TableExportMenu';

export interface RotationExportAccount {
  roleKey: 'normal' | 'admin' | 'enable';
  currentUsername?: string;
  currentDays?: number | null;
  currentExpired?: boolean;
  currentLastRotated?: string | null;
  currentExpiresAt?: string | null;
}

export interface RotationExportDevice {
  id: string;
  hostname?: string;
  ip_address?: string;
  platform?: string;
}

export interface RotationExportGroup {
  credentialName: string;
  isCredential: boolean;
  accounts: RotationExportAccount[];
  devices: RotationExportDevice[];
}

export const rotationExportHeaders = (zh: boolean) => [
  zh ? '凭据名称' : 'Credential name',
  zh ? '设备名称' : 'Device names',
  zh ? '设备数量' : 'Device count',
  zh ? '管理 IP' : 'Management IPs',
  zh ? '平台' : 'Platforms',
  zh ? '普通账号用户名' : 'Normal username',
  zh ? '普通账号设备数' : 'Normal account devices',
  zh ? '普通账号状态' : 'Normal status',
  zh ? '普通账号最近轮换' : 'Normal last rotated',
  zh ? '普通账号到期时间' : 'Normal expiration',
  zh ? '特权账号用户名' : 'Privileged username',
  zh ? '特权账号设备数' : 'Privileged account devices',
  zh ? '特权账号状态' : 'Privileged status',
  zh ? '特权账号最近轮换' : 'Privileged last rotated',
  zh ? '特权账号到期时间' : 'Privileged expiration',
  zh ? '提权账号用户名' : 'Enable username',
  zh ? '提权账号设备数' : 'Enable account devices',
  zh ? '提权账号状态' : 'Enable status',
  zh ? '提权账号最近轮换' : 'Enable last rotated',
  zh ? '提权账号到期时间' : 'Enable expiration',
];

const platformLabel = (platform: string) => {
  const labels: Record<string, string> = {
    cisco_ios: 'Cisco IOS', cisco_nxos: 'Cisco NX-OS', cisco_xe: 'Cisco IOS-XE',
    huawei_vrp: 'Huawei VRP', h3c_comware: 'H3C Comware', h3c_comware_v3: 'H3C Comware V3',
    arista_eos: 'Arista EOS', juniper_junos: 'Juniper JunOS',
    linux: 'Linux', ubuntu: 'Ubuntu', centos: 'CentOS', debian: 'Debian', esxi: 'VMware ESXi',
  };
  return labels[platform] || platform || '-';
};

const uniqueValues = (values: Array<string | undefined | null>) => Array.from(new Set(
  values.map(value => String(value || '').trim()).filter(Boolean),
));

const dateLabel = (value: string | null | undefined, zh: boolean) => {
  if (!value) return zh ? '未曾轮换' : 'Never rotated';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString(zh ? 'zh-CN' : 'en-US');
};

const expirationLabel = (value: string | null | undefined, zh: boolean) => {
  if (!value) return zh ? '到期时间待定' : 'Pending';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString(zh ? 'zh-CN' : 'en-US');
};

const statusLabel = (account: RotationExportAccount | undefined) => {
  if (!account) return '—';
  if (!account.currentExpiresAt) return '—';
  if (account.currentExpired) return 'EXP';
  return account.currentDays == null ? '—' : `${account.currentDays}d`;
};

export function buildRotationExportRow(group: RotationExportGroup, zh: boolean): string[] {
  const roleOrder: RotationExportAccount['roleKey'][] = ['normal', 'admin', 'enable'];
  const row = [
    group.isCredential ? (group.credentialName || (zh ? '已绑定凭据' : 'Bound credential')) : '—',
    uniqueValues(group.devices.map(device => device.hostname)).join(', ') || '—',
    String(group.devices.length),
    uniqueValues(group.devices.map(device => device.ip_address)).join(', ') || '—',
    uniqueValues(group.devices.map(device => platformLabel(String(device.platform || '')))).join(', ') || '—',
  ];

  roleOrder.forEach(role => {
    const roleAccounts = group.accounts.filter(account => account.roleKey === role);
    const account = roleAccounts[0];
    const isServer = group.devices.length > 0 && group.devices.every(device => {
      const platform = String(device.platform || '').toLowerCase();
      return ['linux', 'ubuntu', 'centos', 'server', 'debian'].some(value => platform.includes(value));
    });
    if (!account) {
      row.push(role === 'enable' && isServer ? 'N/A' : '—', '—', '—', '—', '—');
      return;
    }
    row.push(
      account.currentUsername || '—',
      roleAccounts.length > 1 ? String(roleAccounts.length) : '—',
      statusLabel(account),
      dateLabel(account?.currentLastRotated, zh),
      expirationLabel(account?.currentExpiresAt, zh),
    );
  });

  return row;
}

export function buildPasswordRotationExportData(groups: RotationExportGroup[], zh: boolean): TableExportData {
  return {
    headers: rotationExportHeaders(zh),
    rows: groups.map(group => buildRotationExportRow(group, zh)),
  };
}
