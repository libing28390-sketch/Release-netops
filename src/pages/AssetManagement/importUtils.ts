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
export const REMOTE_DESKTOP_PROFILE_SHEET_RE = /^(远程桌面|远程桌面配置|remote[ _-]?desktop([ _-]?(profiles?|configuration))?)$/i;
// Backward-compatible export for older callers and imported workbooks.
export const MANAGEMENT_METHOD_SHEET_RE = MANAGEMENT_ENTRY_SHEET_RE;

export type AssetSheetType = 'network_device' | 'server';

export type RemoteDesktopProfileImportRow = {
  rowNumber: number;
  assetTag: string;
  hostname: string;
  protocol: 'rdp' | 'vnc';
  profileName: string;
  enabled: boolean;
  port: number | null;
  normalCredentialId: string;
  adminCredentialId: string;
  rdpDomain: string;
  rdpSecurityMode: 'any' | 'nla' | 'tls' | 'rdp';
  rdpCertFingerprint: string;
  clipboardEnabled: boolean;
};

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

const REMOTE_DESKTOP_HEADER_ALIASES: Record<keyof Omit<RemoteDesktopProfileImportRow, 'rowNumber' | 'enabled' | 'clipboardEnabled' | 'port' | 'protocol' | 'rdpSecurityMode'>, string[]> = {
  assetTag: ['资产编号 *', '资产编号（关联键）', '资产编号', 'Asset Tag *', 'Asset Tag (link key)', 'Asset Tag', 'asset_tag'],
  hostname: ['主机名 *', '主机名（关联键）', '主机名', 'Hostname *', 'Hostname (link key)', 'Hostname', 'hostname'],
  profileName: ['配置名称', '入口名称', 'Profile Name', 'Entry Name', 'Name'],
  // Preserve older workbooks that explicitly overrode remote desktop credentials.
  normalCredentialId: ['远程桌面普通凭据 ID（可选覆盖）', '绑定普通凭据 ID', '绑定普通凭据ID（可留空继承资产）', '普通凭据 ID', '普通凭据ID', '普通凭据（ID）', 'Remote Desktop Normal Credential ID (optional override)', 'Normal Credential ID', 'Credential ID'],
  adminCredentialId: ['远程桌面管理员凭据 ID（可选覆盖）', '绑定管理员凭据 ID', '绑定管理员凭据ID（可选）', '管理员凭据 ID', '管理员凭据ID', '管理员凭据（ID）', 'Remote Desktop Admin Credential ID (optional override)', 'Admin Credential ID', 'Admin Credential'],
  rdpDomain: ['RDP 域（可选）', 'RDP 域', 'RDP域', 'RDP Domain', 'Domain'],
  rdpCertFingerprint: ['RDP 证书 SHA-256 指纹（可选）', 'RDP 证书 SHA-256 指纹', 'RDP证书指纹', 'RDP Certificate SHA-256 Fingerprint', 'Certificate Fingerprint'],
};

const REMOTE_DESKTOP_SCALAR_HEADERS: Record<'protocol' | 'enabled' | 'port' | 'rdpSecurityMode' | 'clipboardEnabled', string[]> = {
  protocol: ['远程桌面协议 *', '远程桌面协议（RDP/VNC）', '远程桌面协议', '协议', 'Protocol *', 'Protocol (RDP/VNC)', 'Remote Desktop Protocol *', 'Remote Desktop Protocol', 'Protocol'],
  enabled: ['是否启用', '启用', 'Enabled'],
  port: ['端口（可留空用默认值）', '端口（可留空）', '端口', 'Port (blank = default)', 'Port'],
  rdpSecurityMode: ['RDP 安全模式（可留空默认 NLA）', 'RDP 安全模式', 'RDP安全模式', 'RDP Security Mode (blank = NLA)', 'RDP Security Mode'],
  clipboardEnabled: ['允许剪贴板', '是否允许剪贴板', '剪贴板启用', 'Clipboard Enabled', 'Allow Clipboard'],
};

const remoteDesktopCellValue = (
  row: Record<string, unknown>,
  aliases: string[],
): string => {
  const header = aliases.find(candidate => Object.prototype.hasOwnProperty.call(row, candidate));
  return header ? String(row[header] ?? '').trim() : '';
};

const normalizeRemoteDesktopProtocol = (value: string): 'rdp' | 'vnc' | null => {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'rdp' || normalized === '远程桌面（rdp）') return 'rdp';
  if (normalized === 'vnc' || normalized === '虚拟网络计算（vnc）') return 'vnc';
  return null;
};

const normalizeRdpSecurityMode = (value: string): RemoteDesktopProfileImportRow['rdpSecurityMode'] | null => {
  const normalized = value.trim().toLowerCase();
  if (!normalized || normalized === 'nla') return 'nla';
  if (normalized === 'any' || normalized === '自动') return 'any';
  if (normalized === 'tls') return 'tls';
  if (normalized === 'rdp') return 'rdp';
  return null;
};

const normalizeOptionalBoolean = (value: string): boolean => {
  if (!value) return false;
  return !['0', 'false', 'no', 'n', '否', '禁用', '关闭'].includes(value.trim().toLowerCase());
};

export function parseRemoteDesktopProfileSheet(
  worksheet: XLSX.WorkSheet,
): { rows: RemoteDesktopProfileImportRow[]; errors: string[] } {
  const rawRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(worksheet, { defval: '' });
  const rows: RemoteDesktopProfileImportRow[] = [];
  const errors: string[] = [];

  rawRows.forEach((raw, index) => {
    const rowNumber = index + 2;
    const assetTag = remoteDesktopCellValue(raw, REMOTE_DESKTOP_HEADER_ALIASES.assetTag);
    const hostname = remoteDesktopCellValue(raw, REMOTE_DESKTOP_HEADER_ALIASES.hostname);
    const protocolValue = remoteDesktopCellValue(raw, REMOTE_DESKTOP_SCALAR_HEADERS.protocol);
    if (!assetTag && !hostname && !protocolValue) return;
    if (!assetTag && !hostname) {
      errors.push(`远程桌面第 ${rowNumber} 行：资产编号和主机名至少填写一项`);
      return;
    }
    const protocol = normalizeRemoteDesktopProtocol(protocolValue);
    if (!protocol) {
      errors.push(`远程桌面第 ${rowNumber} 行：协议必须填写 RDP 或 VNC`);
      return;
    }

    const portValue = remoteDesktopCellValue(raw, REMOTE_DESKTOP_SCALAR_HEADERS.port);
    const port = portValue ? Number(portValue) : null;
    if (port !== null && (!Number.isInteger(port) || port < 1 || port > 65535)) {
      errors.push(`远程桌面第 ${rowNumber} 行：端口必须是 1 到 65535 的整数`);
      return;
    }
    const rdpSecurityMode = normalizeRdpSecurityMode(
      remoteDesktopCellValue(raw, REMOTE_DESKTOP_SCALAR_HEADERS.rdpSecurityMode),
    );
    if (!rdpSecurityMode) {
      errors.push(`远程桌面第 ${rowNumber} 行：RDP 安全模式必须是 any、nla、tls 或 rdp`);
      return;
    }
    const rdpCertFingerprint = remoteDesktopCellValue(raw, REMOTE_DESKTOP_HEADER_ALIASES.rdpCertFingerprint).replace(/\s+/g, '').toUpperCase();
    if (protocol === 'rdp' && rdpCertFingerprint && !/^[0-9A-F]{64}$/.test(rdpCertFingerprint)) {
      errors.push(`远程桌面第 ${rowNumber} 行：RDP 证书指纹必须是 64 位十六进制 SHA-256 值`);
      return;
    }

    rows.push({
      rowNumber,
      assetTag,
      hostname,
      protocol,
      profileName: remoteDesktopCellValue(raw, REMOTE_DESKTOP_HEADER_ALIASES.profileName),
      enabled: normalizeEnabled(remoteDesktopCellValue(raw, REMOTE_DESKTOP_SCALAR_HEADERS.enabled)),
      port,
      normalCredentialId: remoteDesktopCellValue(raw, REMOTE_DESKTOP_HEADER_ALIASES.normalCredentialId),
      adminCredentialId: remoteDesktopCellValue(raw, REMOTE_DESKTOP_HEADER_ALIASES.adminCredentialId),
      rdpDomain: remoteDesktopCellValue(raw, REMOTE_DESKTOP_HEADER_ALIASES.rdpDomain),
      rdpSecurityMode,
      rdpCertFingerprint: protocol === 'rdp' ? rdpCertFingerprint : '',
      clipboardEnabled: normalizeOptionalBoolean(remoteDesktopCellValue(raw, REMOTE_DESKTOP_SCALAR_HEADERS.clipboardEnabled)),
    });
  });

  return { rows, errors };
}

export function mergeRemoteDesktopProfiles(
  assets: Record<string, any>[],
  profiles: RemoteDesktopProfileImportRow[],
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

  const grouped = new Map<Record<string, any>, RemoteDesktopProfileImportRow[]>();
  profiles.forEach(profile => {
    const asset = (profile.assetTag && byAssetTag.get(profile.assetTag.toLowerCase()))
      || (profile.hostname && byHostname.get(profile.hostname.toLowerCase()));
    if (!asset) {
      errors.push(`远程桌面第 ${profile.rowNumber} 行：找不到对应资产 ${profile.assetTag || profile.hostname}`);
      return;
    }
    const existing = grouped.get(asset) || [];
    if (existing.some(item => item.protocol === profile.protocol)) {
      errors.push(`${asset.asset_tag || asset.hostname}：远程桌面配置中存在重复的 ${profile.protocol.toUpperCase()} 行`);
      return;
    }
    existing.push(profile);
    grouped.set(asset, existing);
  });

  grouped.forEach((assetProfiles, asset) => {
    asset.remote_desktop_profiles = assetProfiles.map(profile => ({
      protocol: profile.protocol,
      profile_name: profile.profileName,
      enabled: profile.enabled,
      port: profile.port,
      normal_credential_id: profile.normalCredentialId || null,
      admin_credential_id: profile.adminCredentialId || null,
      rdp_domain: profile.rdpDomain,
      rdp_security_mode: profile.rdpSecurityMode,
      rdp_cert_fingerprint: profile.rdpCertFingerprint,
      clipboard_enabled: profile.clipboardEnabled,
    }));
  });

  return { assets, errors };
}

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

export type AssetImportFeedback = {
  text: string;
  details?: string[];
};

const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const stringValue = (value: unknown): string => (
  typeof value === 'string' ? value.trim() : String(value ?? '').trim()
);

const safeSiteLabel = (value: unknown, zh: boolean): string => {
  const raw = stringValue(value);
  if (!raw) {
    return zh ? '未提供' : 'not provided';
  }
  if (['site-default', 'default_site', 'default site'].includes(raw.toLowerCase())) {
    return zh ? '系统默认站点' : 'system default site';
  }
  return raw.replace(/\bsite-default\b|\bdefault_site\b/gi, zh ? '系统默认站点' : 'system default site');
};

/**
 * Convert the structured import error contract into a localized toast model.
 * Keep this tolerant of older deployments that returned a string or omitted
 * the reason fields, while never rendering internal site identifiers.
 */
export const formatAssetImportError = (detail: unknown, language: string): AssetImportFeedback => {
  const zh = language === 'zh';
  const root = isRecord(detail) ? detail : {};
  const nested = isRecord(root.details) ? root.details : {};
  const source = stringValue(nested.reason) ? nested : root;
  const rawMessage = typeof root.message === 'string'
    ? root.message
    : typeof detail === 'string'
      ? detail
      : '';
  const reason = stringValue(source.reason);
  const looksReserved = reason === 'reserved_system_site'
    || /system default site|site-default|default_site/i.test(rawMessage);
  const row = Number(source.row);
  const rowLabelZh = Number.isInteger(row) && row > 0 ? `第 ${row} 条` : '';
  const rowLabelEn = Number.isInteger(row) && row > 0 ? `item ${row}` : '';
  const assetLabel = stringValue(source.asset_label);
  const siteLabel = safeSiteLabel(source.site_label, zh);

  if (looksReserved) {
    const subjectZh = assetLabel ? `资产“${assetLabel}”` : '该资产';
    const subjectEn = assetLabel ? `asset “${assetLabel}”` : 'this asset';
    return {
      text: zh
        ? `导入失败${rowLabelZh ? `：${rowLabelZh}` : ''}${subjectZh}的站点“${siteLabel}”是系统保留站点，不能作为业务资产归属。`
        : `Import failed${rowLabelEn ? ` (${rowLabelEn})` : ''}: the site “${siteLabel}” for ${subjectEn} is reserved and cannot be assigned to a business asset.`,
      details: [zh
        ? '请在 CMDB 站点管理中选择实际业务站点；如果资产暂时没有站点，请清空“站点/数据中心”列。'
        : 'Choose a real CMDB site, or clear the Site/Datacenter column when the asset is not assigned to a site.'],
    };
  }

  if (reason === 'unknown_site') {
    const subjectZh = assetLabel ? `资产“${assetLabel}”` : '该资产';
    const subjectEn = assetLabel ? `asset “${assetLabel}”` : 'this asset';
    return {
      text: zh
        ? `导入失败${rowLabelZh ? `：${rowLabelZh}` : ''}${subjectZh}的站点“${siteLabel}”未在 CMDB 中找到。`
        : `Import failed${rowLabelEn ? ` (${rowLabelEn})` : ''}: the site “${siteLabel}” for ${subjectEn} was not found in CMDB.`,
      details: [zh
        ? '请填写已存在的站点 ID、编码或名称；如果资产暂时没有站点，请清空“站点/数据中心”列。'
        : 'Enter an existing site ID, code or name, or clear the Site/Datacenter column when the asset is not assigned to a site.'],
    };
  }

  const fallback = rawMessage.replace(/\bsite-default\b|\bdefault_site\b/gi, zh ? '系统默认站点' : 'system default site');
  return { text: fallback || (zh ? '资产导入失败，请检查导入数据后重试。' : 'Asset import failed. Check the import data and try again.') };
};
