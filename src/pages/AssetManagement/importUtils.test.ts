import { describe, expect, it } from 'vitest';
import * as XLSX from 'xlsx';

import {
  ASSET_INFO_SHEET_RE,
  MANAGEMENT_ENTRY_SHEET_RE,
  mergeManagementMethods,
  parseManagementMethodSheet,
} from './importUtils';

describe('asset management method import', () => {
  it('recognizes the new sheet names and keeps the old management sheet compatible', () => {
    expect(ASSET_INFO_SHEET_RE.test('资产信息')).toBe(true);
    expect(MANAGEMENT_ENTRY_SHEET_RE.test('管理入口')).toBe(true);
    expect(MANAGEMENT_ENTRY_SHEET_RE.test('管理方式')).toBe(true);
    expect(MANAGEMENT_ENTRY_SHEET_RE.test('Management Entries')).toBe(true);
  });

  it('maps SSH-only, Web-only and combined assets without duplicating assets', () => {
    const sheet = XLSX.utils.aoa_to_sheet([
      ['资产编号', '主机名（核对）', '管理方式', '入口名称', '端口', '登录路径', '是否启用'],
      ['A-001', 'a', 'SSH', '命令行管理', 22, '', '是'],
      ['B-001', 'b', 'HTTPS', 'Web管理', 443, '/login', '是'],
      ['C-001', 'c', 'SSH', '命令行管理', 22, '', '是'],
      ['C-001', 'c', 'HTTP', 'HTTP管理', 80, '/', '否'],
      ['C-001', 'c', 'HTTPS', 'HTTPS管理', 443, '/', '是'],
    ]);
    const parsed = parseManagementMethodSheet(sheet);
    expect(parsed.errors).toEqual([]);

    const assets: Record<string, any>[] = [
      { asset_tag: 'A-001', hostname: 'a' },
      { asset_tag: 'B-001', hostname: 'b' },
      { asset_tag: 'C-001', hostname: 'c' },
    ];
    const merged = mergeManagementMethods(assets, parsed.rows);
    expect(merged.errors).toEqual([]);
    expect(merged.assets).toHaveLength(3);
    expect(merged.assets[0]).toMatchObject({ connection_method: 'ssh', management_port: '22', web_profiles: [] });
    expect(merged.assets[1]).toMatchObject({ connection_method: 'web', management_port: 0 });
    expect(merged.assets[1].web_profiles).toHaveLength(1);
    expect(merged.assets[2].connection_method).toBe('ssh');
    expect(merged.assets[2].web_profiles).toHaveLength(2);
    expect(merged.assets[2].web_profiles.find((item: any) => item.scheme === 'http').enabled).toBe(false);
  });

  it('accepts the manual-entry headers used by the downloadable template', () => {
    const sheet = XLSX.utils.aoa_to_sheet([
      ['资产编号（手工填写）', '主机名（手工填写/核对）', '管理协议（每行一个）', '入口显示名称（仅展示）', '端口（可留空自动默认）', '登录路径（Web填写，如 /login）', '是否启用', '凭据模式（默认继承资产）', '普通用户（可选）', '普通密码（不建议填写）', '特权用户（可选）', '特权密码（不建议填写）', '绑定凭据（推荐）', '绑定特权凭据（推荐）'],
      ['WEB-001', 'web-01', 'HTTPS', 'HTTPS管理', 443, '/login', '是', '继承资产凭据', '', '', '', '', 'cred-web', 'cred-web-admin'],
    ]);

    const parsed = parseManagementMethodSheet(sheet);
    expect(parsed.errors).toEqual([]);
    expect(parsed.rows[0]).toMatchObject({
      assetTag: 'WEB-001',
      hostname: 'web-01',
      method: 'https',
      profileName: 'HTTPS管理',
      port: '443',
      path: '/login',
      credentialId: 'cred-web',
      adminCredentialId: 'cred-web-admin',
    });
  });

  it('requires an explicit management entry for every asset in the unified template', () => {
    const assets: Record<string, any>[] = [
      { asset_tag: 'A-001', hostname: 'a' },
      { asset_tag: 'B-001', hostname: 'b' },
    ];
    const merged = mergeManagementMethods(assets, [{
      rowNumber: 2,
      assetTag: 'A-001',
      hostname: 'a',
      method: 'none',
      profileName: '',
      port: '',
      path: '',
      enabled: true,
      credentialMode: 'inherit_asset',
      normalUsername: '',
      normalPassword: '',
      adminUsername: '',
      adminPassword: '',
      credentialId: '',
      adminCredentialId: '',
    }], { requireEntryForAllAssets: true });

    expect(merged.assets[0]).toMatchObject({ connection_method: 'none', management_port: 0 });
    expect(merged.errors).toEqual([
      'B-001：请在“管理入口”中至少配置一行；没有登录入口时填写 NONE',
    ]);
  });
});
