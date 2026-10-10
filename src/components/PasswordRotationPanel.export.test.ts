import { describe, expect, it } from 'vitest';
import { readExplicitTableData } from './ui/TableExportMenu';
import { buildPasswordRotationExportData, type RotationExportGroup } from './PasswordRotationPanel.export';

describe('password rotation table export', () => {
  it('splits device and role details into matching columns and never exports passwords or internal IDs', () => {
    const group = {
      credentialName: 'Production network account',
      credentialId: 'credential-db-id',
      isCredential: true,
      devices: [
        { id: 'asset-db-id-1', hostname: 'core-sw-01', ip_address: '192.168.18.201', platform: 'cisco_ios' },
        { id: 'asset-db-id-2', hostname: 'core-sw-02', ip_address: '192.168.18.202', platform: 'cisco_ios' },
      ],
      accounts: [
        { roleKey: 'normal', currentUsername: 'netops', currentDays: 6, currentExpired: false, currentLastRotated: '2026-09-01', currentExpiresAt: '2026-10-01', password: 'normal-secret', id: 'asset-db-id-1' },
        { roleKey: 'normal', currentUsername: 'netops', currentDays: 6, currentExpired: false, currentLastRotated: '2026-09-01', currentExpiresAt: '2026-10-01', password: 'normal-secret', id: 'asset-db-id-2' },
        { roleKey: 'admin', currentUsername: 'admin', currentDays: null, currentExpired: false, currentLastRotated: null, currentExpiresAt: null, password: 'admin-secret', id: 'asset-db-id-1' },
      ],
    } as unknown as RotationExportGroup;

    const explicit = readExplicitTableData(buildPasswordRotationExportData([group], true));
    expect(explicit.headers).toEqual([
      '凭据名称', '设备名称', '设备数量', '管理 IP', '平台',
      '普通账号用户名', '普通账号设备数', '普通账号状态', '普通账号最近轮换', '普通账号到期时间',
      '特权账号用户名', '特权账号设备数', '特权账号状态', '特权账号最近轮换', '特权账号到期时间',
      '提权账号用户名', '提权账号设备数', '提权账号状态', '提权账号最近轮换', '提权账号到期时间',
    ]);
    expect(explicit.rows).toHaveLength(1);
    expect(explicit.rows[0].slice(0, 7)).toEqual([
      'Production network account', 'core-sw-01, core-sw-02', '2', '192.168.18.201, 192.168.18.202', 'Cisco IOS', 'netops', '2',
    ]);
    expect(explicit.headers).not.toContain('Actions');
    expect(JSON.stringify(explicit)).not.toMatch(/normal-secret|admin-secret|credential-db-id|asset-db-id/);
  });

  it('exports every filtered credential group rather than limiting to the visible page', () => {
    const groups = Array.from({ length: 31 }, (_, index) => ({
      credentialName: `credential-${index}`,
      isCredential: true,
      accounts: [],
      devices: [{ id: `internal-${index}`, hostname: `switch-${index}`, ip_address: `192.0.2.${index + 1}`, platform: 'cisco_nxos' }],
    }));
    const data = buildPasswordRotationExportData(groups, false);
    expect(data.rows).toHaveLength(31);
    expect(data.rows.at(-1)?.[1]).toBe('switch-30');
  });
});
