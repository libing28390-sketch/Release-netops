import * as XLSX from 'xlsx';

export type ManagementMethodImportRow = {
  rowNumber: number;
  assetTag: string;
  hostname: string;
  method: 'ssh' | 'netconf' | 'web' | 'http' | 'https' | 'none';
  profileName: string;
  port: string;
  path: string;
  enabled: boolean;
  credentialMode: 'inherit_asset' | 'independent';
  normalUsername: string;
  normalPassword: string;
  adminUsername: string;
  adminPassword: string;
  credentialId: string;
  adminCredentialId: string;
};

export const ASSET_INFO_SHEET_RE = /^(资产信息|asset[ _-]?(information|info|inventory|master))$/i;
export const NETWORK_ASSET_SHEET_RE = /^(网络设备|网络设备信息|network[ _-]?(devices?|equipment|assets?))$/i;
export const SERVER_ASSET_SHEET_RE = /^(服务器|服务器信息|servers?|server[ _-]?(information|assets?))$/i;
export const MANAGEMENT_ENTRY_SHEET_RE = /^(管理入口|管理方式|management[ _-]?(entries|entry|methods?)|access[ _-]?entries)$/i;
// Backward-compatible export for older callers and imported workbooks.
export const MANAGEMENT_METHOD_SHEET_RE = MANAGEMENT_ENTRY_SHEET_RE;

export type AssetSheetType = 'network_device' | 'server';

export const assetTypeForSheetName = (name: string): AssetSheetType | null => {
  const normalized = name.trim();
  if (NETWORK_ASSET_SHEET_RE.test(normalized)) return 'network_device';
  if (SERVER_ASSET_SHEET_RE.test(normalized)) return 'server';
  return null;
};

export const normalizeImportHeader = (header: string): string => header.trim().replace(/\s*\*+\s*$/, '').trim();

const HEADER_ALIASES: Record<string, string[]> = {
  assetTag: ['资产编号（手工填写）', '资产编号（关联键）', '资产编号', 'Asset Tag (manual)', 'Asset Tag (link key)', 'Asset Tag', 'asset_tag'],
  hostname: ['主机名（手工填写/核对）', '主机名（自动带出/仅核对）', '主机名（仅核对）', '主机名（核对）', '主机名', 'Hostname (manual/check)', 'Hostname (auto/check)', 'Hostname (check)', 'Hostname', 'hostname'],
  method: ['管理协议（每行一个）', '管理协议（SSH/NETCONF/HTTP/HTTPS/NONE）', '管理协议（SSH/HTTP/HTTPS/NONE）', '管理方式', '协议', 'Management Protocol (one per row)', 'Management Protocol (SSH/NETCONF/HTTP/HTTPS/NONE)', 'Management Protocol (SSH/HTTP/HTTPS/NONE)', 'Management Method', 'Method', 'Protocol'],
  profileName: ['入口显示名称（仅展示）', '登录方式（可不填）', '入口名称', '名称', 'Entry Display Name (label only)', 'Login Method (optional)', 'Entry Name', 'Profile Name', 'Name'],
  port: ['端口（可留空自动默认）', '端口（可留空）', '端口', 'Port (blank = default)', 'Port'],
  path: ['登录路径（Web填写，如 /login）', '登录路径（仅 HTTP/HTTPS）', '登录路径', '路径', 'Login Path (Web only)', 'Login Path (HTTP/HTTPS only)', 'Login Path', 'Path'],
  enabled: ['是否启用', '启用', 'Enabled'],
  credentialMode: ['凭据模式（默认继承资产）', '凭据模式', 'Credential Mode (default: inherit asset)', 'Credential Mode'],
  normalUsername: ['普通用户（可选）', '普通用户', 'Normal User (optional)', 'Normal User', 'normal_username'],
  normalPassword: ['普通密码（不建议填写）', '普通密码', 'Normal Password (avoid)', 'Normal Password', 'normal_password'],
  adminUsername: ['特权用户（可选）', '特权用户', 'Admin User (optional)', 'Admin User', 'admin_username'],
  adminPassword: ['特权密码（不建议填写）', '特权密码', 'Admin Password (avoid)', 'Admin Password', 'admin_password'],
  credentialId: ['绑定凭据（推荐）', '绑定凭据', 'Credential ID (recommended)', 'Credential', 'credential_id'],
  adminCredentialId: ['绑定特权凭据（推荐）', '绑定特权凭据', 'Admin Credential ID (recommended)', 'Admin Credential', 'admin_credential_id'],
};

const cellValue = (row: Record<string, unknown>, field: keyof typeof HEADER_ALIASES): string => {
  const alias = HEADER_ALIASES[field].find(header => Object.prototype.hasOwnProperty.call(row, header));
  return alias ? String(row[alias] ?? '').trim() : '';
};

const normalizeMethod = (value: string): ManagementMethodImportRow['method'] | null => {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'ssh') return 'ssh';
  if (normalized === 'netconf') return 'netconf';
  if (normalized === 'http') return 'http';
  if (normalized === 'https') return 'https';
  if (['web', 'web管理', 'web管理入口', 'web management', 'web only', '仅 web（http/https）', '仅web（http/https）'].includes(normalized)) return 'web';
  if (['none', '无', '不启用'].includes(normalized)) return 'none';
  return null;
};

const normalizeProfileLabel = (value: string): string => value.trim().toLowerCase().replace(/\s+/g, '');

// The entry label is display-only, but it still needs to describe the
// selected protocol. Keep the generic Web label accepted for older files;
// the downloadable template now narrows the Excel list to the matching label.
const MANAGEMENT_PROFILE_LABELS: Record<ManagementMethodImportRow['method'], string[]> = {
  ssh: [
    '命令行管理',
    'ssh终端 + web ssh',
    'ssh终端/web ssh',
    'web ssh',
    'cli management',
    'cli management entry',
    'ssh terminal + web ssh',
  ],
  netconf: ['netconf管理', 'netconf management'],
  web: ['web管理', 'web管理入口', 'web management', 'web management entry'],
  http: ['http管理', 'web管理', 'web管理入口', 'http management', 'web management', 'web management entry'],
  https: ['https管理', 'web管理', 'web管理入口', 'https management', 'web management', 'web management entry'],
  none: ['无登录入口', 'no login entry'],
};

const MANAGEMENT_PROFILE_DEFAULT_LABEL: Record<ManagementMethodImportRow['method'], string> = {
  ssh: '命令行管理',
  netconf: 'NETCONF管理',
  web: 'Web管理',
  http: 'HTTP管理',
  https: 'HTTPS管理',
  none: '无登录入口',
};

const isCompatibleManagementProfile = (
  method: ManagementMethodImportRow['method'],
  profileName: string,
): boolean => {
  if (!profileName) return true;
  const accepted = MANAGEMENT_PROFILE_LABELS[method].map(normalizeProfileLabel);
  return accepted.includes(normalizeProfileLabel(profileName));
};

const normalizeEnabled = (value: string): boolean => {
  if (!value) return true;
  return !['0', 'false', 'no', 'n', '否', '禁用'].includes(value.trim().toLowerCase());
};

const normalizeCredentialMode = (value: string): 'inherit_asset' | 'independent' => {
  const normalized = value.trim().toLowerCase();
  return ['独立凭据', '独立web凭据', 'independent', 'override'].includes(normalized)
    ? 'independent'
    : 'inherit_asset';
};

export function parseManagementMethodSheet(
  worksheet: XLSX.WorkSheet,
): { rows: ManagementMethodImportRow[]; errors: string[] } {
  const rawRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(worksheet, { defval: '' });
  const rows: ManagementMethodImportRow[] = [];
  const errors: string[] = [];

  rawRows.forEach((raw, index) => {
    const rowNumber = index + 2;
    const assetTag = cellValue(raw, 'assetTag');
    const hostname = cellValue(raw, 'hostname');
    const methodValue = cellValue(raw, 'method');
    if (!assetTag && !hostname && !methodValue) return;
    if (!assetTag && !hostname) {
      errors.push(`管理入口第 ${rowNumber} 行：资产编号和主机名至少填写一项`);
      return;
    }
    const method = normalizeMethod(methodValue);
    if (!method) {
      errors.push(`管理入口第 ${rowNumber} 行：不支持的管理方式“${methodValue || '空'}”`);
      return;
    }
    const profileName = cellValue(raw, 'profileName');
    if (!isCompatibleManagementProfile(method, profileName)) {
      errors.push(`管理入口第 ${rowNumber} 行：协议“${methodValue}”的入口显示名称应为“${MANAGEMENT_PROFILE_DEFAULT_LABEL[method]}”，当前为“${profileName}”`);
      return;
    }
    const path = cellValue(raw, 'path');
    if (path && ['ssh', 'netconf', 'none'].includes(method)) {
      errors.push(`管理入口第 ${rowNumber} 行：协议“${methodValue}”不应填写登录路径“${path}”，请留空`);
      return;
    }
    rows.push({
      rowNumber,
      assetTag,
      hostname,
      method,
      profileName,
      port: cellValue(raw, 'port'),
      path,
      enabled: normalizeEnabled(cellValue(raw, 'enabled')),
      credentialMode: normalizeCredentialMode(cellValue(raw, 'credentialMode')),
      normalUsername: cellValue(raw, 'normalUsername'),
      normalPassword: cellValue(raw, 'normalPassword'),
      adminUsername: cellValue(raw, 'adminUsername'),
      adminPassword: cellValue(raw, 'adminPassword'),
      credentialId: cellValue(raw, 'credentialId'),
      adminCredentialId: cellValue(raw, 'adminCredentialId'),
    });
  });

  return { rows, errors };
}

export function mergeManagementMethods(
  assets: Record<string, any>[],
  methods: ManagementMethodImportRow[],
  options: { requireEntryForAllAssets?: boolean } = {},
): { assets: Record<string, any>[]; errors: string[] } {
  const errors: string[] = [];
  const byAssetTag = new Map<string, Record<string, any>>();
  const byHostname = new Map<string, Record<string, any>>();
  assets.forEach(asset => {
    const assetTag = String(asset.asset_tag || '').trim().toLowerCase();
    const hostname = String(asset.hostname || '').trim().toLowerCase();
    if (assetTag) byAssetTag.set(assetTag, asset);
    if (hostname) byHostname.set(hostname, asset);
  });

  const grouped = new Map<Record<string, any>, ManagementMethodImportRow[]>();
  methods.forEach(method => {
    const asset = (method.assetTag && byAssetTag.get(method.assetTag.toLowerCase()))
      || (method.hostname && byHostname.get(method.hostname.toLowerCase()));
    if (!asset) {
      errors.push(`管理入口第 ${method.rowNumber} 行：找不到对应资产 ${method.assetTag || method.hostname}`);
      return;
    }
    const existing = grouped.get(asset) || [];
    existing.push(method);
    grouped.set(asset, existing);
  });

  if (options.requireEntryForAllAssets) {
    assets.forEach(asset => {
      if (!grouped.has(asset)) {
        errors.push(`${asset.asset_tag || asset.hostname || '未命名资产'}：请在“管理入口”中至少配置一行；没有登录入口时填写 NONE`);
      }
    });
  }

  grouped.forEach((assetMethods, asset) => {
    const terminalMethods = assetMethods.filter(item => item.enabled && (item.method === 'ssh' || item.method === 'netconf'));
    if (terminalMethods.length > 1) {
      errors.push(`${asset.asset_tag || asset.hostname}：当前版本只能配置一个 SSH/NETCONF 主通道`);
      return;
    }

    const terminal = terminalMethods[0];
    if (terminal) {
      asset.connection_method = terminal.method;
      asset.management_port = terminal.port || (terminal.method === 'netconf' ? '830' : '22');
      if (terminal.normalUsername) asset.normal_username = terminal.normalUsername;
      if (terminal.normalPassword) asset.normal_password = terminal.normalPassword;
      if (terminal.adminUsername) asset.admin_username = terminal.adminUsername;
      if (terminal.adminPassword) asset.admin_password = terminal.adminPassword;
      if (terminal.credentialId) asset.credential_id = terminal.credentialId;
      if (terminal.adminCredentialId) asset.admin_credential_id = terminal.adminCredentialId;
    } else {
      asset.connection_method = assetMethods.some(item => item.enabled && (item.method === 'web' || item.method === 'http' || item.method === 'https'))
        ? 'web'
        : 'none';
      asset.management_port = 0;
    }

    const webProfiles = assetMethods
      .filter(item => item.method === 'web' || item.method === 'http' || item.method === 'https')
      .map(item => {
        const enteredPort = Number.parseInt(item.port, 10);
        const scheme = item.method === 'web'
          ? (enteredPort === 80 ? 'http' : 'https')
          : item.method;
        return {
          profile_name: item.profileName || (item.method === 'web' ? 'Web管理' : scheme === 'https' ? 'HTTPS管理' : 'HTTP管理'),
          scheme,
          port: enteredPort || (scheme === 'https' ? 443 : 80),
          path: item.path || '/',
          enabled: item.enabled,
          credential_mode: item.credentialMode,
          normal_username: item.normalUsername,
          normal_password: item.normalPassword,
          admin_username: item.adminUsername,
          admin_password: item.adminPassword,
          credential_id: item.credentialId,
          admin_credential_id: item.adminCredentialId,
        };
      });
    const duplicateKeys = new Set<string>();
    for (const profile of webProfiles) {
      const key = `${profile.scheme}:${profile.port}:${profile.path}`;
      if (duplicateKeys.has(key)) {
        errors.push(`${asset.asset_tag || asset.hostname}：存在重复的 Web 管理方式 ${key}`);
      }
      duplicateKeys.add(key);
    }
    asset.web_profiles = webProfiles;
  });

  return { assets, errors };
}
