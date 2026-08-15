import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Edit2, Trash2, RefreshCw, X, KeyRound, Building2, Network, Layers, Users as UsersIcon, Server, Search, Check, ShieldAlert, Eye, EyeOff, Copy, ChevronDown, ChevronUp, ChevronRight, FolderTree, Download, Upload, FileSpreadsheet } from 'lucide-react';
import * as XLSX from 'xlsx';
import PageHero from '../components/PageHero';
import Pagination from '../components/Pagination';
import { DataTable } from '../components/DataTable';
import { formatMacAddress } from '../utils/resourceFormatters';

/* ────────────────────────────────────────────────────────────
 * CMDB Management — unified CRUD for the foundational CMDB tables:
 *   credentials · devices · interfaces · sites · vrfs · vlans · tenants
 * Consumes the /api/credentials and /api/cmdb/* endpoints.
 * ──────────────────────────────────────────────────────────── */

interface Props {
  language?: string;
  cmdbPage?: string;
  currentUser?: { role?: string };
}

type EntityKey = 'credentials' | 'devices' | 'interfaces' | 'sites' | 'vrfs' | 'vlans' | 'vlan-business' | 'tenants';

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('netops_token') || '';
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

function formatErrorDetail(detail: any): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((err: any) => {
      if (typeof err === 'object' && err?.msg) {
        const field = Array.isArray(err.loc) ? err.loc[err.loc.length - 1] : 'field';
        return `${field}: ${err.msg}`;
      }
      return String(err);
    }).join('; ');
  }
  if (typeof detail === 'object') return JSON.stringify(detail);
  return 'Request failed';
}

function humanizeCredentialError(message: string, zh: boolean): string {
  const value = String(message || '').trim();
  const normalized = value.toLowerCase();
  if (normalized.includes('old_password is incorrect')) {
    return zh ? '当前密码不正确，请确认输入的是凭据中心中保存的旧密码。' : 'The current password is incorrect. Check the old password stored in the credential center.';
  }
  if (normalized.includes('old_enable_password is incorrect')) {
    return zh ? '当前 Enable 密码不正确，请确认输入的是凭据中心中保存的旧 Enable 密码。' : 'The current Enable password is incorrect. Check the old Enable password stored in the credential center.';
  }
  if (normalized.includes('old_password is required')) {
    return zh ? '修改登录密码前必须填写当前密码。' : 'Enter the current password before changing the login password.';
  }
  if (normalized.includes('old_enable_password is required')) {
    return zh ? '修改 Enable 密码前必须填写当前 Enable 密码。' : 'Enter the current Enable password before changing the Enable password.';
  }
  if (normalized.includes('username or account role changes must be submitted separately')) {
    return zh ? '密码修改不能同时修改用户名或账号角色，请先单独保存身份信息，再修改密码。' : 'Save username or account role changes separately before changing the password.';
  }
  return value;
}

async function apiList<T>(url: string): Promise<T[]> {
  const res = await fetch(url, { headers: authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(formatErrorDetail(json.detail || json.message));
  return (json.data || []) as T[];
}

function dedupeSiteRows<T extends Record<string, any>>(rows: T[]): T[] {
  const merged = new Map<string, T>();
  rows.forEach((row) => {
    const code = String(row.site_code || '').trim().toLowerCase();
    const name = String(row.site_name || '').trim().toLowerCase();
    if (!code && !name) return;
    const key = code || name;
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, row);
      return;
    }
    const combined = { ...existing } as T;
    const combinedValues = combined as Record<string, any>;
    Object.keys(row).forEach((field) => {
      if ((combinedValues[field] == null || String(combinedValues[field] || '').trim() === '') && row[field] != null && String(row[field]).trim() !== '') {
        combinedValues[field] = row[field];
      }
    });
    merged.set(key, combined);
  });
  return Array.from(merged.values()).sort((left, right) => String(left.site_name || left.site_code || '').localeCompare(String(right.site_name || right.site_code || '')));
}

async function apiListPage<T>(url: string): Promise<{ items: T[]; total: number; page: number; page_size: number; total_pages: number; summary?: Record<string, number>; site_summary?: Array<{ key: string; label: string; count: number }>; device_options?: Array<{ value: string; label: string }>; tree?: any[] }> {
  const res = await fetch(url, { headers: authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(formatErrorDetail(json.detail || json.message));
  const data = json.data || {};
  return {
    items: Array.isArray(data) ? data : (data.items || []),
    total: Number(data.total || 0),
    page: Number(data.page || 1),
    page_size: Number(data.page_size || 20),
    total_pages: Number(data.total_pages || 1),
    summary: data.summary || {},
    site_summary: Array.isArray(data.site_summary) ? data.site_summary : [],
    device_options: data.device_options || [],
    tree: Array.isArray(data.tree) ? data.tree : [],
  };
}

async function apiSend(url: string, method: 'POST' | 'PUT' | 'DELETE', body?: Record<string, unknown>): Promise<any> {
  const res = await fetch(url, {
    method,
    headers: authHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({ success: res.ok }));
  if (!res.ok || json.success === false) throw new Error(formatErrorDetail(json.detail || json.message));
  return json;
}

interface FieldDef {
  key: string;
  label: string;
  labelEn: string;
  type?: 'text' | 'number' | 'password' | 'select' | 'tel' | 'email';
  options?: { value: string; label: string; labelEn?: string }[];
  required?: boolean;
  placeholder?: string;
  maxLength?: number;
  inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode'];
  hint?: string;
  /** Hidden from the table list view */
  hideInTable?: boolean;
  /** Hidden from the edit/create form */
  hideInForm?: boolean;
  /** Hidden when creating a record but shown while editing */
  hideInCreate?: boolean;
  /** Shown as a masked presence flag in table (e.g. has_password) */
  secretFlag?: string;
}

type SiteContactField = 'contact_name' | 'contact_phone' | 'contact_email';

interface PhoneRule {
  callingCode: string;
  minDigits: number;
  maxDigits: number;
  pattern?: RegExp;
}

const COUNTRY_PHONE_RULES: Record<string, PhoneRule> = {
  CN: { callingCode: '86', minDigits: 11, maxDigits: 11, pattern: /1[3-9]\d{9}/ },
  US: { callingCode: '1', minDigits: 10, maxDigits: 10 }, CA: { callingCode: '1', minDigits: 10, maxDigits: 10 },
  GB: { callingCode: '44', minDigits: 10, maxDigits: 10 }, AU: { callingCode: '61', minDigits: 9, maxDigits: 9 },
  NZ: { callingCode: '64', minDigits: 8, maxDigits: 10 }, IN: { callingCode: '91', minDigits: 10, maxDigits: 10 },
  JP: { callingCode: '81', minDigits: 9, maxDigits: 10 }, KR: { callingCode: '82', minDigits: 9, maxDigits: 10 },
  SG: { callingCode: '65', minDigits: 8, maxDigits: 8 }, MY: { callingCode: '60', minDigits: 9, maxDigits: 10 },
  TH: { callingCode: '66', minDigits: 8, maxDigits: 9 }, VN: { callingCode: '84', minDigits: 9, maxDigits: 10 },
  DE: { callingCode: '49', minDigits: 7, maxDigits: 11 }, FR: { callingCode: '33', minDigits: 9, maxDigits: 9 },
  IT: { callingCode: '39', minDigits: 9, maxDigits: 10 }, ES: { callingCode: '34', minDigits: 9, maxDigits: 9 },
  RU: { callingCode: '7', minDigits: 10, maxDigits: 10 }, AE: { callingCode: '971', minDigits: 8, maxDigits: 9 },
  SA: { callingCode: '966', minDigits: 9, maxDigits: 9 }, BR: { callingCode: '55', minDigits: 10, maxDigits: 11 },
  MX: { callingCode: '52', minDigits: 10, maxDigits: 10 }, ZA: { callingCode: '27', minDigits: 9, maxDigits: 9 },
};

const COUNTRY_CALLING_CODES: Record<string, string> = {
  AF: '93', AL: '355', DZ: '213', AR: '54', AT: '43', BE: '32', BG: '359', BH: '973',
  BN: '673', BO: '591', BY: '375', CH: '41', CL: '56', CO: '57', CR: '506', CY: '357',
  CZ: '420', DK: '45', DO: '1', EC: '593', EG: '20', FI: '358', GR: '30', GT: '502',
  HK: '852', HR: '385', HU: '36', ID: '62', IE: '353', IL: '972', IR: '98', IQ: '964',
  IS: '354', JM: '1', JO: '962', KH: '855', KW: '965', KZ: '7', LA: '856', LB: '961',
  LK: '94', LU: '352', LV: '371', MC: '377', MM: '95', MN: '976', MO: '853', MT: '356',
  MV: '960', NG: '234', NL: '31', NO: '47', NP: '977', OM: '968', PA: '507', PE: '51',
  PH: '63', PK: '92', PL: '48', PT: '351', QA: '974', RO: '40', RS: '381', SE: '46',
  SK: '421', SI: '386', TR: '90', TW: '886', UA: '380', UY: '598', UZ: '998',
};

function phoneRuleForCountry(isoCode?: string): PhoneRule {
  const code = isoCode || 'CN';
  return COUNTRY_PHONE_RULES[code] || {
    callingCode: COUNTRY_CALLING_CODES[code] || '86', minDigits: 6, maxDigits: 15,
  };
}

function phoneLocalValue(rawValue: unknown, rule: PhoneRule): string {
  const value = String(rawValue ?? '').trim().replace(/[\s()-]/g, '');
  const prefix = `+${rule.callingCode}`;
  return value.startsWith(prefix) ? value.slice(prefix.length) : value.replace(/^\+/, '');
}

function composePhoneValue(localValue: string, rule: PhoneRule): string {
  const digits = localValue.replace(/\D/g, '');
  return digits ? `+${rule.callingCode}${digits}` : '';
}

function siteContactError(field: SiteContactField, rawValue: unknown, required: boolean, zh: boolean, phoneRule = phoneRuleForCountry()): string {
  const value = String(rawValue ?? '').trim();
  if (!value) {
    if (!required) return '';
    if (field === 'contact_name') return zh ? '请输入联系人姓名' : 'Contact name is required';
    if (field === 'contact_phone') return zh ? '请输入联系电话' : 'Contact phone is required';
    return zh ? '请输入联系邮箱' : 'Contact email is required';
  }
  if (field === 'contact_name' && !/^[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z· .'-]{1,49}$/.test(value)) {
    return zh ? '联系人姓名需为2-50个中文或英文字符' : 'Contact name must contain 2-50 Chinese or English letters';
  }
  if (field === 'contact_phone') {
    const local = phoneLocalValue(value, phoneRule);
    const prefix = `+${phoneRule.callingCode}`;
    if (!value.startsWith(prefix) || !/^\d+$/.test(local) || local.length < phoneRule.minDigits || local.length > phoneRule.maxDigits || (phoneRule.pattern && !phoneRule.pattern.test(local))) {
      return zh ? `请输入 ${prefix} 加 ${phoneRule.minDigits === phoneRule.maxDigits ? `${phoneRule.minDigits} 位` : `${phoneRule.minDigits}-${phoneRule.maxDigits} 位`}号码` : `Enter ${prefix} followed by ${phoneRule.minDigits === phoneRule.maxDigits ? phoneRule.minDigits : `${phoneRule.minDigits}-${phoneRule.maxDigits}`} digits`;
    }
  }
  if (field === 'contact_email' && (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value) || value.length > 254)) {
    return zh ? '请输入有效的邮箱地址' : 'Enter a valid email address';
  }
  return '';
}

const SITE_STATUS_OPTS = [
  { value: 'active', label: '在用', labelEn: 'Active' },
  { value: 'planned', label: '规划中', labelEn: 'Planned' },
  { value: 'staging', label: '建设中', labelEn: 'Staging' },
  { value: 'decommissioned', label: '已退役', labelEn: 'Decommissioned' },
  { value: 'offline', label: '离线', labelEn: 'Offline' },
];

const SITE_IMPORT_COLUMNS = [
  { key: 'site_name', header: '站点名称', headerEn: 'Site Name', required: true, sample: '北京生产中心' },
  { key: 'country', header: '国家', headerEn: 'Country', required: false, sample: '中国' },
  { key: 'state_province', header: '省份 / 州', headerEn: 'Province / State', required: false, sample: '北京市' },
  { key: 'city', header: '城市', headerEn: 'City', required: false, sample: '北京市' },
  { key: 'district', header: '区县', headerEn: 'District / County', required: false, sample: '朝阳区' },
  { key: 'contact_name', header: '联系人', headerEn: 'Contact', required: true, sample: '张三' },
  { key: 'contact_phone', header: '联系电话', headerEn: 'Contact Phone', required: true, sample: '+8613800000000' },
  { key: 'contact_email', header: '联系邮箱', headerEn: 'Contact Email', required: true, sample: 'ops@example.com' },
  { key: 'timezone', header: '时区', headerEn: 'Timezone', required: false, sample: 'Asia/Shanghai' },
  { key: 'address', header: '详细地址', headerEn: 'Address', required: false, sample: '示例路 1 号' },
  { key: 'status', header: '状态', headerEn: 'Status', required: false, sample: 'active' },
] as const;

type CredentialTemplateColumn = {
  key: string;
  label: string;
  labelEn: string;
  required: boolean;
  sample: string;
  note: string;
};

const SSH_CREDENTIAL_COLUMNS = [
  { key: 'credential_name', label: '凭据名称', labelEn: 'Credential Name', required: true, sample: 'core-ssh-admin', note: '必须唯一；1-100 个字符' },
  { key: 'credential_type', label: '类型', labelEn: 'Credential Type', required: true, sample: 'ssh_password', note: 'ssh_password / ssh_key / api_token' },
  { key: 'username', label: '用户名', labelEn: 'Username', required: false, sample: 'admin', note: 'SSH 登录用户名' },
  { key: 'account_role', label: '账号角色', labelEn: 'Account Role', required: false, sample: 'normal', note: 'normal / admin / shared / unbound' },
  { key: 'password', label: '密码', labelEn: 'Password', required: false, sample: '', note: '导出时始终为空；导入时按需填写' },
  { key: 'enable_password', label: 'Enable 密码', labelEn: 'Enable Password', required: false, sample: '', note: '导出时始终为空；导入时按需填写' },
] as const satisfies readonly CredentialTemplateColumn[];

const SNMP_CREDENTIAL_COLUMNS = [
  { key: 'credential_name', label: '凭据名称', labelEn: 'Credential Name', required: true, sample: 'core-snmp-monitor', note: '必须唯一；1-100 个字符' },
  { key: 'credential_type', label: '类型', labelEn: 'Credential Type', required: true, sample: 'snmpv2', note: 'snmpv2 / snmpv3' },
  { key: 'snmp_community', label: 'SNMP 团体字', labelEn: 'SNMP Community', required: false, sample: '', note: '导出时始终为空；snmpv2 必须填写' },
  { key: 'snmp_server', label: 'SNMP 服务器地址', labelEn: 'SNMP Server', required: false, sample: '', note: '可选；为空时使用设备管理 IP' },
] as const satisfies readonly CredentialTemplateColumn[];

type CredentialSheetKey = 'ssh' | 'snmp';
type CredentialSheetDefinition = {
  key: CredentialSheetKey;
  name: string;
  columns: readonly CredentialTemplateColumn[];
  defaultType: string;
  allowedTypes: readonly string[];
};

const CREDENTIAL_SHEET_DEFS: readonly CredentialSheetDefinition[] = [
  { key: 'ssh', name: 'SSH', columns: SSH_CREDENTIAL_COLUMNS, defaultType: 'ssh_password', allowedTypes: ['ssh_password', 'ssh_key', 'api_token'] },
  { key: 'snmp', name: 'SNMP', columns: SNMP_CREDENTIAL_COLUMNS, defaultType: 'snmpv2', allowedTypes: ['snmpv2', 'snmpv3'] },
];

const CREDENTIAL_SECRET_FIELDS = new Set(['password', 'enable_password', 'snmp_community']);

const CREDENTIAL_ROLE_VALUE_ALIASES: Record<string, string> = {
  normal: 'normal',
  admin: 'admin',
  shared: 'shared',
  unbound: 'unbound',
  普通账号: 'normal',
  特权账号: 'admin',
  通用账号: 'shared',
  未指定: 'unbound',
  'Normal account': 'normal',
  'Privileged account': 'admin',
  'Shared account': 'shared',
  Unassigned: 'unbound',
};

type SiteImportRow = Record<string, string>;
type SiteImportError = { row: number; message: string };
type CredentialImportRow = { sheet: CredentialSheetKey; sheetName: string; row: number; values: Record<string, string> };
type CredentialImportError = { sheet: string; row: number; message: string };

const SITE_IMPORT_HEADER_ALIASES: Record<string, string> = Object.fromEntries(
  SITE_IMPORT_COLUMNS.flatMap(column => [
    [column.header, column.key],
    [column.headerEn, column.key],
    [column.key, column.key],
  ]),
);

const CRED_TYPE_OPTS = [
  { value: 'ssh_password', label: 'ssh_password' },
  { value: 'ssh_key', label: 'ssh_key' },
  { value: 'snmpv2', label: 'snmpv2' },
  { value: 'snmpv3', label: 'snmpv3' },
  { value: 'api_token', label: 'api_token' },
];

const CRED_ROLE_OPTS = [
  { value: 'normal', label: '普通账号', labelEn: 'Normal account' },
  { value: 'admin', label: '特权账号', labelEn: 'Privileged account' },
  { value: 'shared', label: '通用账号', labelEn: 'Shared account' },
  { value: 'unbound', label: '未指定', labelEn: 'Unassigned' },
];

const VLAN_STATUS_OPTS = [
  { value: 'active', label: 'active' },
  { value: 'reserved', label: 'reserved' },
  { value: 'deprecated', label: 'deprecated' },
];

interface GeoCountry { name: string; isoCode: string }
interface GeoState { name: string; isoCode: string; countryCode: string }
interface GeoCity { name: string; stateCode: string; countryCode: string }
interface GeoDistrict { name: string; displayName: string; pinyin: string; cityName: string; stateCode: string; countryCode: string }
interface GeoCatalog {
  countries: GeoCountry[];
  states: GeoState[];
}

async function fetchLocalGeoData<T>(file: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`/data/geo/${file}`, { signal: controller.signal });
    if (!response.ok) throw new Error(`Geo data request failed: ${response.status}`);
    return await response.json() as T;
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

const CHINA_STATE_LABELS: Record<string, string> = {
  AH: '安徽', BJ: '北京', CQ: '重庆', FJ: '福建', GS: '甘肃', GD: '广东', GX: '广西', GZ: '贵州',
  HI: '海南', HE: '河北', HL: '黑龙江', HA: '河南', HK: '香港', HB: '湖北', HN: '湖南', IM: '内蒙古',
  JS: '江苏', JX: '江西', JL: '吉林', LN: '辽宁', MO: '澳门', NX: '宁夏', QH: '青海', SN: '陕西',
  SD: '山东', SH: '上海', SX: '山西', SC: '四川', TW: '台湾', TJ: '天津', XJ: '新疆', XZ: '西藏',
  YN: '云南', ZJ: '浙江',
};

function countryDisplayName(country: GeoCountry): string {
  try {
    return new Intl.DisplayNames(['zh-CN'], { type: 'region' }).of(country.isoCode) || country.name;
  } catch {
    return country.name;
  }
}

// Country data is intentionally kept in English for stable storage and
// interoperability. These common aliases make Chinese labels searchable by
// pinyin without changing the catalog contract.
const COUNTRY_PINYIN_ALIASES: Record<string, string> = {
  CN: 'zhongguo', US: 'meiguo', JP: 'riben', KR: 'hanguo',
  GB: 'yingguo', SG: 'xinjiapo', MY: 'malaixiya', TH: 'taiguo',
  VN: 'yuenan', IN: 'yindu', RU: 'eluosi', DE: 'deguo',
  FR: 'faguo', IT: 'yidali', ES: 'xibanya', AU: 'aodaliya',
  CA: 'jianada', NZ: 'xinxilan', AE: 'alianqiutichang',
};

function countrySearchText(country: GeoCountry): string {
  return `${country.name} ${country.isoCode} ${COUNTRY_PINYIN_ALIASES[country.isoCode] || ''}`;
}

function stateDisplayName(state: GeoState): string {
  return state.countryCode === 'CN' ? (CHINA_STATE_LABELS[state.isoCode] || state.name) : state.name;
}

const CHINA_CITY_LABELS: Record<string, string> = {
  Beijing: '北京', Shanghai: '上海', Tianjin: '天津', Chongqing: '重庆',
  Guangzhou: '广州', Shenzhen: '深圳', Zhuhai: '珠海', Dongguan: '东莞', Foshan: '佛山',
  Hangzhou: '杭州', Ningbo: '宁波', Wenzhou: '温州', Nanjing: '南京', Suzhou: '苏州',
  Wuxi: '无锡', Xuzhou: '徐州', Wuhan: '武汉', Changsha: '长沙', Zhengzhou: '郑州',
  Jinan: '济南', Qingdao: '青岛', Shenyang: '沈阳', Dalian: '大连', Harbin: '哈尔滨',
  Changchun: '长春', XiAn: '西安', Xian: '西安', Chengdu: '成都', Kunming: '昆明',
  Guiyang: '贵阳', Nanning: '南宁', Haikou: '海口', Fuzhou: '福州', Xiamen: '厦门',
  Hefei: '合肥', Nanchang: '南昌', Taiyuan: '太原', Shijiazhuang: '石家庄',
  Hohhot: '呼和浩特', Urumqi: '乌鲁木齐', Lanzhou: '兰州', Xining: '西宁',
  Yinchuan: '银川', Lhasa: '拉萨', Hainan: '海南', HongKong: '香港', Macau: '澳门',
  Taipei: '台北', Kaohsiung: '高雄', Taichung: '台中', Tainan: '台南',
  // The bundled city catalog is romanized; keep Chinese labels separate so
  // the UI displays Chinese while the searchable aliases remain available.
  Anlu: '\u5b89\u9646', Buhe: '\u5e03\u6cb3', Caidian: '\u8521\u7538', Caohe: '\u6f15\u6cb3', Chengzhong: '\u57ce\u4e2d',
  Danjiangkou: '\u4e39\u6c5f\u53e3', Daye: '\u5927\u51b6', Duobao: '\u591a\u5b9d', Enshi: '\u6069\u65bd', EnshiTujiazuMiaozuZizhizhou: '\u6069\u65bd\u571f\u5bb6\u65cf\u82d7\u65cf\u81ea\u6cbb\u5dde',
  Ezhou: '\u9102\u5dde', EzhouShi: '\u9102\u5dde', Fengkou: '\u4e30\u53e3', Guangshui: '\u5e7f\u6c34', GuchengChengguanzhen: '\u8c37\u57ce',
  Hanchuan: '\u6c49\u5ddd', Huanggang: '\u9ec4\u5188', Huangmei: '\u9ec4\u6885', Huangpi: '\u9ec4\u9642', Huangshi: '\u9ec4\u77f3', Huangzhou: '\u9ec4\u5dde',
  Jingling: '\u7ade\u9675', Jingmen: '\u8346\u95e8', JingmenShi: '\u8346\u95e8', Jingzhou: '\u8346\u5dde', Laohekou: '\u8001\u6cb3\u53e3',
  Lichuan: '\u5229\u5ddd', Macheng: '\u9ebb\u57ce', NanzhangChengguanzhen: '\u5357\u6f33',
  Puqi: '\u8d64\u58c1', Qianjiang: '\u6f5c\u6c5f', Shashi: '\u6c99\u5e02', Shennongjia: '\u795e\u519c\u67b6', Shiyan: '\u5341\u5830',
  Suizhou: '\u968f\u5dde', Wuxue: '\u6b66\u7a74', Xiangyang: '\u8944\u9633', Xianning: '\u54b8\u5b81', XianningPrefecture: '\u54b8\u5b81',
  Xiantao: '\u4ed9\u6843', Xiaogan: '\u5b5d\u611f', Xihe: '\u6eaa\u6cb3', Xindi: '\u65b0\u5824', Xinshi: '\u65b0\u5e02', Xinzhou: '\u65b0\u6d32', Xiulin: '\u79c0\u6797',
  Yichang: '\u5b9c\u660c', Yicheng: '\u5b9c\u57ce', YunmengChengguanzhen: '\u4e91\u68a6', Zaoyang: '\u67a3\u9633', Zhicheng: '\u679d\u57ce', Zhijiang: '\u679d\u6c5f', Zhongxiang: '\u949f\u7965',
};

const CHINA_CITY_LABELS_BY_STATE: Record<string, string> = {
  "SC:abazangzuqiangzuzizhizhou": "\u963f\u575d\u85cf\u65cf\u7f8c\u65cf\u81ea\u6cbb\u5dde",
  "HL:acheng": "\u963f\u57ce\u533a",
  "XJ:ailanmubage": "\u827e\u5170\u6728\u5df4\u683c\u8857\u9053",
  "GD:anbu": "\u5eb5\u57e0\u9547",
  "HL:anda": "\u5b89\u8fbe\u5e02",
  "HN:anjiang": "\u5b89\u6c5f\u9547",
  "SN:ankang": "\u5b89\u5eb7\u5e02",
  "HB:anlu": "\u5b89\u9646\u5e02",
  "HN:anping": "\u5b89\u5e73\u9547",
  "AH:anqing": "\u5b89\u5e86\u5e02",
  "AH:anqingshi": "\u5b89\u5e86\u5e02",
  "SD:anqiu": "\u5b89\u4e18\u5e02",
  "LN:anshan": "\u978d\u5c71\u5e02",
  "GZ:anshun": "\u5b89\u987a\u5e02",
  "HN:anxiang": "\u5b89\u4e61\u53bf",
  "HA:anyang": "\u5b89\u9633\u5e02",
  "HA:anyangshi": "\u5b89\u9633\u5e02",
  "GX:babu": "\u516b\u6b65\u533a",
  "GZ:bahuang": "\u575d\u9ec4\u9547",
  "JL:baicheng": "\u767d\u57ce\u5e02",
  "GX:baihe": "\u767e\u5408\u9547",
  "TJ:baijian": "\u767d\u6da7\u9547",
  "XJ:baijiantan": "\u767d\u78b1\u6ee9\u533a",
  "HL:baiquan": "\u62dc\u6cc9\u53bf",
  "GX:baiseshi": "\u767e\u8272\u5e02",
  "HN:baisha": "\u767d\u6c99\u9547",
  "JL:baishan": "\u767d\u5c71\u5e02",
  "JL:baishishan": "\u767d\u77f3\u5c71\u9547",
  "GS:baiyin": "\u767d\u94f6\u5e02",
  "TJ:bamencheng": "\u516b\u95e8\u57ce\u9547",
  "HL:bamiantong": "\u516b\u9762\u901a\u9547",
  "GZ:bangdong": "\u90a6\u6d1e\u8857\u9053",
  "TJ:bangjun": "\u90a6\u5747\u9547",
  "HE:baoding": "\u4fdd\u5b9a\u5e02",
  "SN:baojishi": "\u5b9d\u9e21\u5e02",
  "HL:baoqing": "\u5b9d\u6e05\u53bf",
  "HL:baoshan": "\u5b9d\u5c71\u533a",
  "NM:baotou": "\u5305\u5934\u5e02",
  "HI:basuo": "\u516b\u6240\u9547",
  "HL:bayan": "\u5df4\u5f66\u53bf",
  "SC:bazhongshi": "\u5df4\u4e2d\u5e02",
  "HL:bei\u2019an": "\u5317\u5b89\u5e02",
  "CQ:beibei": "\u5317\u789a\u533a",
  "TJ:beicang": "\u5317\u4ed3\u9547",
  "GX:beihai": "\u5317\u6d77\u5e02",
  "TJ:beihuaidian": "\u5317\u6dee\u6dc0\u9547",
  "LN:beipiao": "\u5317\u7968\u5e02",
  "SD:beizhai": "\u5317\u5b85\u8857\u9053",
  "GZ:benchu": "\u574c\u5904\u9547",
  "AH:bengbu": "\u868c\u57e0\u5e02",
  "LN:benxi": "\u672c\u6eaa\u5e02",
  "SD:bianzhuang": "\u535e\u5e84\u8857\u9053",
  "TJ:biaokou": "\u4ff5\u53e3\u9547",
  "GZ:bijie": "\u6bd5\u8282\u5e02",
  "HA:binhe": "\u6ee8\u6cb3\u8857\u9053",
  "HL:binzhou": "\u5bbe\u5dde\u9547",
  "SD:binzhou": "\u6ee8\u5dde\u5e02",
  "HN:biyong": "\u78a7\u6d8c\u9547",
  "HL:boli": "\u52c3\u5229\u53bf",
  "SD:boshan": "\u535a\u5c71\u533a",
  "HN:boyang": "\u64ad\u9633\u9547",
  "AH:bozhou": "\u4eb3\u5dde\u5e02",
  "HN:bozhou": "\u6ce2\u6d32\u9547",
  "HB:buhe": "\u57e0\u6cb3\u9547",
  "HB:caidian": "\u8521\u7538\u533a",
  "CQ:caijia": "\u8521\u5bb6\u9547",
  "HE:cangzhou": "\u6ca7\u5dde\u5e02",
  "HE:cangzhoushi": "\u6ca7\u5dde\u5e02",
  "HB:caohe": "\u6f15\u6cb3\u9547",
  "GZ:chadian": "\u8336\u5e97\u8857\u9053",
  "HL:chaihe": "\u67f4\u6cb3\u9547",
  "JL:changchun": "\u957f\u6625\u5e02",
  "HN:changde": "\u5e38\u5fb7\u5e02",
  "XJ:changji": "\u660c\u5409\u5e02",
  "XJ:changjihuizuzizhizhou": "\u660c\u5409\u56de\u65cf\u81ea\u6cbb\u5dde",
  "HE:changli": "\u660c\u9ece\u53bf",
  "BJ:changping": "\u660c\u5e73\u533a",
  "GZ:changsha": "\u957f\u6c99\u9547",
  "HN:changsha": "\u957f\u6c99\u5e02",
  "HN:changshashi": "\u957f\u6c99\u5e02",
  "LN:changtu": "\u660c\u56fe\u53bf",
  "JS:changzhou": "\u5e38\u5dde\u5e02",
  "AH:chaohu": "\u5de2\u6e56\u5e02",
  "JL:chaoyang": "\u671d\u9633\u533a",
  "GD:chaozhou": "\u6f6e\u5dde\u5e02",
  "HN:chatian": "\u8336\u7530\u9547",
  "HE:chengde": "\u627f\u5fb7\u5e02",
  "SC:chengdu": "\u6210\u90fd\u5e02",
  "HA:chengguan": "\u57ce\u5173\u9547",
  "GD:chenghua": "\u6f84\u534e\u8857\u9053",
  "FJ:chengmen": "\u57ce\u95e8\u9547",
  "SD:chengyang": "\u57ce\u9633\u533a",
  "HB:chengzhong": "\u57ce\u4e2d\u8857\u9053",
  "HL:chengzihe": "\u57ce\u5b50\u6cb3\u533a",
  "HN:chenzhou": "\u90f4\u5dde\u5e02",
  "NM:chifeng": "\u8d64\u5cf0\u5e02",
  "FJ:chixi": "\u8d64\u6eaa\u9547",
  "AH:chizhou": "\u6c60\u5dde\u5e02",
  "AH:chizhoushi": "\u6c60\u5dde\u5e02",
  "GX:chongzuoshi": "\u5d07\u5de6\u5e02",
  "GZ:chumi": "\u695a\u7c73\u9547",
  "YN:chuxiongyizuzizhizhou": "\u695a\u96c4\u5f5d\u65cf\u81ea\u6cbb\u5dde",
  "AH:chuzhou": "\u6ec1\u5dde\u5e02",
  "AH:chuzhoushi": "\u6ec1\u5dde\u5e02",
  "GZ:dabachang": "\u5927\u575d\u573a\u9547",
  "FJ:dadeng": "\u5927\u5d9d\u8857\u9053",
  "SC:dadukou": "\u5927\u6e21\u53e3\u8857\u9053",
  "FJ:daixi": "\u4ee3\u6eaa\u9547",
  "TJ:dakoutun": "\u5927\u53e3\u5c6f\u9547",
  "YN:dali": "\u5927\u7406\u5e02",
  "YN:dalibaizuzizhizhou": "\u5927\u7406\u767d\u65cf\u81ea\u6cbb\u5dde",
  "LN:dalian": "\u5927\u8fde\u5e02",
  "GD:daliang": "\u5927\u826f\u8857\u9053",
  "LN:dalianwan": "\u5927\u8fde\u6e7e\u8857\u9053",
  "LN:dandong": "\u4e39\u4e1c\u5e02",
  "HB:danjiangkou": "\u4e39\u6c5f\u53e3\u5e02",
  "GD:danshui": "\u6de1\u6c34\u8857\u9053",
  "FJ:danyang": "\u4e39\u9633\u9547",
  "FJ:daqiao": "\u5927\u6865\u9547",
  "HL:daqing": "\u5927\u5e86\u5e02",
  "GD:dasha": "\u5927\u6c99\u8857\u9053",
  "LN:dashiqiao": "\u5927\u77f3\u6865\u5e02",
  "JL:dashitou": "\u5927\u77f3\u5934\u9547",
  "AH:datong": "\u5927\u901a\u533a",
  "SX:datong": "\u5927\u540c\u5e02",
  "SX:datongshi": "\u5927\u540c\u5e02",
  "NX:dawukou": "\u5927\u6b66\u53e3\u533a",
  "BJ:daxing": "\u5927\u5174\u533a",
  "HB:daye": "\u5927\u51b6\u5e02",
  "TJ:dazhongzhuang": "\u5927\u949f\u5e84\u9547",
  "SC:dazhou": "\u8fbe\u5dde\u5e02",
  "YN:dehongdaizujingpozuzizhizhou": "\u5fb7\u5b8f\u50a3\u65cf\u666f\u9887\u65cf\u81ea\u6cbb\u5dde",
  "JL:dehui": "\u5fb7\u60e0\u5e02",
  "QH:delingha": "\u5fb7\u4ee4\u54c8\u5e02",
  "HN:dengjiapu": "\u9093\u5bb6\u94fa\u9547",
  "HN:dengyuantai": "\u9093\u5143\u6cf0\u9547",
  "SD:dengzhou": "\u767b\u5dde\u8857\u9053",
  "ZJ:deqing": "\u5fb7\u6e05\u53bf",
  "SC:deyang": "\u5fb7\u9633\u5e02",
  "SD:dezhou": "\u5fb7\u5dde\u5e02",
  "HA:dingcheng": "\u5b9a\u57ce\u8857\u9053",
  "SD:dingtao": "\u5b9a\u9676\u533a",
  "GS:dingxishi": "\u5b9a\u897f\u5e02",
  "HE:dingzhou": "\u5b9a\u5dde\u5e02",
  "SD:dongcun": "\u4e1c\u6751\u8857\u9053",
  "FJ:dongdai": "\u4e1c\u5cb1\u9547",
  "JL:dongfeng": "\u4e1c\u4e30\u53bf",
  "GD:dongguan": "\u4e1c\u839e\u5e02",
  "GD:donghai": "\u4e1c\u6d77\u8857\u9053",
  "FJ:donghu": "\u4e1c\u6e56\u9547",
  "FJ:dongling": "\u4e1c\u5cad\u9547",
  "LN:dongling": "\u4e1c\u9675\u8857\u9053",
  "HL:dongning": "\u4e1c\u5b81\u5e02",
  "HN:dongshandongzuxiang": "\u4e1c\u5c71\u4f97\u65cf\u4e61",
  "NM:dongsheng": "\u4e1c\u80dc\u533a",
  "TJ:dongshigu": "\u4e1c\u65bd\u53e4\u9547",
  "NX:dongta": "\u4e1c\u5854\u9547",
  "CQ:dongxi": "\u4e1c\u6eaa\u9547",
  "SC:dongxi": "\u4e1c\u6eaa\u8857\u9053",
  "HL:dongxing": "\u4e1c\u5174\u9547",
  "ZJ:dongyang": "\u4e1c\u9633\u5e02",
  "FJ:dongyuan": "\u4e1c\u56ed\u9547",
  "GD:ducheng": "\u90fd\u57ce\u9547",
  "JL:dunhua": "\u6566\u5316\u5e02",
  "HB:duobao": "\u591a\u5b9d\u9547",
  "NM:e\u2019erguna": "\u989d\u5c14\u53e4\u7eb3\u5e02",
  "GD:encheng": "\u6069\u57ce\u8857\u9053",
  "HB:enshitujiazumiaozuzizhizhou": "\u6069\u65bd\u571f\u5bb6\u65cf\u82d7\u65cf\u81ea\u6cbb\u5dde",
  "JL:erdaojiang": "\u4e8c\u9053\u6c5f\u533a",
  "TJ:erwangzhuang": "\u5c14\u738b\u5e84\u9547",
  "HB:ezhou": "\u9102\u5dde\u5e02",
  "HB:ezhoushi": "\u9102\u5dde\u5e02",
  "GX:fangchenggangshi": "\u9632\u57ce\u6e2f\u5e02",
  "BJ:fangshan": "\u623f\u5c71\u533a",
  "SC:fangting": "\u65b9\u4ead\u8857\u9053",
  "SD:feicheng": "\u80a5\u57ce\u5e02",
  "FJ:feiluan": "\u98de\u9e3e\u9547",
  "HL:fendou": "\u594b\u6597\u8857\u9053",
  "LN:fengcheng": "\u51e4\u57ce\u5e02",
  "ZJ:fenghua": "\u5949\u5316\u533a",
  "HN:fenghuang": "\u51e4\u51f0\u53bf",
  "HB:fengkou": "\u5cf0\u53e3\u9547",
  "HE:fengrun": "\u4e30\u6da6\u533a",
  "HL:fengxiang": "\u51e4\u7fd4\u9547",
  "FJ:fengzhou": "\u4e30\u5dde\u9547",
  "JX:fenyi": "\u5206\u5b9c\u53bf",
  "GD:foshan": "\u4f5b\u5c71\u5e02",
  "GD:foshanshi": "\u4f5b\u5c71\u5e02",
  "FJ:fu\u2019an": "\u798f\u5b89\u5e02",
  "SC:fubao": "\u798f\u5b9d\u9547",
  "FJ:fuding": "\u798f\u9f0e\u5e02",
  "HL:fujin": "\u5bcc\u9526\u5e02",
  "XJ:fukang": "\u961c\u5eb7\u5e02",
  "HL:fuli": "\u5bcc\u529b\u8857\u9053",
  "CQ:fuling": "\u6daa\u9675\u533a",
  "FJ:fuqing": "\u798f\u6e05\u5e02",
  "LN:fushun": "\u629a\u987a\u5e02",
  "LN:fuxin": "\u961c\u65b0\u5e02",
  "AH:fuyang": "\u961c\u9633\u5e02",
  "ZJ:fuyang": "\u5bcc\u9633\u533a",
  "AH:fuyangshi": "\u961c\u9633\u5e02",
  "HL:fuyu": "\u5bcc\u88d5\u53bf",
  "JL:fuyu": "\u6276\u4f59\u5e02",
  "HL:fuyuan": "\u629a\u8fdc\u5e02",
  "FJ:fuzhou": "\u798f\u5dde\u5e02",
  "LN:gaizhou": "\u76d6\u5dde\u5e02",
  "HL:gannan": "\u7518\u5357\u53bf",
  "CQ:ganshui": "\u8d76\u6c34\u9547",
  "FJ:gantang": "\u7518\u68e0\u9547",
  "JX:ganzhou": "\u8d63\u5dde\u5e02",
  "JX:ganzhoushi": "\u8d63\u5dde\u5e02",
  "SD:gaomi": "\u9ad8\u5bc6\u5e02",
  "GZ:gaoniang": "\u9ad8\u917f\u9547",
  "SC:gaoping": "\u9ad8\u576a\u533a",
  "HN:gaoqiao": "\u9ad8\u6865\u8857\u9053",
  "GD:gaoyao": "\u9ad8\u8981\u533a",
  "GD:gaozhou": "\u9ad8\u5dde\u5e02",
  "YN:gejiu": "\u4e2a\u65e7\u5e02",
  "NM:genhe": "\u6839\u6cb3\u5e02",
  "JL:gongzhuling": "\u516c\u4e3b\u5cad\u5e02",
  "GZ:guandu": "\u5b98\u6e21\u9547",
  "SC:guang\u2019an": "\u5e7f\u5b89\u5e02",
  "JL:guangming": "\u5149\u660e\u8857\u9053",
  "HB:guangshui": "\u5e7f\u6c34\u5e02",
  "SC:guangyuan": "\u5e7f\u5143\u5e02",
  "GD:guangzhou": "\u5e7f\u5dde\u5e02",
  "GD:guangzhoushi": "\u5e7f\u5dde\u5e02",
  "HN:guankou": "\u5173\u53e3\u8857\u9053",
  "FJ:guantou": "\u742f\u5934\u9547",
  "FJ:gufeng": "\u53e4\u5cf0\u9547",
  "GX:guigang": "\u8d35\u6e2f\u5e02",
  "GX:guilin": "\u6842\u6797\u5e02",
  "GX:guilinshi": "\u6842\u6797\u5e02",
  "GX:guiping": "\u6842\u5e73\u5e02",
  "JX:guixi": "\u8d35\u6eaa\u5e02",
  "GZ:guiyang": "\u8d35\u9633\u5e02",
  "SN:guozhen": "\u90ed\u9547",
  "AH:gushu": "\u59d1\u5b70\u9547",
  "SX:gutao": "\u53e4\u9676\u9547",
  "HE:guye": "\u53e4\u51b6\u533a",
  "LN:haicheng": "\u6d77\u57ce\u5e02",
  "HI:haikou": "\u6d77\u53e3\u5e02",
  "YN:haikou": "\u6d77\u53e3\u8857\u9053",
  "HL:hailin": "\u6d77\u6797\u5e02",
  "HL:hailun": "\u6d77\u4f26\u5e02",
  "GD:haimen": "\u6d77\u95e8\u9547",
  "ZJ:haining": "\u6d77\u5b81\u5e02",
  "XJ:hami": "\u54c8\u5bc6\u5e02",
  "HA:hancheng": "\u97e9\u57ce\u9547",
  "SN:hancheng": "\u97e9\u57ce\u5e02",
  "HB:hanchuan": "\u6c49\u5ddd\u5e02",
  "HE:handan": "\u90af\u90f8\u5e02",
  "ZJ:hangzhou": "\u676d\u5dde\u5e02",
  "SD:hanting": "\u5bd2\u4ead\u533a",
  "SN:hanzhong": "\u6c49\u4e2d\u5e02",
  "TJ:hebeitun": "\u6cb3\u5317\u5c6f\u9547",
  "HA:hebi": "\u9e64\u58c1\u5e02",
  "GX:hechishi": "\u6cb3\u6c60\u5e02",
  "CQ:hechuan": "\u5408\u5ddd\u533a",
  "HE:hecun": "\u548c\u6751\u9547",
  "AH:hefei": "\u5408\u80a5\u5e02",
  "AH:hefeishi": "\u5408\u80a5\u5e02",
  "HL:hegang": "\u9e64\u5c97\u5e02",
  "HL:heihe": "\u9ed1\u6cb3\u5e02",
  "LN:heishan": "\u9ed1\u5c71\u53bf",
  "JL:helong": "\u548c\u9f99\u5e02",
  "HN:hengbanqiao": "\u6a2a\u677f\u6865\u9547",
  "HE:hengshui": "\u8861\u6c34\u5e02",
  "HN:hengyang": "\u8861\u9633\u5e02",
  "GD:hepo": "\u6cb3\u5a46\u8857\u9053",
  "FJ:hetang": "\u9e64\u5858\u9547",
  "HN:hexiangqiao": "\u8377\u9999\u6865\u9547",
  "TJ:hexiwu": "\u6cb3\u897f\u52a1\u9547",
  "GD:heyuan": "\u6cb3\u6e90\u5e02",
  "SD:heze": "\u83cf\u6cfd\u5e02",
  "GS:hezuo": "\u5408\u4f5c\u5e02",
  "HL:honggang": "\u7ea2\u5c97\u533a",
  "YN:honghehanizuyizuzizhizhou": "\u7ea2\u6cb3\u54c8\u5c3c\u65cf\u5f5d\u65cf\u81ea\u6cbb\u5dde",
  "HN:hongjiang": "\u6d2a\u6c5f\u5e02",
  "HN:hongqiao": "\u6d2a\u6865\u8857\u9053",
  "FJ:hongtang": "\u6d2a\u5858\u9547",
  "GZ:hongzhou": "\u6d2a\u5dde\u9547",
  "JL:huadian": "\u6866\u7538\u5e02",
  "JS:huaian": "\u6dee\u5b89\u5e02",
  "AH:huaibei": "\u6dee\u5317\u5e02",
  "GD:huaicheng": "\u6000\u57ce\u8857\u9053",
  "HN:huaihua": "\u6000\u5316\u5e02",
  "AH:huainan": "\u6dee\u5357\u5e02",
  "AH:huainanshi": "\u6dee\u5357\u5e02",
  "HL:huanan": "\u6866\u5357\u53bf",
  "GD:huanggang": "\u9ec4\u5188\u9547",
  "HB:huanggang": "\u9ec4\u5188\u5e02",
  "HN:huanglong": "\u9ec4\u9f99\u9547",
  "HN:huangmaoyuan": "\u9ec4\u8305\u56ed\u9547",
  "HB:huangmei": "\u9ec4\u6885\u53bf",
  "QH:huangnanzangzuzizhizhou": "\u9ec4\u5357\u85cf\u65cf\u81ea\u6cbb\u5dde",
  "JL:huangnihe": "\u9ec4\u6ce5\u6cb3\u9547",
  "HB:huangpi": "\u9ec4\u9642\u533a",
  "HN:huangqiao": "\u9ec4\u6865\u9547",
  "AH:huangshan": "\u9ec4\u5c71\u5e02",
  "AH:huangshanshi": "\u9ec4\u5c71\u5e02",
  "FJ:huangtian": "\u9ec4\u7530\u9547",
  "HN:huangtukuang": "\u9ec4\u571f\u77ff\u9547",
  "HN:huangxikou": "\u9ec4\u6eaa\u53e3\u9547",
  "ZJ:huangyan": "\u9ec4\u5ca9\u533a",
  "HB:huangzhou": "\u9ec4\u5dde\u533a",
  "LN:huanren": "\u6853\u4ec1\u9547",
  "HN:huaqiao": "\u82b1\u6865\u9547",
  "GZ:huaqiu": "\u82b1\u79cb\u9547",
  "SN:huayin": "\u534e\u9634\u5e02",
  "HN:huayuan": "\u82b1\u57a3\u53bf",
  "GD:huazhou": "\u5316\u5dde\u5e02",
  "HA:huazhou": "\u82b1\u6d32\u8857\u9053",
  "HA:huichang": "\u4f1a\u660c\u8857\u9053",
  "GD:huicheng": "\u60e0\u57ce\u533a",
  "JL:huinan": "\u8f89\u5357\u53bf",
  "GD:huizhou": "\u60e0\u5dde\u5e02",
  "HL:hulan": "\u547c\u5170\u533a",
  "LN:huludao": "\u846b\u82a6\u5c9b\u5e02",
  "LN:huludaoshi": "\u846b\u82a6\u5c9b\u5e02",
  "GD:humen": "\u864e\u95e8\u9547",
  "XJ:huocheng": "\u970d\u57ce\u53bf",
  "TJ:huogezhuang": "\u970d\u5404\u5e84\u9547",
  "HN:huomachong": "\u706b\u9a6c\u51b2\u9547",
  "FJ:huotong": "\u970d\u7ae5\u9547",
  "LN:hushitai": "\u864e\u77f3\u53f0\u8857\u9053",
  "ZJ:huzhou": "\u6e56\u5dde\u5e02",
  "JL:ji\u2019an": "\u96c6\u5b89\u5e02",
  "JX:ji\u2019an": "\u5409\u5b89\u5e02",
  "SD:jiamaying": "\u7532\u9a6c\u8425\u9547",
  "HL:jiamusi": "\u4f73\u6728\u65af\u5e02",
  "FJ:jian\u2019ou": "\u5efa\u74ef\u5e02",
  "SC:jiancheng": "\u7b80\u57ce\u8857\u9053",
  "FJ:jiangkou": "\u6c5f\u53e3\u9547",
  "HN:jiangkouxu": "\u6c5f\u53e3\u589f\u9547",
  "GD:jiangmen": "\u6c5f\u95e8\u5e02",
  "JX:jianguang": "\u5251\u5149\u8857\u9053",
  "SC:jiangyou": "\u6c5f\u6cb9\u5e02",
  "XZ:jiangzi": "\u6c5f\u5b5c\u53bf",
  "FJ:jianjiang": "\u9274\u6c5f\u9547",
  "SC:jiannan": "\u5251\u5357\u8857\u9053",
  "HA:jianshe": "\u5efa\u8bbe\u8857\u9053",
  "ZJ:jiaojiang": "\u6912\u6c5f\u533a",
  "SD:jiaozhou": "\u80f6\u5dde\u5e02",
  "HA:jiaozuo": "\u7126\u4f5c\u5e02",
  "ZJ:jiashan": "\u5609\u5584\u53bf",
  "ZJ:jiaxing": "\u5609\u5174\u5e02",
  "ZJ:jiaxingshi": "\u5609\u5174\u5e02",
  "GS:jiayuguan": "\u5609\u5cea\u5173\u5e02",
  "GD:jiazi": "\u7532\u5b50\u9547",
  "HL:jidong": "\u9e21\u4e1c\u53bf",
  "SD:jiehu": "\u754c\u6e56\u8857\u9053",
  "AH:jieshou": "\u754c\u9996\u5e02",
  "SX:jiexiu": "\u4ecb\u4f11\u5e02",
  "GD:jieyang": "\u63ed\u9633\u5e02",
  "CQ:jijiang": "\u51e0\u6c5f\u8857\u9053",
  "JL:jilin": "\u5409\u6797\u5e02",
  "SD:jimo": "\u5373\u58a8\u533a",
  "SD:jinan": "\u6d4e\u5357\u5e02",
  "GS:jinchang": "\u91d1\u660c\u5e02",
  "SX:jincheng": "\u664b\u57ce\u5e02",
  "JX:jingdezhenshi": "\u666f\u5fb7\u9547\u5e02",
  "FJ:jingfeng": "\u51c0\u5cf0\u9547",
  "YN:jinghong": "\u666f\u6d2a\u5e02",
  "HB:jingling": "\u7adf\u9675\u8857\u9053",
  "HB:jingmen": "\u8346\u95e8\u5e02",
  "HB:jingmenshi": "\u8346\u95e8\u5e02",
  "HB:jingzhou": "\u8346\u5dde\u5e02",
  "HN:jinhe": "\u9526\u548c\u9547",
  "ZJ:jinhua": "\u91d1\u534e\u5e02",
  "NM:jining": "\u96c6\u5b81\u533a",
  "SD:jining": "\u6d4e\u5b81\u5e02",
  "GX:jinji": "\u91d1\u9e21\u9547",
  "FJ:jinjiang": "\u664b\u6c5f\u5e02",
  "HI:jinjiang": "\u91d1\u6c5f\u9547",
  "FJ:jinjing": "\u91d1\u4e95\u9547",
  "HN:jinshiqiao": "\u91d1\u77f3\u6865\u9547",
  "ZJ:jinxiang": "\u91d1\u4e61\u9547",
  "SX:jinzhongshi": "\u664b\u4e2d\u5e02",
  "LN:jinzhou": "\u9526\u5dde\u5e02",
  "JL:jishu": "\u5409\u8212\u8857\u9053",
  "HA:jishui": "\u6c72\u6c34\u9547",
  "JX:jiujiang": "\u4e5d\u6c5f\u5e02",
  "GS:jiuquan": "\u9152\u6cc9\u5e02",
  "JL:jiutai": "\u4e5d\u53f0\u533a",
  "HL:jixi": "\u9e21\u897f\u5e02",
  "HA:jiyuan": "\u6d4e\u6e90\u5e02",
  "SD:juye": "\u5de8\u91ce\u53bf",
  "HA:kaifeng": "\u5f00\u5c01\u5e02",
  "YN:kaihua": "\u5f00\u5316\u8857\u9053",
  "JL:kaitong": "\u5f00\u901a\u9547",
  "HA:kaiyuan": "\u5f00\u5143\u8857\u9053",
  "LN:kaiyuan": "\u5f00\u539f\u5e02",
  "YN:kaiyuan": "\u5f00\u8fdc\u5e02",
  "SC:kangding": "\u5eb7\u5b9a\u5e02",
  "FJ:kengyuan": "\u5751\u56ed\u9547",
  "LN:kuandian": "\u5bbd\u7538\u9547",
  "SD:kuiju": "\u594e\u805a\u8857\u9053",
  "YN:kunming": "\u6606\u660e\u5e02",
  "ZJ:kunyang": "\u6606\u9633\u9547",
  "GX:laibin": "\u6765\u5bbe\u5e02",
  "SD:laiwu": "\u83b1\u829c\u533a",
  "SD:laixi": "\u83b1\u897f\u5e02",
  "SD:laiyang": "\u83b1\u9633\u5e02",
  "SD:laizhou": "\u83b1\u5dde\u5e02",
  "HE:langfang": "\u5eca\u574a\u5e02",
  "HE:langfangshi": "\u5eca\u574a\u5e02",
  "HL:langxiang": "\u6717\u4e61\u9547",
  "SC:langzhong": "\u9606\u4e2d\u5e02",
  "HN:lanli": "\u5170\u91cc\u9547",
  "GZ:lantian": "\u84dd\u7530\u9547",
  "HL:lanxi": "\u5170\u897f\u53bf",
  "ZJ:lanxi": "\u5170\u6eaa\u5e02",
  "GS:lanzhou": "\u5170\u5dde\u5e02",
  "SD:laocheng": "\u8001\u57ce\u8857\u9053",
  "HB:laohekou": "\u8001\u6cb3\u53e3\u5e02",
  "GS:laojunmiao": "\u8001\u541b\u5e99\u9547",
  "GD:lecheng": "\u4e50\u57ce\u8857\u9053",
  "HN:leiyang": "\u8012\u9633\u5e02",
  "HN:lengshuijiang": "\u51b7\u6c34\u6c5f\u5e02",
  "HN:lengshuitan": "\u51b7\u6c34\u6ee9\u533a",
  "SC:leshan": "\u4e50\u5c71\u5e02",
  "ZJ:lianghu": "\u6881\u6e56\u8857\u9053",
  "SC:liangshanyizuzizhizhou": "\u51c9\u5c71\u5f5d\u65cf\u81ea\u6cbb\u5dde",
  "HN:liangyaping": "\u4e24\u4e2b\u576a\u9547",
  "GD:lianjiang": "\u5ec9\u6c5f\u5e02",
  "YN:lianran": "\u8fde\u7136\u8857\u9053",
  "LN:lianshan": "\u8fde\u5c71\u533a",
  "HN:lianyuan": "\u6d9f\u6e90\u5e02",
  "JS:lianyungang": "\u8fde\u4e91\u6e2f\u5e02",
  "GD:lianzhou": "\u8fde\u5dde\u5e02",
  "GX:lianzhou": "\u5ec9\u5dde\u9547",
  "TJ:lianzhuang": "\u5ec9\u5e84\u9547",
  "SD:liaocheng": "\u804a\u57ce\u5e02",
  "LN:liaoyang": "\u8fbd\u9633\u5e02",
  "JL:liaoyuan": "\u8fbd\u6e90\u5e02",
  "LN:liaozhong": "\u8fbd\u4e2d\u533a",
  "GD:licheng": "\u8354\u57ce\u8857\u9053",
  "HB:lichuan": "\u5229\u5ddd\u5e02",
  "YN:lijiang": "\u4e3d\u6c5f\u5e02",
  "YN:lincangshi": "\u4e34\u6ca7\u5e02",
  "HI:lincheng": "\u4e34\u57ce\u9547",
  "SX:linfen": "\u4e34\u6c7e\u5e02",
  "GX:lingcheng": "\u7075\u57ce\u8857\u9053",
  "HL:lingdong": "\u5cad\u4e1c\u533a",
  "LN:linghai": "\u51cc\u6d77\u5e02",
  "LN:lingyuan": "\u51cc\u6e90\u5e02",
  "ZJ:linhai": "\u4e34\u6d77\u5e02",
  "JL:linjiang": "\u4e34\u6c5f\u5e02",
  "HL:linkou": "\u6797\u53e3\u53bf",
  "ZJ:linping": "\u4e34\u5e73\u533a",
  "SC:linqiong": "\u4e34\u909b\u8857\u9053",
  "HE:linshui": "\u4e34\u6c34\u9547",
  "TJ:lintingkou": "\u6797\u4ead\u53e3\u9547",
  "SN:lintong": "\u4e34\u6f7c\u533a",
  "HE:linxi": "\u4e34\u897f\u53bf",
  "GS:linxiahuizuzizhizhou": "\u4e34\u590f\u56de\u65cf\u81ea\u6cbb\u5dde",
  "SD:linyi": "\u4e34\u6c82\u5e02",
  "JL:lishu": "\u68a8\u6811\u53bf",
  "ZJ:lishui": "\u4e3d\u6c34\u5e02",
  "JL:liuhe": "\u67f3\u6cb3\u53bf",
  "GZ:liupanshui": "\u516d\u76d8\u6c34\u5e02",
  "GX:liuzhoushi": "\u67f3\u5dde\u5e02",
  "HN:lixiqiao": "\u674e\u7199\u6865\u9547",
  "HL:longfeng": "\u9f99\u51e4\u533a",
  "SD:longgang": "\u9f99\u6e2f\u8857\u9053",
  "HL:longjiang": "\u9f99\u6c5f\u53bf",
  "JL:longjing": "\u9f99\u4e95\u5e02",
  "FJ:longmen": "\u9f99\u95e8\u9547",
  "GS:longnanshi": "\u9647\u5357\u5e02",
  "YN:longquan": "\u9f99\u6cc9\u8857\u9053",
  "HN:longtan": "\u9f99\u6f6d\u9547",
  "FJ:longyan": "\u9f99\u5ca9\u5e02",
  "HN:loudi": "\u5a04\u5e95\u5e02",
  "GZ:loushanguan": "\u5a04\u5c71\u5173\u8857\u9053",
  "AH:lu\u2019an": "\u516d\u5b89\u5e02",
  "HE:luancheng": "\u683e\u57ce\u533a",
  "GD:lubu": "\u7984\u6b65\u9547",
  "AH:lucheng": "\u5e90\u57ce\u9547",
  "GD:luocheng": "\u7f57\u57ce\u8857\u9053",
  "SC:luocheng": "\u96d2\u57ce\u8857\u9053",
  "HN:luojiu": "\u7f57\u65e7\u9547",
  "GX:luorong": "\u96d2\u5bb9\u9547",
  "FJ:luoyang": "\u87ba\u9633\u9547",
  "GD:luoyang": "\u6d1b\u9633\u9547",
  "HA:luoyang": "\u6d1b\u9633\u5e02",
  "ZJ:luqiao": "\u8def\u6865\u533a",
  "FJ:luxia": "\u7089\u4e0b\u9547",
  "HN:luyang": "\u5362\u9633\u9547",
  "SC:luzhou": "\u6cf8\u5dde\u5e02",
  "HN:ma\u2019an": "\u9a6c\u978d\u9547",
  "GD:maba": "\u9a6c\u575d\u9547",
  "YN:mabai": "\u9a6c\u767d\u9547",
  "HB:macheng": "\u9ebb\u57ce\u5e02",
  "YN:majie": "\u9a6c\u8857\u8857\u9053",
  "NM:manzhouli": "\u6ee1\u6d32\u91cc\u5e02",
  "GD:maoming": "\u8302\u540d\u5e02",
  "GZ:maoping": "\u8305\u576a\u9547",
  "HN:maoping": "\u8305\u576a\u9547",
  "FJ:maping": "\u9a6c\u576a\u9547",
  "GS:mawu": "\u9a6c\u575e\u9547",
  "TJ:meichang": "\u6885\u5382\u9547",
  "JL:meihekou": "\u6885\u6cb3\u53e3\u5e02",
  "SC:meishanshi": "\u7709\u5c71\u5e02",
  "GD:meizhou": "\u6885\u5dde\u5e02",
  "SD:mengyin": "\u8499\u9634\u53bf",
  "BJ:mentougou": "\u95e8\u5934\u6c9f\u533a",
  "SC:mianyang": "\u7ef5\u9633\u5e02",
  "FJ:min\u2019an": "\u6c11\u5b89\u8857\u9053",
  "HA:minggang": "\u660e\u6e2f\u8857\u9053",
  "AH:mingguang": "\u660e\u5149\u5e02",
  "HL:mingshui": "\u660e\u6c34\u53bf",
  "SD:mingshui": "\u660e\u6c34\u8857\u9053",
  "JL:mingyue": "\u660e\u6708\u9547",
  "JL:minzhu": "\u6c11\u4e3b\u8857\u9053",
  "HL:mishan": "\u5bc6\u5c71\u5e02",
  "YN:miyang": "\u5f25\u9633\u8857\u9053",
  "SD:mizhou": "\u5bc6\u5dde\u8857\u9053",
  "NM:mositai": "\u83ab\u65af\u53f0\u8857\u9053",
  "HL:mudanjiang": "\u7261\u4e39\u6c5f\u5e02",
  "NM:mujiayingzi": "\u7a46\u5bb6\u8425\u5b50\u9547",
  "HI:nada": "\u90a3\u5927\u9547",
  "JX:nanchang": "\u5357\u660c\u5e02",
  "SC:nanchong": "\u5357\u5145\u5e02",
  "SD:nanding": "\u5357\u5b9a\u9547",
  "GX:nandu": "\u5357\u6e21\u9547",
  "GD:nanfeng": "\u5357\u4e30\u9547",
  "HE:nangong": "\u5357\u5bab\u5e02",
  "JS:nanjing": "\u5357\u4eac\u5e02",
  "SC:nanlong": "\u5357\u9686\u8857\u9053",
  "SD:nanma": "\u5357\u9ebb\u8857\u9053",
  "HN:nanmuping": "\u6960\u6728\u576a\u9547",
  "GX:nanning": "\u5357\u5b81\u5e02",
  "LN:nanpiao": "\u5357\u7968\u533a",
  "FJ:nanping": "\u5357\u5e73\u5e02",
  "LN:nantai": "\u5357\u53f0\u9547",
  "JS:nantong": "\u5357\u901a\u5e02",
  "HA:nanyang": "\u5357\u9633\u5e02",
  "HN:nanzhou": "\u5357\u6d32\u9547",
  "HL:nehe": "\u8bb7\u6cb3\u5e02",
  "SC:neijiang": "\u5185\u6c5f\u5e02",
  "FJ:neikeng": "\u5185\u5751\u9547",
  "HL:nenjiang": "\u5ae9\u6c5f\u5e02",
  "HL:nianzishan": "\u78be\u5b50\u5c71\u533a",
  "HL:ning\u2019an": "\u5b81\u5b89\u5e02",
  "ZJ:ningbo": "\u5b81\u6ce2\u5e02",
  "FJ:ningde": "\u5b81\u5fb7\u5e02",
  "SD:ninghai": "\u5b81\u6d77\u8857\u9053",
  "ZJ:ninghai": "\u5b81\u6d77\u53bf",
  "SD:ningyang": "\u5b81\u9633\u53bf",
  "YN:nujianglisuzuzizhizhou": "\u6012\u6c5f\u5088\u50f3\u65cf\u81ea\u6cbb\u5dde",
  "FJ:pandu": "\u6f58\u6e21\u9547",
  "LN:panjinshi": "\u76d8\u9526\u5e02",
  "LN:panshan": "\u76d8\u5c71\u53bf",
  "SC:panzhihua": "\u6500\u679d\u82b1\u5e02",
  "TJ:panzhuang": "\u6f58\u5e84\u9547",
  "HE:pengcheng": "\u5f6d\u57ce\u9547",
  "HA:pingdingshan": "\u5e73\u9876\u5c71\u5e02",
  "SD:pingdu": "\u5e73\u5ea6\u5e02",
  "GZ:pingjiang": "\u5e73\u6c5f\u9547",
  "GS:pingliang": "\u5e73\u51c9\u5e02",
  "GX:pingnan": "\u5e73\u5357\u53bf",
  "GD:pingshan": "\u576a\u5c71\u533a",
  "JX:pingxiang": "\u840d\u4e61\u5e02",
  "SD:pingyi": "\u5e73\u9091\u53bf",
  "SD:pingyin": "\u5e73\u9634\u53bf",
  "NM:pingzhuang": "\u5e73\u5e84\u9547",
  "JX:poyang": "\u9131\u9633\u53bf",
  "FJ:pucheng": "\u6d66\u57ce\u53bf",
  "SC:puji": "\u666e\u6d4e\u9547",
  "HN:pukou": "\u6d66\u53e3\u9547",
  "LN:pulandian": "\u666e\u5170\u5e97\u533a",
  "GX:pumiao": "\u84b2\u5e99\u9547",
  "GD:puning": "\u666e\u5b81\u5e02",
  "FJ:putian": "\u8386\u7530\u5e02",
  "ZJ:puyang": "\u6d66\u9633\u9547",
  "HA:puyangshi": "\u6fee\u9633\u5e02",
  "HN:qiancheng": "\u9ed4\u57ce\u9547",
  "HB:qianjiang": "\u6f5c\u6c5f\u5e02",
  "HN:qianzhou": "\u4e7e\u5dde\u8857\u9053",
  "HN:qiaojiang": "\u6865\u6c5f\u9547",
  "FJ:qibu": "\u8d77\u6b65\u9547",
  "SD:qingdao": "\u9752\u5c9b\u5e02",
  "HL:qinggang": "\u9752\u5188\u53bf",
  "TJ:qingguang": "\u9752\u5149\u9547",
  "HA:qingping": "\u6e05\u5e73\u8857\u9053",
  "HB:qingquan": "\u6e05\u6cc9\u9547",
  "HN:qingxi": "\u6e05\u6eaa\u9547",
  "SD:qingyang": "\u6e05\u6d0b\u8857\u9053",
  "GS:qingyangshi": "\u5e86\u9633\u5e02",
  "GD:qingyuan": "\u6e05\u8fdc\u5e02",
  "SD:qingzhou": "\u9752\u5dde\u5e02",
  "HE:qinhuangdao": "\u79e6\u7687\u5c9b\u5e02",
  "GX:qinzhou": "\u94a6\u5dde\u5e02",
  "HI:qionghai": "\u743c\u6d77\u5e02",
  "HN:qionghu": "\u743c\u6e56\u8857\u9053",
  "HI:qiongshan": "\u743c\u5c71\u533a",
  "FJ:quanzhou": "\u6cc9\u5dde\u5e02",
  "SD:qufu": "\u66f2\u961c\u5e02",
  "YN:qujing": "\u66f2\u9756\u5e02",
  "ZJ:quzhou": "\u8862\u5dde\u5e02",
  "HE:renqiu": "\u4efb\u4e18\u5e02",
  "XZ:rikaze": "\u65e5\u5580\u5219\u5e02",
  "SD:rizhao": "\u65e5\u7167\u5e02",
  "HA:runing": "\u6c5d\u5b81\u8857\u9053",
  "HN:ruoshui": "\u82e5\u6c34\u9547",
  "HA:ruzhou": "\u6c5d\u5dde\u5e02",
  "XZ:saga": "\u8428\u560e\u53bf",
  "GZ:sanchahe": "\u4e09\u5c94\u6cb3\u9547",
  "GZ:sangmu": "\u6851\u6728\u9547",
  "TJ:sangzi": "\u6851\u6893\u9547",
  "FJ:sanming": "\u4e09\u660e\u5e02",
  "HI:sansha": "\u4e09\u6c99\u5e02",
  "GD:sanshui": "\u4e09\u6c34\u533a",
  "HI:sanya": "\u4e09\u4e9a\u5e02",
  "XJ:shache": "\u838e\u8f66\u53bf",
  "HE:shahecheng": "\u6c99\u6cb3\u57ce\u9547",
  "FJ:shajiang": "\u6c99\u6c5f\u9547",
  "SD:shancheng": "\u5c71\u57ce\u8857\u9053",
  "TJ:shangcang": "\u4e0a\u4ed3\u9547",
  "FJ:shangjie": "\u4e0a\u8857\u9547",
  "HN:shangmei": "\u4e0a\u6885\u8857\u9053",
  "HA:shangqiu": "\u5546\u4e18\u5e02",
  "JX:shangrao": "\u4e0a\u9976\u5e02",
  "ZJ:shangyu": "\u4e0a\u865e\u533a",
  "HL:shangzhi": "\u5c1a\u5fd7\u5e02",
  "HE:shanhaiguan": "\u5c71\u6d77\u5173\u533a",
  "HN:shanmen": "\u5c71\u95e8\u9547",
  "SD:shanting": "\u5c71\u4ead\u533a",
  "GD:shantou": "\u6c55\u5934\u5e02",
  "GD:shanwei": "\u6c55\u5c3e\u5e02",
  "FJ:shanxia": "\u5c71\u971e\u9547",
  "FJ:shanyang": "\u6749\u6d0b\u9547",
  "GD:shaoguan": "\u97f6\u5173\u5e02",
  "FJ:shaowu": "\u90b5\u6b66\u5e02",
  "ZJ:shaoxing": "\u7ecd\u5174\u5e02",
  "GD:shaping": "\u6c99\u576a\u9547",
  "SD:shazikou": "\u6c99\u5b50\u53e3\u8857\u9053",
  "SD:shengli": "\u80dc\u5229\u8857\u9053",
  "ZJ:shenjiamen": "\u6c88\u5bb6\u95e8\u8857\u9053",
  "LN:shenyang": "\u6c88\u9633\u5e02",
  "NM:shiguai": "\u77f3\u62d0\u533a",
  "XJ:shihezi": "\u77f3\u6cb3\u5b50\u5e02",
  "HN:shijiang": "\u77f3\u6c5f\u9547",
  "HE:shijiazhuang": "\u77f3\u5bb6\u5e84\u5e02",
  "HE:shijiazhuangshi": "\u77f3\u5bb6\u5e84\u5e02",
  "FJ:shijing": "\u77f3\u4e95\u9547",
  "YN:shilin": "\u77f3\u6797\u8857\u9053",
  "GD:shilong": "\u77f3\u9f99\u9547",
  "FJ:shima": "\u77f3\u7801\u8857\u9053",
  "GZ:shiqian": "\u77f3\u9621\u53bf",
  "GD:shiqiao": "\u5e02\u6865\u8857\u9053",
  "NX:shitanjing": "\u77f3\u70ad\u4e95\u8857\u9053",
  "GD:shiwan": "\u77f3\u6e7e\u8857\u9053",
  "GD:shixing": "\u59cb\u5174\u53bf",
  "HB:shiyan": "\u5341\u5830\u5e02",
  "SD:shizilu": "\u5341\u5b57\u8def\u8857\u9053",
  "NX:shizuishan": "\u77f3\u5634\u5c71\u5e02",
  "SD:shouguang": "\u5bff\u5149\u5e02",
  "HL:shuangcheng": "\u53cc\u57ce\u533a",
  "SC:shuanghejiedao": "\u53cc\u6cb3\u9547",
  "HN:shuangjiang": "\u53cc\u6c5f\u9547",
  "FJ:shuangxi": "\u53cc\u6eaa\u8857\u9053",
  "JL:shuangyang": "\u53cc\u9633\u533a",
  "HL:shuangyashan": "\u53cc\u9e2d\u5c71\u5e02",
  "HN:shuiche": "\u6c34\u8f66\u9547",
  "FJ:shuikou": "\u6c34\u53e3\u9547",
  "JL:shulan": "\u8212\u5170\u5e02",
  "BJ:shunyi": "\u987a\u4e49\u533a",
  "SX:shuozhou": "\u6714\u5dde\u5e02",
  "HN:simenqian": "\u53f8\u95e8\u524d\u9547",
  "JL:siping": "\u56db\u5e73\u5e02",
  "XJ:sishilichengzi": "\u56db\u5341\u91cc\u57ce\u5b50\u9547",
  "SD:sishui": "\u6cd7\u6c34\u53bf",
  "SH:songjiang": "\u677e\u6c5f\u533a",
  "JL:songjianghe": "\u677e\u6c5f\u6cb3\u9547",
  "GZ:songkan": "\u677e\u574e\u9547",
  "HE:songling": "\u677e\u5cad\u9547",
  "HA:songyang": "\u5d69\u9633\u8857\u9053",
  "JL:songyuan": "\u677e\u539f\u5e02",
  "HL:suifenhe": "\u7ee5\u82ac\u6cb3\u5e02",
  "HL:suihua": "\u7ee5\u5316\u5e02",
  "HL:suileng": "\u7ee5\u68f1\u53bf",
  "SC:suining": "\u9042\u5b81\u5e02",
  "AH:suixi": "\u6fc9\u6eaa\u53bf",
  "HB:suizhou": "\u968f\u5dde\u5e02",
  "LN:sujiatun": "\u82cf\u5bb6\u5c6f\u533a",
  "HA:suohe": "\u7d22\u6cb3\u8857\u9053",
  "JS:suqian": "\u5bbf\u8fc1\u5e02",
  "AH:suzhou": "\u5bbf\u5dde\u5e02",
  "JS:suzhou": "\u82cf\u5dde\u5e02",
  "AH:suzhoushi": "\u5bbf\u5dde\u5e02",
  "XJ:tacheng": "\u5854\u57ce\u5e02",
  "XJ:tachengdiqu": "\u5854\u57ce\u5730\u533a",
  "HL:tahe": "\u5854\u6cb3\u53bf",
  "SD:tai\u2019an": "\u6cf0\u5b89\u5e02",
  "SC:taihe": "\u592a\u548c\u8857\u9053",
  "HL:tailai": "\u6cf0\u6765\u53bf",
  "SC:taiping": "\u592a\u5e73\u8857\u9053",
  "GD:taishan": "\u53f0\u5c71\u5e02",
  "SX:taiyuan": "\u592a\u539f\u5e02",
  "ZJ:taizhou": "\u53f0\u5dde\u5e02",
  "JS:taizhou": "\u6cf0\u5dde\u5e02",
  "HN:tangjiafang": "\u5510\u5bb6\u574a\u9547",
  "HE:tangjiazhuang": "\u5510\u5bb6\u5e84\u8857\u9053",
  "FJ:tangkou": "\u68e0\u53e3\u9547",
  "GD:tangping": "\u5858\u576a\u9547",
  "HE:tangshan": "\u5510\u5c71\u5e02",
  "HE:tangshanshi": "\u5510\u5c71\u5e02",
  "AH:tangzhai": "\u5510\u5be8\u9547",
  "FJ:tantou": "\u6f6d\u5934\u9547",
  "HN:tanwan": "\u6f6d\u6e7e\u9547",
  "SD:taozhuang": "\u9676\u5e84\u9547",
  "SC:tianpeng": "\u5929\u5f6d\u8857\u9053",
  "GS:tianshui": "\u5929\u6c34\u5e02",
  "HL:tieli": "\u94c1\u529b\u5e02",
  "LN:tieling": "\u94c1\u5cad\u5e02",
  "LN:tielingshi": "\u94c1\u5cad\u5e02",
  "GZ:tingdong": "\u505c\u6d1e\u9547",
  "FJ:tingjiang": "\u4ead\u6c5f\u9547",
  "SC:tongchuan": "\u901a\u5ddd\u533a",
  "SN:tongchuanshi": "\u94dc\u5ddd\u5e02",
  "GZ:tonggu": "\u94dc\u9f13\u9547",
  "JL:tonghua": "\u901a\u5316\u5e02",
  "JL:tonghuashi": "\u901a\u5316\u5e02",
  "NM:tongliao": "\u901a\u8fbd\u5e02",
  "GZ:tongren": "\u94dc\u4ec1\u5e02",
  "HN:tongwan": "\u94dc\u6e7e\u9547",
  "BJ:tongzhou": "\u901a\u5dde\u533a",
  "JL:tumen": "\u56fe\u4eec\u5e02",
  "HN:tuokou": "\u6258\u53e3\u9547",
  "FJ:tuzhai": "\u6d82\u5be8\u9547",
  "HA:wacheng": "\u5a32\u57ce\u8857\u9053",
  "LN:wafangdian": "\u74e6\u623f\u5e97\u5e02",
  "HL:wangkui": "\u671b\u594e\u53bf",
  "JL:wangqing": "\u6c6a\u6e05\u53bf",
  "HI:wanning": "\u4e07\u5b81\u5e02",
  "HN:wantouqiao": "\u6e7e\u5934\u6865\u9547",
  "SD:weifang": "\u6f4d\u574a\u5e02",
  "SD:weihai": "\u5a01\u6d77\u5e02",
  "SN:weinan": "\u6e2d\u5357\u5e02",
  "HI:wenchang": "\u6587\u660c\u5e02",
  "YN:wenlan": "\u6587\u6f9c\u8857\u9053",
  "ZJ:wenling": "\u6e29\u5cad\u5e02",
  "NM:wenquan": "\u6e29\u6cc9\u8857\u9053",
  "YN:wenshanzhuangzumiaozuzizhizhou": "\u6587\u5c71\u58ee\u65cf\u82d7\u65cf\u81ea\u6cbb\u5dde",
  "SD:wenshang": "\u6c76\u4e0a\u53bf",
  "GZ:wenshui": "\u6e29\u6c34\u9547",
  "HN:wenxing": "\u6587\u661f\u8857\u9053",
  "ZJ:wenzhou": "\u6e29\u5dde\u5e02",
  "HL:wuchang": "\u4e94\u5e38\u5e02",
  "AH:wucheng": "\u65e0\u57ce\u9547",
  "GD:wuchuan": "\u5434\u5ddd\u5e02",
  "NM:wuda": "\u4e4c\u8fbe\u533a",
  "NM:wuhai": "\u4e4c\u6d77\u5e02",
  "HB:wuhan": "\u6b66\u6c49\u5e02",
  "AH:wuhu": "\u829c\u6e56\u5e02",
  "HN:wulingyuan": "\u6b66\u9675\u6e90\u533a",
  "AH:wusong": "\u4e94\u677e\u9547",
  "GS:wuwei": "\u6b66\u5a01\u5e02",
  "HN:wuxi": "\u6d6f\u6eaa\u8857\u9053",
  "JS:wuxi": "\u65e0\u9521\u5e02",
  "HB:wuxue": "\u6b66\u7a74\u5e02",
  "HN:wuyang": "\u6b66\u9633\u9547",
  "FJ:wuyishan": "\u6b66\u5937\u5c71\u5e02",
  "NX:wuzhong": "\u5434\u5fe0\u5e02",
  "GX:wuzhou": "\u68a7\u5dde\u5e02",
  "FJ:xiahu": "\u4e0b\u6d52\u9547",
  "GZ:xiajiang": "\u4e0b\u6c5f\u9547",
  "SC:xialiang": "\u4e0b\u4e24\u9547",
  "FJ:xiamen": "\u53a6\u95e8\u5e02",
  "FJ:xiancun": "\u54b8\u6751\u9547",
  "HN:xiangtan": "\u6e58\u6f6d\u5e02",
  "HN:xiangxitujiazumiaozuzizhizhou": "\u6e58\u897f\u571f\u5bb6\u65cf\u82d7\u65cf\u81ea\u6cbb\u5dde",
  "HN:xiangxiang": "\u6e58\u4e61\u5e02",
  "HB:xiangyang": "\u8944\u9633\u5e02",
  "FJ:xiangyun": "\u7fd4\u4e91\u9547",
  "ZJ:xianju": "\u4ed9\u5c45\u53bf",
  "HB:xianning": "\u54b8\u5b81\u5e02",
  "SC:xiantan": "\u5148\u6ee9\u9547",
  "HB:xiantao": "\u4ed9\u6843\u5e02",
  "HN:xianxi": "\u4ed9\u6eaa\u9547",
  "SN:xianyang": "\u54b8\u9633\u5e02",
  "HB:xiaogan": "\u5b5d\u611f\u5e02",
  "HN:xiaoshajiang": "\u5c0f\u6c99\u6c5f\u9547",
  "ZJ:xiaoshan": "\u8427\u5c71\u533a",
  "GZ:xiaoweizhai": "\u5c0f\u56f4\u5be8\u8857\u9053",
  "SD:xiazhuang": "\u590f\u5e84\u8857\u9053",
  "FJ:xibing": "\u6eaa\u67c4\u9547",
  "SC:xichang": "\u897f\u660c\u5e02",
  "TJ:xiditou": "\u897f\u5824\u5934\u9547",
  "LN:xifeng": "\u897f\u4e30\u53bf",
  "HB:xihe": "\u897f\u6cb3\u9547",
  "FJ:ximei": "\u6eaa\u7f8e\u8857\u9053",
  "FJ:xinan": "\u6eaa\u5357\u9547",
  "HA:xincheng": "\u65b0\u57ce\u8857\u9053",
  "HB:xindi": "\u65b0\u5824\u8857\u9053",
  "FJ:xindian": "\u65b0\u5e97\u9547",
  "SD:xindian": "\u8f9b\u5e97\u8857\u9053",
  "LN:xingcheng": "\u5174\u57ce\u5e02",
  "JL:xinglongshan": "\u5174\u9686\u5c71\u9547",
  "GD:xingning": "\u5174\u5b81\u5e02",
  "HE:xingtai": "\u90a2\u53f0\u5e02",
  "HA:xinhualu": "\u65b0\u534e\u8def\u8857\u9053",
  "GD:xinhui": "\u65b0\u4f1a\u533a",
  "QH:xining": "\u897f\u5b81\u5e02",
  "HE:xinji": "\u8f9b\u96c6\u5e02",
  "TJ:xinkaikou": "\u65b0\u5f00\u53e3\u9547",
  "LN:xinmin": "\u65b0\u6c11\u5e02",
  "HL:xinqing": "\u65b0\u9752\u9547",
  "SD:xintai": "\u65b0\u6cf0\u5e02",
  "HA:xinxiang": "\u65b0\u4e61\u5e02",
  "HA:xinxiangshi": "\u65b0\u4e61\u5e02",
  "LN:xinxing": "\u65b0\u5174\u8857\u9053",
  "HA:xinyang": "\u4fe1\u9633\u5e02",
  "GD:xinyi": "\u4fe1\u5b9c\u5e02",
  "JX:xinyu": "\u65b0\u4f59\u5e02",
  "XJ:xinyuan": "\u65b0\u6e90\u53bf",
  "GZ:xinzhan": "\u65b0\u7ad9\u9547",
  "SX:xinzhi": "\u8f9b\u7f6e\u9547",
  "HB:xinzhou": "\u65b0\u6d32\u533a",
  "SX:xinzhou": "\u5ffb\u5dde\u5e02",
  "GD:xiongzhou": "\u96c4\u5dde\u8857\u9053",
  "GZ:xishan": "\u897f\u5c71\u9547",
  "HB:xiulin": "\u7ee3\u6797\u8857\u9053",
  "HI:xiuying": "\u79c0\u82f1\u533a",
  "HN:xixi": "\u6d17\u6eaa\u9547",
  "HA:xixiang": "\u897f\u5411\u9547",
  "HN:xiyan": "\u897f\u5ca9\u9547",
  "AH:xuanzhou": "\u5ba3\u5dde\u533a",
  "HA:xuchang": "\u8bb8\u660c\u5e02",
  "HA:xuchangshi": "\u8bb8\u660c\u5e02",
  "GD:xucheng": "\u5f90\u57ce\u8857\u9053",
  "GZ:xujiaba": "\u8bb8\u5bb6\u575d\u9547",
  "SC:xunchang": "\u5de1\u573a\u9547",
  "JS:xuzhou": "\u5f90\u5dde\u5e02",
  "HA:yakou": "\u57ad\u53e3\u8857\u9053",
  "JL:yanbianchaoxianzuzizhizhou": "\u5ef6\u8fb9\u671d\u9c9c\u65cf\u81ea\u6cbb\u5dde",
  "JS:yancheng": "\u76d0\u57ce\u5e02",
  "GD:yangchun": "\u9633\u6625\u5e02",
  "SD:yanggu": "\u9633\u8c37\u53bf",
  "FJ:yanghou": "\u6d0b\u540e\u9547",
  "GD:yangjiang": "\u9633\u6c5f\u5e02",
  "TJ:yangjinzhuang": "\u6768\u6d25\u5e84\u9547",
  "TJ:yangliuqing": "\u6768\u67f3\u9752\u9547",
  "SX:yangquan": "\u9633\u6cc9\u5e02",
  "GX:yangshuo": "\u9633\u6714\u53bf",
  "GZ:yangtou": "\u6f3e\u5934\u9547",
  "FJ:yangzhong": "\u6d0b\u4e2d\u8857\u9053",
  "JS:yangzhou": "\u626c\u5dde\u5e02",
  "JL:yanji": "\u5ef6\u5409\u5e02",
  "SC:yanjiang": "\u96c1\u6c5f\u533a",
  "SN:yanliang": "\u960e\u826f\u533a",
  "HN:yanmen": "\u5ca9\u95e8\u9547",
  "SD:yanta": "\u71d5\u5854\u8857\u9053",
  "SD:yantai": "\u70df\u53f0\u5e02",
  "JL:yantongshan": "\u70df\u7b52\u5c71\u9547",
  "SD:yanzhou": "\u5156\u5dde\u533a",
  "GX:yashan": "\u4e9a\u5c71\u9547",
  "SD:yatou": "\u5d16\u5934\u8857\u9053",
  "LN:yebaishou": "\u53f6\u67cf\u5bff\u8857\u9053",
  "SC:yibin": "\u5b9c\u5bbe\u5e02",
  "HB:yichang": "\u5b9c\u660c\u5e02",
  "HB:yicheng": "\u5b9c\u57ce\u5e02",
  "HL:yichun": "\u4f0a\u6625\u5e02",
  "JX:yichun": "\u5b9c\u6625\u5e02",
  "HA:yigou": "\u5b9c\u6c9f\u9547",
  "HL:yilan": "\u4f9d\u5170\u53bf",
  "HA:yima": "\u4e49\u9a6c\u5e02",
  "NX:yinchuan": "\u94f6\u5ddd\u5e02",
  "GD:yingcheng": "\u82f1\u57ce\u8857\u9053",
  "HA:yingchuan": "\u988d\u5ddd\u8857\u9053",
  "LN:yingkou": "\u8425\u53e3\u5e02",
  "FJ:yinglin": "\u82f1\u6797\u9547",
  "TJ:yinliu": "\u6d07\u6e9c\u9547",
  "SD:yinzhu": "\u9690\u73e0\u8857\u9053",
  "SD:yishui": "\u6c82\u6c34\u53bf",
  "ZJ:yiwu": "\u4e49\u4e4c\u5e02",
  "HN:yiyang": "\u76ca\u9633\u5e02",
  "CQ:yongchuan": "\u6c38\u5ddd\u533a",
  "HN:yongfeng": "\u6c38\u4e30\u8857\u9053",
  "FJ:yongning": "\u6c38\u5b81\u9547",
  "HN:yongzhou": "\u6c38\u5dde\u5e02",
  "TJ:youguzhuang": "\u5c24\u53e4\u5e84\u9547",
  "HL:youhao": "\u53cb\u597d\u533a",
  "SX:yuanping": "\u539f\u5e73\u5e02",
  "SC:yucheng": "\u96e8\u57ce\u533a",
  "SD:yucheng": "\u79b9\u57ce\u5e02",
  "SX:yuci": "\u6986\u6b21\u533a",
  "CQ:yudong": "\u9c7c\u6d1e\u8857\u9053",
  "HN:yueyang": "\u5cb3\u9633\u5e02",
  "HN:yueyangshi": "\u5cb3\u9633\u5e02",
  "GX:yulin": "\u7389\u6797\u5e02",
  "SN:yulinshi": "\u6986\u6797\u5e02",
  "SX:yuncheng": "\u8fd0\u57ce\u5e02",
  "GD:yunfu": "\u4e91\u6d6e\u5e02",
  "HA:yunyang": "\u4e91\u9633\u9547",
  "FJ:yushan": "\u7389\u5c71\u9547",
  "JL:yushu": "\u6986\u6811\u5e02",
  "QH:yushuzangzuzizhizhou": "\u7389\u6811\u85cf\u65cf\u81ea\u6cbb\u5dde",
  "HN:yutan": "\u7389\u6f6d\u8857\u9053",
  "YN:yuxi": "\u7389\u6eaa\u5e02",
  "SN:yuxia": "\u4f59\u4e0b\u8857\u9053",
  "ZJ:yuyao": "\u4f59\u59da\u5e02",
  "TJ:zaojiacheng": "\u9020\u7532\u57ce\u9547",
  "HB:zaoyang": "\u67a3\u9633\u5e02",
  "SD:zaozhuang": "\u67a3\u5e84\u5e02",
  "HN:zhaishimiaozudongzuxiang": "\u5be8\u5e02\u82d7\u65cf\u4f97\u65cf\u4e61",
  "NM:zhalantun": "\u624e\u5170\u5c6f\u5e02",
  "HN:zhangjiajie": "\u5f20\u5bb6\u754c\u5e02",
  "HE:zhangjiakou": "\u5f20\u5bb6\u53e3\u5e02",
  "HE:zhangjiakoushi": "\u5f20\u5bb6\u53e3\u5e02",
  "TJ:zhangjiawo": "\u5f20\u5bb6\u7a9d\u9547",
  "FJ:zhangwan": "\u6f33\u6e7e\u9547",
  "GS:zhangye": "\u5f20\u6396\u5e02",
  "GS:zhangyeshi": "\u5f20\u6396\u5e02",
  "FJ:zhangzhou": "\u6f33\u5dde\u5e02",
  "GD:zhanjiang": "\u6e5b\u6c5f\u5e02",
  "ZJ:zhaobaoshan": "\u62db\u5b9d\u5c71\u8857\u9053",
  "HL:zhaodong": "\u8087\u4e1c\u5e02",
  "HE:zhaogezhuang": "\u8d75\u5404\u5e84\u8857\u9053",
  "GD:zhaoqing": "\u8087\u5e86\u5e02",
  "YN:zhaotong": "\u662d\u901a\u5e02",
  "HL:zhaoyuan": "\u8087\u6e90\u53bf",
  "SD:zhaoyuan": "\u62db\u8fdc\u5e02",
  "HL:zhaozhou": "\u8087\u5dde\u53bf",
  "JL:zhengjiatun": "\u90d1\u5bb6\u5c6f\u8857\u9053",
  "HA:zhengzhou": "\u90d1\u5dde\u5e02",
  "JS:zhenjiang": "\u9547\u6c5f\u5e02",
  "JL:zhenlai": "\u9547\u8d49\u53bf",
  "HB:zhicheng": "\u679d\u57ce\u9547",
  "ZJ:zhicheng": "\u96c9\u57ce\u8857\u9053",
  "HB:zhijiang": "\u679d\u6c5f\u5e02",
  "SC:zhongba": "\u4e2d\u575d\u8857\u9053",
  "GZ:zhongchao": "\u4e2d\u6f6e\u9547",
  "FJ:zhongfang": "\u4e2d\u623f\u9547",
  "HN:zhongfang": "\u4e2d\u65b9\u53bf",
  "GD:zhongshan": "\u4e2d\u5c71\u5e02",
  "YN:zhongshu": "\u4e2d\u67a2\u8857\u9053",
  "NX:zhongwei": "\u4e2d\u536b\u5e02",
  "HB:zhongxiang": "\u949f\u7965\u5e02",
  "HN:zhongzhai": "\u4e2d\u5be8\u9547",
  "SD:zhoucheng": "\u5dde\u57ce\u8857\u9053",
  "SD:zhoucun": "\u5468\u6751\u533a",
  "HA:zhoukou": "\u5468\u53e3\u5e02",
  "ZJ:zhoushan": "\u821f\u5c71\u5e02",
  "LN:zhuanghe": "\u5e84\u6cb3\u5e02",
  "SD:zhuangyuan": "\u5e84\u56ed\u8857\u9053",
  "GD:zhuhai": "\u73e0\u6d77\u5e02",
  "ZJ:zhuji": "\u8bf8\u66a8\u5e02",
  "GZ:zhujiachang": "\u6731\u5bb6\u573a\u9547",
  "SH:zhujiajiao": "\u6731\u5bb6\u89d2\u9547",
  "HA:zhumadian": "\u9a7b\u9a6c\u5e97\u5e02",
  "HA:zhumadianshi": "\u9a7b\u9a6c\u5e97\u5e02",
  "HN:zhuzhou": "\u682a\u6d32\u5e02",
  "HN:zhuzhoushi": "\u682a\u6d32\u5e02",
  "SD:zibo": "\u6dc4\u535a\u5e02",
  "SC:zigong": "\u81ea\u8d21\u5e02",
  "HA:zijinglu": "\u7d2b\u8346\u8def\u8857\u9053",
  "SD:zoucheng": "\u90b9\u57ce\u5e02",
  "HE:zunhua": "\u9075\u5316\u5e02",
  "GZ:zunyi": "\u9075\u4e49\u5e02",
  // A few GeoNames aliases use a shortened or English suffix form. Keep
  // these explicit aliases so every commonly selectable Chinese city still
  // renders a Chinese label while its original value remains searchable.
  "XJ:aksu": "\u963f\u514b\u82cf\u5e02",
  "XJ:aksudiqu": "\u963f\u514b\u82cf\u5730\u533a",
  "XJ:altay": "\u963f\u52d2\u6cf0\u5e02",
  "XJ:altaydiqu": "\u963f\u52d2\u6cf0\u5730\u533a",
  "XJ:aral": "\u963f\u62c9\u5c14\u5e02",
  "NM:bayannur": "\u5df4\u5f66\u6dd6\u5c14\u5e02",
  "NM:bayannurshi": "\u5df4\u5f66\u6dd6\u5c14\u5e02",
  "SC:barkam": "\u9a6c\u5c14\u5eb7\u5e02",
  "SX:changzhi": "\u957f\u6cbb\u5e02",
  "LN:chaoyang": "\u671d\u9633\u5e02",
  "TW:changhua": "\u5f70\u5316\u53bf",
  "TW:chiayi": "\u5609\u4e49\u5e02",
  "GZ:duyun": "\u90fd\u5300\u5e02",
  "NM:erenhot": "\u4e8c\u8fde\u6d69\u7279\u5e02",
  "QH:golmud": "\u683c\u5c14\u6728\u5e02",
  "NM:hailar": "\u6d77\u62c9\u5c14\u533a",
  "XJ:hotan": "\u548c\u7530\u5e02",
  "JL:hunchun": "\u73f2\u6625\u5e02",
  "JX:jingdezhen": "\u666f\u5fb7\u9547\u5e02",
  "XJ:karamay": "\u514b\u62c9\u739b\u4f9d\u5e02",
  "XJ:kashgar": "\u5580\u4ec0\u5e02",
  "XJ:korla": "\u5e93\u5c14\u52d2\u5e02",
  "XJ:kuqa": "\u5e93\u8f66\u5e02",
  "YN:shangrila": "\u9999\u683c\u91cc\u62c9\u5e02",
  "XZ:qamdo": "\u660c\u90fd\u5e02",
  "HL:qiqihar": "\u9f50\u9f50\u54c8\u5c14\u5e02",
  "XJ:turpan": "\u5410\u9c81\u756a\u5e02",
  "NM:ulanhot": "\u4e4c\u5170\u6d69\u7279\u5e02",
  "NM:xilinhot": "\u9521\u6797\u6d69\u7279\u5e02",
  "GZ:weining": "\u5a01\u5b81\u53bf",
  "CQ:wanxian": "\u4e07\u5dde\u533a",
};

function cityDisplayName(city: GeoCity): string {
  if (city.countryCode !== 'CN') return city.name;
  const normalized = city.name.replace(/[\s-]/g, '').toLowerCase();
  return CHINA_CITY_LABELS_BY_STATE[`${city.stateCode}:${normalized}`]
    || CHINA_CITY_LABELS[city.name.replace(/[\s-]/g, '')]
    || city.name;
}

interface GeoSelectOption {
  value: string;
  label: string;
  searchText?: string;
}

interface SearchableGeoSelectProps {
  value: string;
  options: GeoSelectOption[];
  placeholder: string;
  emptyText: string;
  allowCustom?: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
}

const SearchableGeoSelect: React.FC<SearchableGeoSelectProps> = ({
  value, options, placeholder, emptyText, disabled, onChange,
  allowCustom = false,
}) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const selected = options.find(option => option.value === value);
  const displayValue = selected?.label || value;
  const vrfs = options.map(option => ({ id: option.value, vrf_name: option.label }));
  const filteredOptions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return options;
    return options.filter(option => `${option.label} ${option.value} ${option.searchText || ''}`.toLocaleLowerCase().includes(normalized));
  }, [options, query]);

  const vrfOptions = useMemo(
    () => [{ value: '', label: '默认', labelEn: '(default)' }, ...vrfs.map(v => ({ value: v.id, label: v.vrf_name, labelEn: v.vrf_name }))],
    [vrfs]
  );

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [open]);

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
    setQuery('');
  };

  return (
    <div ref={rootRef} className="relative">
      <div className={`flex items-center rounded-xl border bg-white transition-all ${open ? 'border-[#06b6d4]/60 ring-2 ring-[#06b6d4]/10' : 'border-black/10'} ${disabled ? 'bg-slate-50' : ''}`}>
        <Search size={14} className="ml-3 shrink-0 text-black/35" />
        <input
          value={open ? query : displayValue}
          placeholder={open ? '输入名称或拼音搜索…' : placeholder}
          disabled={disabled}
          onFocus={() => { setOpen(true); setQuery(''); }}
          onChange={event => { setOpen(true); setQuery(event.target.value); }}
          onKeyDown={event => {
            if (event.key === 'Escape') { setOpen(false); setQuery(''); }
            if (event.key === 'Enter' && (filteredOptions[0] || (allowCustom && query.trim()))) {
              choose(filteredOptions[0]?.value || query.trim());
            }
          }}
          className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm text-[#164e63] outline-none disabled:cursor-not-allowed disabled:text-black/35"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => { setOpen(previous => !previous); setQuery(''); }}
          className="px-3 py-2 text-black/35 hover:text-[#0891b2] disabled:cursor-not-allowed"
          aria-label="打开选项"
        >
          <span className="text-xs">⌄</span>
        </button>
      </div>
      {open && !disabled && (
        <div className="absolute left-0 right-0 top-[calc(100%+6px)] z-[120] max-h-60 overflow-y-auto rounded-xl border border-black/10 bg-white p-1.5 shadow-xl">
          <button type="button" onClick={() => choose('')} className={`w-full rounded-lg px-3 py-2 text-left text-xs transition-colors ${!value ? 'bg-cyan-50 text-cyan-700' : 'text-black/50 hover:bg-slate-50'}`}>
            {placeholder}
          </button>
          {filteredOptions.map(option => (
            <button
              type="button"
              key={`${option.value}-${option.label}`}
              onClick={() => choose(option.value)}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors ${option.value === value ? 'bg-cyan-50 text-cyan-700' : 'text-[#164e63] hover:bg-slate-50'}`}
            >
              <span className="truncate">{option.label}</span>
              {option.value === value && <Check size={14} className="shrink-0" />}
            </button>
          ))}
          {allowCustom && query.trim() && !filteredOptions.some(option => option.value.toLocaleLowerCase() === query.trim().toLocaleLowerCase()) && (
            <button type="button" onClick={() => choose(query.trim())} className="mt-1 w-full rounded-lg border-t border-black/5 px-3 py-2 text-left text-xs text-cyan-700 hover:bg-cyan-50">
              使用“{query.trim()}”作为自定义值
            </button>
          )}
          {!filteredOptions.length && <div className="px-3 py-3 text-xs text-black/40">{emptyText}</div>}
        </div>
      )}
    </div>
  );
};

function matchesGeoValue(value: string, ...candidates: string[]): boolean {
  const normalized = value.trim().toLowerCase();
  return Boolean(normalized) && candidates.some(candidate => candidate.trim().toLowerCase() === normalized);
}

const CHINA_LEGACY_COUNTRY_VALUES = new Set(['中国', 'China', 'CN', '台湾', 'Taiwan', 'TW', '香港', 'Hong Kong', 'HK', '澳门', 'Macau', 'MO']);

function splitVlanValues(value: unknown, separator: RegExp = /[;\n]+/): string[] {
  if (Array.isArray(value)) return value.flatMap(item => splitVlanValues(item, separator));
  const text = String(value ?? '').trim();
  if (!text) return [];
  return text.split(separator).map(item => item.trim()).filter(Boolean);
}

const CmdbManagementTab: React.FC<Props> = ({ language, cmdbPage, currentUser }) => {
  const zh = language !== 'en';
  const navigate = useNavigate();
  const [tab, setTab] = useState<EntityKey>((cmdbPage as EntityKey) || 'credentials');

  useEffect(() => {
    if (cmdbPage) {
      setTab(cmdbPage as EntityKey);
    }
  }, [cmdbPage]);
  const [rows, setRows] = useState<any[]>([]);
  const [sites, setSites] = useState<any[]>([]);
  const [vrfs, setVrfs] = useState<any[]>([]);
  const [vlanCatalog, setVlanCatalog] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [interfaceSyncing, setInterfaceSyncing] = useState(false);
  const [interfaceJobStatus, setInterfaceJobStatus] = useState<any | null>(null);
  const interfaceTerminalHandledRef = useRef<string | null>(null);
  const loadRequestRef = useRef(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [credentialJobStatus, setCredentialJobStatus] = useState<any | null>(null);
  const [credentialJobDetailsOpen, setCredentialJobDetailsOpen] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [visiblePasswordFields, setVisiblePasswordFields] = useState<Record<string, boolean>>({});
  const [credentialDeviceDetails, setCredentialDeviceDetails] = useState<Record<string, any[]>>({});
  const [expandedCredentialDevices, setExpandedCredentialDevices] = useState<Record<string, boolean>>({});
  const [credentialDeviceLoading, setCredentialDeviceLoading] = useState<Record<string, boolean>>({});
  const [revealedCredentialSecret, setRevealedCredentialSecret] = useState<{ id: string; type: 'password' | 'enable_password'; secret: string } | null>(null);
  const [credentialSecretLoading, setCredentialSecretLoading] = useState<string | null>(null);
  const [credentialSecretCopied, setCredentialSecretCopied] = useState(false);
  const [bindingModal, setBindingModal] = useState<{ credentialId: string; credentialName: string; deviceId: string; deviceName: string; bindingRole: 'normal' | 'admin' } | null>(null);
  const [bindingAction, setBindingAction] = useState<'replace' | 'unbind'>('replace');
  const [replacementCredentialId, setReplacementCredentialId] = useState('');
  const [bindingSaving, setBindingSaving] = useState(false);
  const [form, setForm] = useState<Record<string, any>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [confirmDelete, setConfirmDelete] = useState<any | null>(null);
  const [siteReplacementId, setSiteReplacementId] = useState('');
  const [siteDeleteError, setSiteDeleteError] = useState('');
  const [geoCatalog, setGeoCatalog] = useState<GeoCatalog | null>(null);
  const [geoCityCache, setGeoCityCache] = useState<Record<string, GeoCity[]>>({});
  const [geoDistrictCache, setGeoDistrictCache] = useState<Record<string, GeoDistrict[]>>({});
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoCityLoading, setGeoCityLoading] = useState(false);
  const [geoError, setGeoError] = useState('');
  const [geoCityError, setGeoCityError] = useState('');
  const [search, setSearch] = useState('');
  const [vlanSiteFilter, setVlanSiteFilter] = useState('');
  const [vlanTreeCollapsed, setVlanTreeCollapsed] = useState(false);
  const [vlanScopeTree, setVlanScopeTree] = useState<any[]>([]);
  const [expandedVlanTree, setExpandedVlanTree] = useState<Record<string, boolean>>({ root: true });
  const [vlanTreeBranch, setVlanTreeBranch] = useState<{ site_id?: string; asset_type?: string; device_category?: string; device_role?: string }>({});
  const [vlanStatusFilter, setVlanStatusFilter] = useState('all');
  const [vlanListMeta, setVlanListMeta] = useState({
    total: 0,
    page: 1,
    page_size: 10,
    summary: { total: 0, gateways: 0, arp: 0, mac: 0, unbound: 0 },
    site_summary: [] as Array<{ key: string; label: string; count: number }>,
  });
  const [vlanExporting, setVlanExporting] = useState(false);
  const [credentialExporting, setCredentialExporting] = useState(false);
  const [credentialTemplateDownloading, setCredentialTemplateDownloading] = useState(false);
  const [vlanDetailRow, setVlanDetailRow] = useState<any | null>(null);
  const [expandedVlans, setExpandedVlans] = useState<Record<string, boolean>>({});
  const [interfaceDeviceFilter, setInterfaceDeviceFilter] = useState<string>('');
  const [expandedInterfaceDevices, setExpandedInterfaceDevices] = useState<Record<string, boolean>>({});
  const [interfacePage, setInterfacePage] = useState(1);
  const [interfacePageSize, setInterfacePageSize] = useState(20);
  const [interfaceListMeta, setInterfaceListMeta] = useState({
    total: 0,
    summary: { total: 0, with_ip: 0, oper_up: 0, with_links: 0 },
    device_options: [] as Array<{ value: string; label: string }>,
  });
  const [genericListMeta, setGenericListMeta] = useState({ total: 0, page: 1, page_size: 20 });
  const readOnlyTabs = useMemo(() => new Set<EntityKey>(['devices', 'interfaces']), []);
  const isReadOnlyTab = readOnlyTabs.has(tab);
  const isAdministrator = currentUser?.role === 'Administrator';

  const interfaceStats = useMemo(() => {
    if (tab !== 'interfaces') return { total: 0, withIp: 0, operUp: 0, withLinks: 0 };
    if (interfaceListMeta.total > 0) {
      return {
        total: interfaceListMeta.summary.total || interfaceListMeta.total,
        withIp: interfaceListMeta.summary.with_ip || 0,
        operUp: interfaceListMeta.summary.oper_up || 0,
        withLinks: interfaceListMeta.summary.with_links || 0,
      };
    }
    let total = rows.length;
    let withIp = 0;
    let operUp = 0;
    let withLinks = 0;
    rows.forEach(r => {
      const hasIp = Boolean(r.interface_ip || (r.ip_count && Number(r.ip_count) > 0));
      if (hasIp) withIp++;
      if (r.oper_status === 'up') operUp++;
      if (r.link_count && Number(r.link_count) > 0) withLinks++;
    });
    return { total, withIp, operUp, withLinks };
  }, [interfaceListMeta, rows, tab]);

  const interfaceDeviceOptions = useMemo(() => {
    if (tab !== 'interfaces') return [];
    if (interfaceListMeta.device_options.length > 0) return interfaceListMeta.device_options;
    const deviceMap = new Map<string, string>();
    rows.forEach(r => {
      if (r.device_id && r.device_hostname) {
        deviceMap.set(r.device_id, r.device_hostname);
      }
    });
    return Array.from(deviceMap.entries()).map(([id, name]) => ({ value: id, label: name }));
  }, [interfaceListMeta.device_options, rows, tab]);

  // Pagination states
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [siteImportOpen, setSiteImportOpen] = useState(false);
  const [siteImportFileName, setSiteImportFileName] = useState('');
  const [siteImportRows, setSiteImportRows] = useState<SiteImportRow[]>([]);
  const [siteImportErrors, setSiteImportErrors] = useState<SiteImportError[]>([]);
  const [siteImporting, setSiteImporting] = useState(false);
  const [siteExporting, setSiteExporting] = useState(false);
  const siteImportInputRef = useRef<HTMLInputElement | null>(null);
  const [credentialImportOpen, setCredentialImportOpen] = useState(false);
  const [credentialImportFileName, setCredentialImportFileName] = useState('');
  const [credentialImportRows, setCredentialImportRows] = useState<CredentialImportRow[]>([]);
  const [credentialImportErrors, setCredentialImportErrors] = useState<CredentialImportError[]>([]);
  const [credentialImporting, setCredentialImporting] = useState(false);
  const credentialImportInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const jobId = credentialJobStatus?.job_id;
    if (!jobId) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { headers: authHeaders() });
        const payload = await response.json().catch(() => ({}));
        if (cancelled || !response.ok || payload.success === false) return;
        // /api/jobs/{id} returns the job object directly; accept the wrapped
        // shape too so this page remains compatible with proxy adapters.
        const job = payload.data || payload;
        const next = { ...job, job_id: jobId };
        setCredentialJobStatus(next);
        const terminal = ['succeeded', 'partially_failed', 'failed', 'cancelled', 'timeout'].includes(next.status);
        if (terminal) {
          setNotice(zh
            ? `密码同步任务 ${jobId}：${next.status}，成功 ${next.success_count || 0} 台，失败 ${next.failed_count || 0} 台。${next.status === 'succeeded' ? '凭据中心已更新。' : '凭据中心仍保持原值。'}`
            : `Password sync job ${jobId}: ${next.status}; ${next.success_count || 0} succeeded, ${next.failed_count || 0} failed.`);
        }
      } catch {
        // The task remains durable; a transient polling failure must not hide it.
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [credentialJobStatus?.job_id, zh]);

  const tabs: { key: EntityKey; label: string; labelEn: string; icon: React.ReactNode }[] = [
    { key: 'credentials', label: '凭据中心', labelEn: 'Credentials', icon: <KeyRound size={14} /> },
    { key: 'devices', label: '设备骨架', labelEn: 'Devices', icon: <Server size={14} /> },
    { key: 'interfaces', label: '接口骨架', labelEn: 'Interfaces', icon: <Network size={14} /> },
    { key: 'sites', label: '站点', labelEn: 'Sites', icon: <Building2 size={14} /> },
    { key: 'vrfs', label: 'VRF', labelEn: 'VRFs', icon: <Network size={14} /> },
    { key: 'vlans', label: 'VLAN', labelEn: 'VLANs', icon: <Layers size={14} /> },
    { key: 'vlan-business', label: 'VLAN业务', labelEn: 'VLAN Business', icon: <UsersIcon size={14} /> },
    { key: 'tenants', label: '租户', labelEn: 'Tenants', icon: <UsersIcon size={14} /> },
  ];

  const vrfOptions = useMemo(
    () => [{ value: '', label: 'Default', labelEn: '(default)' }, ...vrfs.map(v => ({ value: v.id, label: v.vrf_name, labelEn: v.vrf_name }))],
    [vrfs]
  );

  const siteOptions = useMemo(
    () => [{ value: '', label: '（无）', labelEn: '(none)' }, ...sites.map(s => ({ value: s.id, label: `${s.site_code} · ${s.site_name}`, labelEn: `${s.site_code} · ${s.site_name}` }))],
    [sites, zh]
  );

  const vlanBusinessOptions = useMemo(() => {
    const selectedSite = String(form.site_id || '');
    const scopedById = new Map<string, any>();
    vlanCatalog
      .filter(vlan => String(vlan.site_id || '') === selectedSite)
      .forEach(vlan => {
        const key = `${selectedSite}:${vlan.vlan_id}`;
        if (!scopedById.has(key)) scopedById.set(key, vlan);
      });
    const scoped = Array.from(scopedById.values()).sort((left, right) => Number(left.vlan_id || 0) - Number(right.vlan_id || 0));
    const options = scoped.map(vlan => ({
      value: String(vlan.vlan_id),
      label: `VLAN ${vlan.vlan_id} · ${vlan.name || `VLAN ${vlan.vlan_id}`}`,
      labelEn: `VLAN ${vlan.vlan_id} · ${vlan.name || `VLAN ${vlan.vlan_id}`}`,
    }));
    const current = String(form.vlan_id || '');
    if (current && !options.some(option => option.value === current)) {
      options.unshift({
        value: current,
        label: `VLAN ${current} · 未找到当前站点记录`,
        labelEn: `VLAN ${current} · not found in selected site`,
      });
    }
    return [
      { value: '', label: scoped.length ? '请选择 VLAN' : '当前站点暂无可关联 VLAN', labelEn: scoped.length ? 'Select VLAN' : 'No VLANs available for this site' },
      ...options,
    ];
  }, [form.site_id, form.vlan_id, vlanCatalog]);

  useEffect(() => {
    if (!modalOpen || tab !== 'sites' || geoCatalog) return;
    let cancelled = false;
    setGeoLoading(true);
    setGeoError('');
    Promise.all([
      fetchLocalGeoData<GeoCountry[]>('countries.json'),
      fetchLocalGeoData<GeoState[]>('states.json'),
    ])
      .then(([countries, states]) => {
        if (cancelled) return;
        setGeoCatalog({ countries, states });
      })
      .catch(() => {
        if (!cancelled) setGeoError(zh ? '全球地理数据加载失败，请刷新页面重试。' : 'Failed to load geographic data. Refresh and retry.');
      })
      .finally(() => {
        if (!cancelled) setGeoLoading(false);
      });
    return () => { cancelled = true; };
  }, [geoCatalog, modalOpen, tab, zh]);

  const selectedGeoCountry = useMemo(() => {
    if (!geoCatalog || !form.country) return undefined;
    if (CHINA_LEGACY_COUNTRY_VALUES.has(String(form.country).trim())) {
      return geoCatalog.countries.find(country => country.isoCode === 'CN');
    }
    return geoCatalog.countries.find(country => matchesGeoValue(
      String(form.country), country.name, country.isoCode, countryDisplayName(country)
    ));
  }, [form.country, geoCatalog]);

  useEffect(() => {
    const countryCode = selectedGeoCountry?.isoCode;
    if (!modalOpen || tab !== 'sites' || !countryCode || countryCode in geoCityCache) return;
    let cancelled = false;
    setGeoCityLoading(true);
    setGeoCityError('');
    fetchLocalGeoData<GeoCity[]>(`cities/${countryCode}.json`)
      .then(cities => {
        if (!cancelled) setGeoCityCache(previous => ({ ...previous, [countryCode]: cities }));
      })
      .catch(() => {
        if (!cancelled) {
          // A country may legitimately have no city catalog in the bundled
          // source. Do not disable the whole site form for that one field.
          setGeoCityCache(previous => ({ ...previous, [countryCode]: [] }));
          setGeoCityError(zh ? '该国家暂无可用城市目录，可直接手动填写。' : 'No city catalog is available for this country; enter a city manually.');
        }
      })
      .finally(() => {
        if (!cancelled) setGeoCityLoading(false);
      });
    return () => { cancelled = true; };
  }, [geoCityCache, modalOpen, selectedGeoCountry, tab, zh]);

  useEffect(() => {
    const countryCode = selectedGeoCountry?.isoCode;
    if (!modalOpen || tab !== 'sites' || countryCode !== 'CN' || countryCode in geoDistrictCache) return;
    let cancelled = false;
    fetchLocalGeoData<GeoDistrict[]>('districts/CN.json')
      .then(districts => {
        if (!cancelled) setGeoDistrictCache(previous => ({ ...previous, CN: districts }));
      })
      .catch(() => {
        if (!cancelled) setGeoDistrictCache(previous => ({ ...previous, CN: [] }));
      });
    return () => { cancelled = true; };
  }, [geoDistrictCache, modalOpen, selectedGeoCountry, tab]);

  const geoStates = useMemo(
    () => selectedGeoCountry ? geoCatalog?.states.filter(state => state.countryCode === selectedGeoCountry.isoCode) || [] : [],
    [geoCatalog, selectedGeoCountry]
  );

  const selectedGeoState = useMemo(() => {
    if (!form.state_province) return undefined;
    return geoStates.find(state => matchesGeoValue(
      String(form.state_province), state.name, state.isoCode, stateDisplayName(state)
    ));
  }, [form.state_province, geoStates]);

  const geoCities = useMemo(
    () => {
      if (!selectedGeoCountry) return [];
      const allCities = geoCityCache[selectedGeoCountry.isoCode] || [];
      // Some countries do not expose a province/state layer. In that case
      // the city picker should still be usable instead of staying empty.
      if (!geoStates.length) return allCities;
      if (!selectedGeoState) return [];
      return allCities.filter(city => city.stateCode === selectedGeoState.isoCode);
    },
    [geoCityCache, geoStates, selectedGeoCountry, selectedGeoState]
  );

  const selectedGeoCity = useMemo(() => {
    if (!form.city) return undefined;
    return geoCities.find(city => matchesGeoValue(String(form.city), city.name, cityDisplayName(city)));
  }, [form.city, geoCities]);

  const geoDistricts = useMemo(
    () => {
      if (selectedGeoCountry?.isoCode !== 'CN' || !selectedGeoState || !selectedGeoCity) return [];
      return (geoDistrictCache.CN || []).filter(district => (
        district.stateCode === selectedGeoState.isoCode && district.cityName === selectedGeoCity.name
      ));
    },
    [geoDistrictCache, selectedGeoCity, selectedGeoCountry, selectedGeoState]
  );

  const geoSelectOptions = useMemo(() => {
    const addCurrentValue = (options: GeoSelectOption[], key: string) => {
      const current = String(form[key] || '').trim();
      if (current && !options.some(option => option.value === current)) {
        const matching = key === 'country'
          ? geoCatalog?.countries.find(country => matchesGeoValue(current, country.name, country.isoCode, countryDisplayName(country)))
          : undefined;
        options.unshift({
          value: current,
          label: matching ? countryDisplayName(matching) : `${current}（当前值）`,
          searchText: matching?.name,
        });
      }
      return options;
    };
    return {
      country: addCurrentValue(
        (geoCatalog?.countries || []).map(country => ({ value: countryDisplayName(country), label: countryDisplayName(country), searchText: countrySearchText(country) })),
        'country'
      ),
      state_province: addCurrentValue(
        geoStates.map(state => ({ value: stateDisplayName(state), label: stateDisplayName(state), searchText: state.name })),
        'state_province'
      ),
      city: addCurrentValue(
        geoCities.map(city => ({ value: city.name, label: cityDisplayName(city), searchText: city.name })),
        'city'
      ),
      district: addCurrentValue(
        geoDistricts.map(district => ({ value: district.displayName, label: district.displayName, searchText: `${district.name} ${district.pinyin}` })),
        'district'
      ),
    };
  }, [form, geoCatalog, geoCities, geoStates, geoDistricts]);

  const fieldDefs: Record<EntityKey, FieldDef[]> = useMemo(() => ({
    credentials: [
      { key: 'credential_name', label: '凭据名称', labelEn: 'Name', required: true },
      { key: 'credential_type', label: '类型', labelEn: 'Type', type: 'select', options: CRED_TYPE_OPTS },
      { key: 'username', label: '用户名', labelEn: 'Username' },
      { key: 'account_role', label: '账号角色', labelEn: 'Account Role', type: 'select', options: CRED_ROLE_OPTS },
      { key: 'old_password', label: '旧密码', labelEn: 'Current Password', type: 'password', hideInTable: true, hideInCreate: true, hint: '修改密码时必须输入当前密码' },
      { key: 'old_enable_password', label: '旧 Enable 密码', labelEn: 'Current Enable Password', type: 'password', hideInTable: true, hideInCreate: true, hint: '修改 Enable 密码时必须输入当前密码' },
      { key: 'password', label: '密码', labelEn: 'Password', type: 'password', hideInTable: true, secretFlag: 'has_password' },
      { key: 'enable_password', label: 'Enable 密码', labelEn: 'Enable Password', type: 'password', hideInTable: true, secretFlag: 'has_enable_password' },
      { key: 'snmp_community', label: 'SNMP Community', labelEn: 'SNMP Community', type: 'password', hideInTable: true, secretFlag: 'has_snmp_community', hint: 'SNMPv2c 团体字；采集使用 UDP 161' },
      { key: 'snmp_server', label: 'SNMP Server 地址', labelEn: 'SNMP Server Address', hideInTable: true, hint: '可选；不填写时使用设备管理 IP' },
      { key: 'devices', label: '关联设备', labelEn: 'Associated Devices', hideInForm: true },
    ],
    devices: [
      { key: 'hostname', label: '设备名称', labelEn: 'Hostname', hideInForm: true },
      { key: 'ip_address', label: '管理IP', labelEn: 'Management IP', hideInForm: true },
      { key: 'platform', label: '平台', labelEn: 'Platform', hideInForm: true },
      { key: 'role', label: '角色', labelEn: 'Role', hideInForm: true },
      { key: 'status', label: '状态', labelEn: 'Status', hideInForm: true },
      { key: 'site_id', label: '站点', labelEn: 'Site', hideInForm: true },
      { key: 'asset_tag', label: '资产标签', labelEn: 'Asset Tag', hideInForm: true },
      { key: 'interface_count', label: '接口数', labelEn: 'Interfaces', hideInForm: true },
      { key: 'ip_count', label: 'IP数', labelEn: 'IPs', hideInForm: true },
      { key: 'link_count', label: '链路数', labelEn: 'Links', hideInForm: true },
    ],
    interfaces: [
      { key: 'description', label: 'Description', labelEn: 'Description', hideInForm: true },
      { key: 'device_ip', label: '设备IP', labelEn: 'Device IP', hideInForm: true },
      { key: 'interface_ip', label: '接口IP', labelEn: 'Interface IP', hideInForm: true },
      { key: 'interface_name', label: '接口名称', labelEn: 'Interface', hideInForm: true },
      { key: 'device_hostname', label: '所属设备', labelEn: 'Device', hideInForm: true },
      { key: 'oper_status', label: '运行状态', labelEn: 'Oper Status', hideInForm: true },
      { key: 'admin_status', label: '管理状态', labelEn: 'Admin Status', hideInForm: true },
      { key: 'mac_address', label: 'MAC', labelEn: 'MAC', hideInForm: true },
      { key: 'switchport_mode', label: '交换模式', labelEn: 'Switchport', hideInForm: true },
      { key: 'access_vlan', label: 'Access VLAN', labelEn: 'Access VLAN', hideInForm: true },
      { key: 'native_vlan', label: 'Native VLAN', labelEn: 'Native VLAN', hideInForm: true },
      { key: 'allowed_vlans', label: 'Allowed VLAN', labelEn: 'Allowed VLANs', hideInForm: true },
      { key: 'vrf_name', label: 'VRF', labelEn: 'VRF', hideInForm: true },
      { key: 'ip_count', label: 'IP数', labelEn: 'IPs', hideInForm: true },
      { key: 'link_count', label: '链路数', labelEn: 'Links', hideInForm: true },
    ],
    sites: [
      { key: 'site_code', label: '站点编码', labelEn: 'Site Code', hideInForm: true, hideInTable: true },
      { key: 'site_name', label: '站点名称', labelEn: 'Site Name', required: true },
      { key: 'country', label: '国家', labelEn: 'Country' },
      { key: 'state_province', label: '省份 / 州', labelEn: 'Province / State' },
      { key: 'city', label: '城市', labelEn: 'City' },
      { key: 'district', label: '区县', labelEn: 'District / County' },
      { key: 'contact_name', label: '联系人', labelEn: 'Contact', required: true, maxLength: 50, placeholder: '例如 张三 / Zhang San', hint: '2-50个中文或英文字母，可含空格、点号或连字符' },
      { key: 'contact_phone', label: '联系电话', labelEn: 'Contact Phone', type: 'tel', required: true, maxLength: 32, inputMode: 'tel', placeholder: '例如 13800000000', hint: '支持11位手机、座机（010-12345678）或国际号码' },
      { key: 'contact_email', label: '联系邮箱', labelEn: 'Contact Email', type: 'email', required: true, maxLength: 254, inputMode: 'email', placeholder: '例如 ops@example.com', hint: '请输入有效的邮箱地址，例如 ops@example.com' },
      { key: 'timezone', label: '时区', labelEn: 'Timezone', placeholder: 'Asia/Shanghai' },
      { key: 'address', label: '详细地址', labelEn: 'Address' },
      { key: 'status', label: '状态', labelEn: 'Status', type: 'select', options: SITE_STATUS_OPTS },
      { key: 'created_at', label: '创建时间', labelEn: 'Created At', hideInForm: true },
    ],
    vrfs: [
      { key: 'vrf_name', label: 'VRF 名称', labelEn: 'VRF Name', required: true },
      { key: 'rd', label: 'RD', labelEn: 'RD', placeholder: '65000:1' },
      { key: 'description', label: '描述', labelEn: 'Description' },
    ],
    vlans: [
      { key: 'device_hostname', label: '设备名称', labelEn: 'Device', hideInForm: true, hideInTable: true },
      { key: 'device_ip', label: '设备 IP', labelEn: 'Device IP', hideInForm: true, hideInTable: true },
      { key: 'site_name', label: '站点', labelEn: 'Site', hideInForm: true },
      { key: 'vrf_name', label: 'VRF', labelEn: 'VRF', hideInForm: true },
      { key: 'prefixes', label: '网段', labelEn: 'Prefixes', hideInForm: true },
      { key: 'gateway', label: '网关地址', labelEn: 'Gateway', hideInForm: true },
      { key: 'gateway_device', label: '网关设备', labelEn: 'Gateway Device', hideInForm: true },
      { key: 'svi_interfaces', label: '三层接口', labelEn: 'VLANIF / SVI', hideInForm: true },
      { key: 'port_details', label: '端口描述', labelEn: 'Port Descriptions', hideInForm: true },
      { key: 'undocumented_port_count', label: '缺少描述', labelEn: 'Missing Descriptions', hideInForm: true },
      { key: 'device_count', label: '设备数', labelEn: 'Devices', hideInForm: true },
      { key: 'port_count', label: '端口数', labelEn: 'Ports', hideInForm: true },
      { key: 'mac_count', label: 'MAC 数', labelEn: 'MACs', hideInForm: true },
      { key: 'arp_count', label: 'ARP 数', labelEn: 'ARPs', hideInForm: true },
      { key: 'business_systems', label: '业务系统', labelEn: 'Business Systems', hideInForm: true },
      { key: 'last_discovered_at', label: '最近发现', labelEn: 'Last Discovered', hideInForm: true },
      { key: 'vlan_id', label: 'VLAN ID', labelEn: 'VLAN ID', type: 'number', required: true, placeholder: '1-4094' },
      { key: 'name', label: '名称', labelEn: 'Name', required: true },
      { key: 'site_id', label: '站点', labelEn: 'Site', type: 'select' },
      { key: 'status', label: '状态', labelEn: 'Status', type: 'select', options: VLAN_STATUS_OPTS },
    ],
    'vlan-business': [
      { key: 'vlan_id', label: 'VLAN', labelEn: 'VLAN', type: 'select', required: true },
      { key: 'site_id', label: '站点', labelEn: 'Site', type: 'select' },
      { key: 'vrf_id', label: 'VRF', labelEn: 'VRF', type: 'select' },
      { key: 'business_system', label: '业务系统', labelEn: 'Business System', required: true },
      { key: 'department', label: '部门', labelEn: 'Department', required: true },
      { key: 'owner', label: '负责人', labelEn: 'Owner', required: true },
      { key: 'business_level', label: '业务等级', labelEn: 'Business Level', type: 'select', options: [
        { value: 'P1', label: 'P1（关键）', labelEn: 'P1' }, { value: 'P2', label: 'P2（重要）', labelEn: 'P2' },
        { value: 'P3', label: 'P3（一般）', labelEn: 'P3' }, { value: 'P4', label: 'P4（低）', labelEn: 'P4' },
      ] },
      { key: 'status', label: '状态', labelEn: 'Status', type: 'select', options: [
        { value: 'active', label: '启用', labelEn: 'Active' }, { value: 'planned', label: '规划中', labelEn: 'Planned' },
        { value: 'retired', label: '已停用', labelEn: 'Retired' },
      ] },
      { key: 'description', label: '描述', labelEn: 'Description' },
      { key: 'updated_at', label: '最后确认', labelEn: 'Last Confirmed', hideInForm: true },
    ],
    tenants: [
      { key: 'name', label: '租户名称', labelEn: 'Name', required: true },
      { key: 'description', label: '描述', labelEn: 'Description' },
    ],
  }), []);

  const endpointFor = (key: EntityKey, id?: string) => {
    const base = key === 'credentials'
      ? '/api/credentials'
      : key === 'vlan-business'
        ? '/api/cmdb/vlan-business-bindings'
        : `/api/cmdb/${key}`;
    return id ? `${base}/${id}` : base;
  };

  const load = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    setError('');
    try {
      let endpoint = endpointFor(tab);
      if (tab === 'interfaces') {
        // Keep the CMDB interface view aligned with its historical L3/IP
        // inventory contract.  Topology maintains physical endpoint rows
        // independently when it needs them for link identity.
        const params = new URLSearchParams({ has_ip: 'true' });
        if (search.trim()) params.set('search', search.trim());
        if (interfaceDeviceFilter) params.set('device_id', interfaceDeviceFilter);
        params.set('page', String(interfacePage));
        params.set('page_size', String(interfacePageSize));
        endpoint = `${endpoint}?${params.toString()}`;
      }
      if (tab === 'interfaces') {
        const pageData = await apiListPage<any>(endpoint);
        if (requestId !== loadRequestRef.current) return;
        setRows(pageData.items);
        setInterfaceListMeta({
          total: pageData.total,
          summary: {
            total: Number(pageData.summary?.total || pageData.total || 0),
            with_ip: Number(pageData.summary?.with_ip || 0),
            oper_up: Number(pageData.summary?.oper_up || 0),
            with_links: Number(pageData.summary?.with_links || 0),
          },
          device_options: pageData.device_options || [],
        });
      } else if (tab === 'vlans') {
        const params = new URLSearchParams({
          page: String(page),
          page_size: String(pageSize),
          q: search.trim(),
          status: vlanStatusFilter,
        });
        if (vlanSiteFilter) params.set('site_id', vlanSiteFilter);
        Object.entries(vlanTreeBranch).forEach(([key, value]) => {
          if (value && key !== 'site_id') params.set(key, value);
        });
        const pageData = await apiListPage<any>(`${endpoint}?${params.toString()}`);
        if (requestId !== loadRequestRef.current) return;
        setRows(pageData.items);
        setVlanListMeta({
          total: pageData.total,
          page: pageData.page,
          page_size: pageData.page_size,
          summary: {
            total: Number(pageData.summary?.total || pageData.total || 0),
            gateways: Number(pageData.summary?.gateways || 0),
            arp: Number(pageData.summary?.arp || 0),
            mac: Number(pageData.summary?.mac || 0),
            unbound: Number(pageData.summary?.unbound || 0),
          },
          site_summary: pageData.site_summary || [],
        });
        setVlanScopeTree(pageData.tree || []);
      } else {
        const pagedEntity = ['sites', 'vrfs'].includes(tab);
        if (pagedEntity) {
          const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), q: search.trim() });
          const pageData = await apiListPage<any>(`${endpoint}?${params.toString()}`);
          if (requestId !== loadRequestRef.current) return;
          setRows(tab === 'sites' ? dedupeSiteRows(pageData.items) : pageData.items);
          setGenericListMeta({ total: pageData.total, page: pageData.page, page_size: pageData.page_size });
        } else {
          const data = await apiList<any>(endpoint);
          if (requestId !== loadRequestRef.current) return;
          setRows(tab === 'sites' ? dedupeSiteRows(data) : data);
          setGenericListMeta({ total: data.length, page: 1, page_size: data.length || pageSize });
        }
      }
      if (tab === 'vlans' && sites.length === 0) {
        const siteRows = dedupeSiteRows(await apiList<any>('/api/cmdb/sites').catch(() => []));
        if (requestId === loadRequestRef.current) setSites(siteRows);
      }
    } catch (e: any) {
      if (requestId !== loadRequestRef.current) return;
      setError(e.message || String(e));
      setRows([]);
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, [tab, search, interfaceDeviceFilter, interfacePage, interfacePageSize, page, pageSize, vlanSiteFilter, vlanStatusFilter, vlanTreeBranch]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const downloadSiteImportTemplate = useCallback(() => {
    const headers = SITE_IMPORT_COLUMNS.map(column => column.header);
    const sample = SITE_IMPORT_COLUMNS.map(column => column.sample);
    const worksheet = XLSX.utils.aoa_to_sheet([headers, sample]);
    worksheet['!cols'] = SITE_IMPORT_COLUMNS.map(column => ({ wch: Math.max(14, column.header.length + 6) }));
    const guide = XLSX.utils.aoa_to_sheet([
      ['字段', '英文别名', '是否必填', '填写说明'],
      ...SITE_IMPORT_COLUMNS.map(column => [
        column.header,
        column.headerEn,
        column.required ? '是' : '否',
        column.key === 'status' ? '可选值：active、planned、staging、decommissioned、offline；留空默认为 active' : (column.required ? '不能为空；字段格式与站点新建表单一致' : '可留空'),
      ]),
    ]);
    guide['!cols'] = [{ wch: 18 }, { wch: 22 }, { wch: 12 }, { wch: 72 }];
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, '站点数据');
    XLSX.utils.book_append_sheet(workbook, guide, '填写说明');
    XLSX.writeFile(workbook, `site_import_template_${new Date().toISOString().slice(0, 10)}.xlsx`);
    setNotice(zh ? '站点导入模板已下载' : 'Site import template downloaded');
  }, [zh]);

  const validateSiteImportRows = useCallback((rawRows: Array<Record<string, unknown>>) => {
    const normalizedRows: SiteImportRow[] = [];
    const errors: SiteImportError[] = [];
    const seenSiteNames = new Set<string>();
    rawRows.forEach((raw, index) => {
      const rowNumber = index + 2;
      const normalized: SiteImportRow = {};
      Object.entries(raw).forEach(([rawKey, value]) => {
        const key = SITE_IMPORT_HEADER_ALIASES[String(rawKey).replace(/^\uFEFF/, '').trim()];
        if (key) normalized[key] = String(value ?? '').trim();
      });
      const hasValue = Object.values(normalized).some(Boolean);
      if (!hasValue) return;
      normalized.timezone = normalized.timezone || 'Asia/Shanghai';
      normalized.status = normalized.status || 'active';
      SITE_IMPORT_COLUMNS.filter(column => column.required).forEach(column => {
        if (!normalized[column.key]) errors.push({ row: rowNumber, message: `${column.header}不能为空` });
      });
      const siteNameKey = normalized.site_name?.toLocaleLowerCase();
      if (siteNameKey) {
        if (seenSiteNames.has(siteNameKey)) errors.push({ row: rowNumber, message: '站点名称在导入文件中重复' });
        seenSiteNames.add(siteNameKey);
      }
      if (normalized.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(normalized.contact_email)) {
        errors.push({ row: rowNumber, message: '联系邮箱格式不正确' });
      }
      if (normalized.contact_phone && !/^\+?[0-9][0-9\s().-]{5,31}$/.test(normalized.contact_phone)) {
        errors.push({ row: rowNumber, message: '联系电话格式不正确' });
      }
      if (!SITE_STATUS_OPTS.some(option => option.value === normalized.status)) {
        errors.push({ row: rowNumber, message: '状态必须是 active、planned、staging、decommissioned 或 offline' });
      }
      if (Object.keys(normalized).length === 0) {
        errors.push({ row: rowNumber, message: '未识别到站点字段，请使用导入模板表头' });
      } else {
        normalizedRows.push(normalized);
      }
    });
    if (normalizedRows.length === 0 && errors.length === 0) {
      errors.push({ row: 1, message: '文件中没有可导入的站点数据' });
    }
    return { normalizedRows, errors };
  }, []);

  const handleSiteImportFile = useCallback(async (file?: File) => {
    if (!file) return;
    setSiteImportOpen(true);
    setSiteImportFileName(file.name);
    setSiteImportRows([]);
    setSiteImportErrors([]);
    try {
      const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array' });
      const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
      if (!firstSheet) throw new Error('导入文件没有可读取的工作表');
      const rawRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(firstSheet, { defval: '' });
      const result = validateSiteImportRows(rawRows);
      setSiteImportRows(result.normalizedRows);
      setSiteImportErrors(result.errors);
    } catch (e: any) {
      setSiteImportErrors([{ row: 1, message: e.message || '无法读取导入文件' }]);
    } finally {
      if (siteImportInputRef.current) siteImportInputRef.current.value = '';
    }
  }, [validateSiteImportRows]);

  const importSiteRows = useCallback(async () => {
    if (siteImporting || !siteImportRows.length || siteImportErrors.length) return;
    setSiteImporting(true);
    setError('');
    try {
      const response = await fetch('/api/cmdb/sites/import', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ rows: siteImportRows }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.success === false) {
        throw new Error(formatErrorDetail(payload.detail || payload.message));
      }
      const result = payload.data || {};
      if (Number(result.failed || 0) > 0) {
        setSiteImportErrors((result.errors || []).map((item: any) => ({ row: Number(item.row || 0), message: String(item.message || '导入失败') })));
        if (Number(result.imported || 0) > 0) await load();
        return;
      }
      setSiteImportOpen(false);
      setSiteImportRows([]);
      setNotice(zh ? `已成功导入 ${result.imported || siteImportRows.length} 个站点` : `Imported ${result.imported || siteImportRows.length} site(s)`);
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setSiteImporting(false);
    }
  }, [load, siteImportErrors.length, siteImportRows, siteImporting, zh]);

  const exportSiteInventory = useCallback(async () => {
    if (siteExporting) return;
    setSiteExporting(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set('q', search.trim());
      const response = await fetch(`/api/cmdb/sites/export?${params.toString()}`, { headers: authHeaders() });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(formatErrorDetail(payload.detail || payload.message));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `sites_export_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setNotice(zh ? '站点数据已导出' : 'Site data exported');
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setSiteExporting(false);
    }
  }, [search, siteExporting, zh]);

  const downloadCredentialImportTemplate = useCallback(async () => {
    if (credentialTemplateDownloading) return;
    setCredentialTemplateDownloading(true);
    setError('');
    setNotice('');
    try {
      const response = await fetch('/api/credentials/import-template', { headers: authHeaders() });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(formatErrorDetail(payload.detail || payload.message));
      }
      // A long-running backend process may still serve the pre-fix template.
      // Prefer the API once it advertises the current format; otherwise use
      // the bundled compatibility copy so the download is correct immediately
      // without requiring a backend restart.
      let templateResponse = response;
      if (response.headers.get('X-Credential-Template-Version') !== '2') {
        templateResponse = await fetch('/templates/credential_import_template.xlsx?v=2', {
          cache: 'no-store',
        });
        if (!templateResponse.ok) {
          throw new Error(zh ? '无法读取凭据导入模板' : 'Unable to read the credential import template');
        }
      }
      const blob = await templateResponse.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'credential_import_template.xlsx';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setCredentialTemplateDownloading(false);
    }
  }, [credentialTemplateDownloading]);

  const exportCredentialInventory = useCallback(() => {
    if (credentialExporting) return;
    setCredentialExporting(true);
    setError('');
    try {
      const workbook = XLSX.utils.book_new();
      CREDENTIAL_SHEET_DEFS.forEach(sheet => {
        const sheetRows = rows.filter(row => {
          const type = String(row.credential_type || '').toLowerCase();
          return sheet.key === 'snmp' ? type.startsWith('snmp') : !type.startsWith('snmp');
        });
        const headers = sheet.columns.map(column => column.label);
        const dataRows = sheetRows.map(row => sheet.columns.map(column => (
          CREDENTIAL_SECRET_FIELDS.has(column.key) ? '' : (row[column.key] ?? '')
        )));
        const worksheet = XLSX.utils.aoa_to_sheet([headers, ...dataRows]);
        worksheet['!cols'] = sheet.columns.map(column => ({
          wch: Math.max(18, column.key.length + 6),
        }));
        XLSX.utils.book_append_sheet(workbook, worksheet, sheet.name);
      });
      XLSX.writeFile(workbook, `credentials_export_${new Date().toISOString().slice(0, 10)}.xlsx`);
      setNotice(zh ? '凭据已导出，SSH 和 SNMP 已分为两个 Sheet，所有秘密字段为空' : 'Credentials exported into separate SSH and SNMP sheets with all secret fields blank');
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setCredentialExporting(false);
    }
  }, [credentialExporting, rows, zh]);

  const validateCredentialImportRows = useCallback((sheetInputs: Array<{ name: string; rows: Array<Record<string, unknown>> }>) => {
    const normalizedRows: CredentialImportRow[] = [];
    const errors: CredentialImportError[] = [];
    const existingNames = new Set(rows.map(row => String(row.credential_name || '').trim().toLocaleLowerCase()).filter(Boolean));
    const seenNames = new Set<string>();

    const normalizeHeader = (value: unknown) => String(value ?? '').replace(/^\uFEFF/, '').trim().toLocaleLowerCase();
    const definitionForSheet = (name: string, rawRows: Array<Record<string, unknown>>): CredentialSheetDefinition => {
      if (/snmp/i.test(name)) return CREDENTIAL_SHEET_DEFS[1];
      if (/ssh/i.test(name)) return CREDENTIAL_SHEET_DEFS[0];
      const firstRowKeys = Object.keys(rawRows[0] || {}).map(normalizeHeader);
      return firstRowKeys.some(key => key === 'snmp_community' || key === 'snmp_server' || key === 'snmp community' || key === 'snmp server' || key === 'snmp 团体字' || key === 'snmp 服务器地址')
        ? CREDENTIAL_SHEET_DEFS[1]
        : CREDENTIAL_SHEET_DEFS[0];
    };

    sheetInputs.forEach(sheetInput => {
      const definition = definitionForSheet(sheetInput.name, sheetInput.rows);
      const aliases = new Map<string, string>();
      definition.columns.forEach(column => {
        [column.key, column.label, column.labelEn].forEach(alias => aliases.set(normalizeHeader(alias), column.key));
      });

      sheetInput.rows.forEach((raw, index) => {
        const rowNumber = index + 2;
        const values: Record<string, string> = {};
        Object.entries(raw).forEach(([rawKey, value]) => {
          const key = aliases.get(normalizeHeader(rawKey));
          if (key) values[key] = String(value ?? '');
        });
        if (!Object.values(values).some(value => value.trim())) return;

        values.credential_name = String(values.credential_name || '').trim();
        values.credential_type = String(values.credential_type || definition.defaultType).trim().toLowerCase();
        if ('username' in values) values.username = values.username.trim();
        if ('account_role' in values) {
          const rawRole = (values.account_role || 'normal').trim();
          values.account_role = CREDENTIAL_ROLE_VALUE_ALIASES[rawRole]
            || CREDENTIAL_ROLE_VALUE_ALIASES[rawRole.toLowerCase()]
            || rawRole.toLowerCase();
        }
        if ('snmp_server' in values) values.snmp_server = values.snmp_server.trim();

        if (!values.credential_name) errors.push({ sheet: definition.name, row: rowNumber, message: '凭据名称不能为空' });
        if (!definition.allowedTypes.includes(values.credential_type)) {
          errors.push({ sheet: definition.name, row: rowNumber, message: `${definition.name} Sheet 的凭据类型必须是 ${definition.allowedTypes.join('、')}` });
        }
        if (definition.key === 'ssh' && values.account_role && !CRED_ROLE_OPTS.some(option => option.value === values.account_role)) {
          errors.push({ sheet: definition.name, row: rowNumber, message: '账号角色必须是普通账号、特权账号、通用账号或未指定' });
        }
        const nameKey = values.credential_name.toLocaleLowerCase();
        if (nameKey && (existingNames.has(nameKey) || seenNames.has(nameKey))) {
          errors.push({ sheet: definition.name, row: rowNumber, message: '凭据名称已存在或在导入文件中重复' });
        }
        if (nameKey) seenNames.add(nameKey);
        if (definition.key === 'snmp' && values.credential_type === 'snmpv2' && !String(values.snmp_community || '').trim()) {
          errors.push({ sheet: definition.name, row: rowNumber, message: 'snmpv2 必须填写 SNMP Community' });
        }
        if (Object.keys(values).length === 0) {
          errors.push({ sheet: definition.name, row: rowNumber, message: '未识别到字段，请使用 SSH 或 SNMP 导入模板' });
        } else {
          normalizedRows.push({ sheet: definition.key, sheetName: definition.name, row: rowNumber, values });
        }
      });
    });

    if (normalizedRows.length === 0 && errors.length === 0) {
      errors.push({ sheet: '文件', row: 1, message: '文件中没有可导入的凭据数据' });
    }
    return { normalizedRows, errors };
  }, [rows]);

  const handleCredentialImportFile = useCallback(async (file?: File) => {
    if (!file) return;
    setCredentialImportOpen(true);
    setCredentialImportFileName(file.name);
    setCredentialImportRows([]);
    setCredentialImportErrors([]);
    try {
      const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array' });
      const sheetInputs = workbook.SheetNames.map(name => ({
        name,
        rows: XLSX.utils.sheet_to_json<Record<string, unknown>>(workbook.Sheets[name], { defval: '' }),
      })).filter(item => item.rows.length > 0);
      if (!sheetInputs.length) throw new Error('导入文件没有可读取的工作表或数据');
      const result = validateCredentialImportRows(sheetInputs);
      setCredentialImportRows(result.normalizedRows);
      setCredentialImportErrors(result.errors);
    } catch (e: any) {
      setCredentialImportErrors([{ sheet: '文件', row: 1, message: e.message || '无法读取导入文件' }]);
    } finally {
      if (credentialImportInputRef.current) credentialImportInputRef.current.value = '';
    }
  }, [validateCredentialImportRows]);

  const importCredentialRows = useCallback(async () => {
    if (credentialImporting || !credentialImportRows.length || credentialImportErrors.length) return;
    setCredentialImporting(true);
    setError('');
    const failed: CredentialImportError[] = [];
    let imported = 0;
    try {
      for (const item of credentialImportRows) {
        try {
          await apiSend('/api/credentials', 'POST', item.values);
          imported += 1;
        } catch (e: any) {
          failed.push({ sheet: item.sheetName, row: item.row, message: e.message || '导入失败' });
        }
      }
      if (imported > 0) await load();
      if (failed.length) {
        setCredentialImportErrors(failed);
        setNotice(zh ? `已导入 ${imported} 条，${failed.length} 条失败，请检查错误信息` : `${imported} imported, ${failed.length} failed. Check the errors.`);
        return;
      }
      setCredentialImportOpen(false);
      setCredentialImportRows([]);
      setNotice(zh ? `已成功导入 ${imported} 条凭据` : `Imported ${imported} credential(s)`);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setCredentialImporting(false);
    }
  }, [credentialImportErrors.length, credentialImportRows, credentialImporting, load, zh]);

  const exportVlanInventory = useCallback(async () => {
    if (vlanExporting) return;
    setVlanExporting(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (vlanSiteFilter && vlanSiteFilter !== 'unassigned') params.set('site_id', vlanSiteFilter);
      const response = await fetch(`/api/cmdb/vlans/export?${params.toString()}`, { headers: authHeaders() });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(formatErrorDetail(payload.detail || payload.message));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `VLAN清单_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setNotice(zh ? 'VLAN 清单已导出，包含完整设备、接口和 ARP/MAC 信息。' : 'VLAN inventory exported with complete device, interface and ARP/MAC details.');
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setVlanExporting(false);
    }
  }, [vlanExporting, vlanSiteFilter, zh]);

  const triggerInterfaceSync = useCallback(async () => {
    if (tab !== 'interfaces') return;
    setInterfaceSyncing(true);
    interfaceTerminalHandledRef.current = null;
    setError('');
    try {
      const res = await fetch('/api/cmdb/interfaces/sync', {
        method: 'POST',
        headers: authHeaders(),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || json.success === false) {
        throw new Error(formatErrorDetail(json.detail || json.message));
      }
      const job = json.data?.job || json.data || {};
      const jobId = json.data?.job_id || job.job_id || job.id;
      if (!jobId) throw new Error(zh ? '接口采集任务未返回任务编号' : 'Interface collection did not return a job id');
      setInterfaceJobStatus({ ...job, job_id: jobId });
      setNotice(zh ? `接口采集任务已启动，共 ${job.total_targets || job.targets?.length || 0} 台设备；进度和失败原因会显示在本页。` : `Interface collection started for ${job.total_targets || job.targets?.length || 0} device(s); progress and failures will appear here.`);
    } catch (e: any) {
      setError(e.message || String(e));
      setInterfaceSyncing(false);
    } finally {
      // Keep the button busy until the durable job reaches a terminal state.
    }
  }, [load, tab, zh]);

  useEffect(() => {
    const jobId = interfaceJobStatus?.job_id;
    if (!jobId || tab !== 'interfaces') return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`/api/cmdb/interfaces/sync/${encodeURIComponent(jobId)}`, { headers: authHeaders() });
        const payload = await response.json().catch(() => ({}));
        if (cancelled || !response.ok || payload.success === false) return;
        const next = payload.data || payload;
        setInterfaceJobStatus({ ...next, job_id: jobId });
        const terminal = ['succeeded', 'partially_failed', 'failed', 'cancelled', 'timeout', 'completed', 'complete', 'success', 'finished'].includes(String(next.status || '').toLowerCase());
        if (terminal && interfaceTerminalHandledRef.current !== jobId) {
          interfaceTerminalHandledRef.current = jobId;
          setInterfaceSyncing(false);
          await load();
          const failed = Number(next.failed_count || 0);
          setNotice(zh
            ? `接口采集${failed ? `完成，成功 ${next.success_count || 0} 台，失败 ${failed} 台` : '已完成'}；详情已显示在本页。`
            : `Interface collection ${failed ? `finished: ${next.success_count || 0} succeeded, ${failed} failed` : 'completed'}; details are shown on this page.`);
        }
      } catch {
        // Keep the durable job id; a transient polling failure must not hide it.
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [interfaceJobStatus?.job_id, tab, zh, load]);

  // Preload scope catalogs so VLAN and VLAN-business forms can be edited
  // without another round trip when the modal opens.
  useEffect(() => {
    apiList<any>('/api/cmdb/sites').then(data => setSites(dedupeSiteRows(data))).catch(() => {});
    apiList<any>('/api/cmdb/vrfs').then(setVrfs).catch(() => {});
    let cancelled = false;
    const loadVlanCatalog = async () => {
      try {
        const firstPage = await apiListPage<any>('/api/cmdb/vlans?page=1&page_size=100&status=all');
        const pages = Array.from({ length: Math.max(0, firstPage.total_pages - 1) }, (_, index) => index + 2);
        const remaining = await Promise.all(pages.map(pageNumber => apiListPage<any>(`/api/cmdb/vlans?page=${pageNumber}&page_size=100&status=all`)));
        if (!cancelled) setVlanCatalog([firstPage, ...remaining].flatMap(pageData => pageData.items));
      } catch {
        if (!cancelled) setVlanCatalog([]);
      }
    };
    void loadVlanCatalog();
    return () => { cancelled = true; };
  }, []);

  // Reset page number on tab or search change
  useEffect(() => {
    setPage(1);
    if (tab === 'interfaces') setInterfacePage(1);
  }, [tab, search]);

  // Do not keep the previous entity's rows visible while the new tab is
  // loading.  Otherwise a slow VRF/site/VLAN request can temporarily render
  // records from the tab the user just left.
  useEffect(() => {
    setRows([]);
    setError('');
  }, [tab]);

  const openCreate = () => {
    if (isReadOnlyTab) return;
    const defaults: Record<string, any> = {};
    fieldDefs[tab].forEach(f => {
      if (f.hideInForm || f.hideInCreate) return;
      if (f.type === 'select' && f.options?.length) defaults[f.key] = f.options[0].value;
      else if (f.key === 'timezone') defaults[f.key] = 'Asia/Shanghai';
      else defaults[f.key] = '';
    });
    setForm(defaults);
    setEditing(null);
    setError('');
    setNotice('');
    setFieldErrors({});
    setVisiblePasswordFields({});
    setModalOpen(true);
  };

  const openEdit = (row: any) => {
    if (isReadOnlyTab) return;
    const f: Record<string, any> = {};
    fieldDefs[tab].forEach(fd => {
      if (fd.hideInForm) return;
      if (fd.secretFlag) f[fd.key] = ''; // never prefill secrets
      else if (tab === 'sites' && fd.key === 'country' && CHINA_LEGACY_COUNTRY_VALUES.has(String(row[fd.key] ?? '').trim())) f[fd.key] = '中国';
      else f[fd.key] = row[fd.key] ?? '';
    });
    setForm(f);
    setEditing(row);
    setError('');
    setNotice('');
    setFieldErrors({});
    setVisiblePasswordFields({});
    setModalOpen(true);
  };

  const idOf = (row: any) => row.id;

  const submit = async () => {
    if (isReadOnlyTab) return;
    setError('');
    setNotice('');
    setFieldErrors({});
    const defs = fieldDefs[tab].filter(fd => !fd.hideInForm && (!fd.hideInCreate || Boolean(editing))
      && !(tab === 'credentials' && form.credential_type === 'snmpv2'
        && ['username', 'account_role', 'old_password', 'old_enable_password', 'password', 'enable_password'].includes(fd.key))
      && !(tab === 'credentials' && !String(form.credential_type || '').startsWith('snmp')
        && ['snmp_community', 'snmp_server'].includes(fd.key)));
    // New site records require contact data. Existing records remain
    // editable without backfilling columns introduced later.
    for (const fd of defs) {
      if (tab === 'sites' && ['contact_name', 'contact_phone', 'contact_email'].includes(fd.key)) continue;
      if (fd.required && !editing && String(form[fd.key] ?? '').trim() === '') {
        setError(zh ? `请填写「${fd.label}」` : `${fd.labelEn} is required`);
        return;
      }
    }
    if (tab === 'sites') {
      const contactFields: SiteContactField[] = ['contact_name', 'contact_phone', 'contact_email'];
      const contactErrors: Record<string, string> = {};
      const phoneRule = phoneRuleForCountry(selectedGeoCountry?.isoCode);
      contactFields.forEach(field => {
        const value = String(form[field] ?? '').trim();
        const changed = !editing || String(editing[field] ?? '').trim() !== value;
        if (changed) contactErrors[field] = siteContactError(field, value, true, zh, phoneRule);
      });
      const visibleErrors = Object.fromEntries(Object.entries(contactErrors).filter(([, message]) => message));
      if (Object.keys(visibleErrors).length) {
        setFieldErrors(previous => ({ ...previous, ...visibleErrors }));
        return;
      }
    }
    if (tab === 'credentials' && form.credential_type === 'snmpv2' && !editing && !String(form.snmp_community || '').trim()) {
      setError(zh ? 'SNMPv2 凭据必须填写 SNMP Community' : 'SNMPv2 credentials require an SNMP Community');
      return;
    }
    // Build payload; omit blank secrets on edit so they stay unchanged.
    const payload: Record<string, any> = {};
    defs.forEach(fd => {
      let v = form[fd.key];
      if (editing && tab === 'sites' && ['contact_name', 'contact_phone', 'contact_email'].includes(fd.key)
        && String(editing[fd.key] ?? '').trim() === String(v ?? '').trim()) return;
      if (fd.type === 'number') v = v === '' ? undefined : Number(v);
      if (fd.secretFlag && editing && (v === '' || v == null)) return; // keep existing secret
      if (editing && !fd.secretFlag
        && String(editing[fd.key] ?? '').trim() === String(v ?? '').trim()) return;
      if (fd.key === 'site_id' && v === '') { payload[fd.key] = tab === 'vlan-business' ? '' : null; return; }
      if (fd.key === 'vrf_id' && v === '') { payload[fd.key] = ''; return; }
      if (v !== undefined) payload[fd.key] = v;
    });
    try {
      const response = editing
        ? await apiSend(endpointFor(tab, idOf(editing)), 'PUT', payload)
        : await apiSend(endpointFor(tab), 'POST', payload);
      setModalOpen(false);
      if (tab === 'credentials' && response?.job_id) {
        setCredentialJobStatus({ job_id: response.job_id, status: 'queued', total_targets: response.device_count || 0 });
        setCredentialJobDetailsOpen(true);
        setNotice(zh
          ? `密码同步任务已创建：${response.job_id}，正在处理 ${response.device_count || 0} 台设备。凭据中心将在全部设备验证成功后更新。`
          : `Password sync job ${response.job_id} started for ${response.device_count || 0} devices. The vault updates after all devices verify successfully.`);
      }
      await load();
    } catch (e: any) {
      const message = e.message || String(e);
      const displayMessage = tab === 'credentials' ? humanizeCredentialError(message, zh) : message;
      const contactField = tab === 'sites'
        ? (['contact_name', 'contact_phone', 'contact_email'] as SiteContactField[]).find(field => message.includes(field))
        : undefined;
      if (contactField) setFieldErrors(previous => ({ ...previous, [contactField]: message }));
      else {
        if (tab === 'credentials') {
          const credentialField = /old_enable_password/i.test(message)
            ? 'old_enable_password'
            : /old_password/i.test(message)
              ? 'old_password'
              : '';
          if (credentialField) setFieldErrors(previous => ({ ...previous, [credentialField]: displayMessage }));
        }
        setError(displayMessage);
      }
    }
  };

  const doDelete = async () => {
    if (isReadOnlyTab) return;
    if (!confirmDelete) return;
    setError('');
    try {
      let url = endpointFor(tab, idOf(confirmDelete));
      if (tab === 'sites' && siteReplacementId) {
        url += `?replacement_site_id=${encodeURIComponent(siteReplacementId)}`;
      }
      await apiSend(url, 'DELETE');
      setConfirmDelete(null);
      setSiteReplacementId('');
      setSiteDeleteError('');
      await load();
    } catch (e: any) {
      const message = e.message || String(e);
      if (tab === 'sites' && message.includes('still referenced')) {
        setSiteDeleteError(message);
      } else {
        setError(message);
        setConfirmDelete(null);
      }
    }
  };

  const openDeleteConfirm = (row: any) => {
    setConfirmDelete(row);
    setSiteReplacementId('');
    setSiteDeleteError('');
  };

  const tableColumns = fieldDefs[tab].filter(f => !f.hideInTable);

  const getSiteStatusStyle = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/20 dark:text-emerald-400 dark:border-emerald-900/30';
      case 'planned':
        return 'bg-blue-50 text-blue-700 border-blue-100 dark:bg-blue-950/20 dark:text-blue-400 dark:border-blue-900/30';
      case 'staging':
        return 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-950/20 dark:text-amber-400 dark:border-amber-900/30';
      case 'offline':
        return 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/20 dark:text-rose-400 dark:border-rose-900/30';
      case 'decommissioned':
      default:
        return 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-900/20 dark:text-slate-400 dark:border-slate-800';
    }
  };

  const getVlanStatusStyle = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/20 dark:text-emerald-400 dark:border-emerald-900/30';
      case 'reserved':
        return 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-950/20 dark:text-amber-400 dark:border-amber-900/30';
      case 'deprecated':
      default:
        return 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-900/20 dark:text-slate-400 dark:border-slate-800';
    }
  };

  const getCredTypeLabel = (type: string) => {
    if (zh) {
      switch (type) {
        case 'ssh_password': return 'SSH 密码';
        case 'ssh_key': return 'SSH 私钥';
        case 'snmpv2': return 'SNMP v2';
        case 'snmpv3': return 'SNMP v3';
        case 'api_token': return 'API 令牌';
        default: return type;
      }
    } else {
      switch (type) {
        case 'ssh_password': return 'SSH Password';
        case 'ssh_key': return 'SSH Key';
        case 'snmpv2': return 'SNMP v2';
        case 'snmpv3': return 'SNMP v3';
        case 'api_token': return 'API Token';
        default: return type;
      }
    }
  };

  const getCredTypeStyle = (type: string) => {
    switch (type) {
      case 'ssh_password':
        return 'bg-indigo-50/70 text-indigo-600 border-indigo-100/60 dark:bg-indigo-950/20 dark:text-indigo-400 dark:border-indigo-900/30';
      case 'ssh_key':
        return 'bg-cyan-50/70 text-cyan-700 border-cyan-100/60 dark:bg-cyan-950/20 dark:text-cyan-400 dark:border-cyan-900/30';
      case 'snmpv2':
        return 'bg-violet-50/70 text-violet-600 border-violet-100/60 dark:bg-violet-950/20 dark:text-violet-400 dark:border-violet-900/30';
      case 'snmpv3':
        return 'bg-purple-50/70 text-purple-600 border-purple-100/60 dark:bg-purple-950/20 dark:text-purple-400 dark:border-purple-900/30';
      case 'api_token':
      default:
        return 'bg-amber-50/70 text-amber-700 border-amber-100/60 dark:bg-amber-950/20 dark:text-amber-400 dark:border-amber-900/30';
    }
  };

  const getAccountRoleLabel = (role: string) => {
    if (!zh) {
      switch (role) {
        case 'normal': return 'Normal';
        case 'admin': return 'Privileged Account';
        case 'mixed': return 'Mixed';
        case 'shared': return 'Shared';
        case 'unbound': return 'Unbound';
        case 'login':
        default: return 'Login';
      }
    }
    switch (role) {
      case 'normal': return '普通账号';
      case 'admin': return '特权账号';
      case 'mixed': return '多角色';
      case 'shared': return '通用账号';
      case 'unbound': return '未关联';
      case 'login':
      default: return '登录账号';
    }
  };

  const getAccountRoleStyle = (role: string) => {
    switch (role) {
      case 'normal':
        return 'bg-sky-50 text-sky-700 border-sky-100 dark:bg-sky-950/20 dark:text-sky-400 dark:border-sky-900/30';
      case 'admin':
        return 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/20 dark:text-rose-400 dark:border-rose-900/30';
      case 'mixed':
        return 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-950/20 dark:text-amber-400 dark:border-amber-900/30';
      case 'shared':
        return 'bg-violet-50 text-violet-700 border-violet-100 dark:bg-violet-950/20 dark:text-violet-400 dark:border-violet-900/30';
      case 'unbound':
        return 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-900/20 dark:text-slate-400 dark:border-slate-800';
      case 'login':
      default:
        return 'bg-indigo-50 text-indigo-700 border-indigo-100 dark:bg-indigo-950/20 dark:text-indigo-400 dark:border-indigo-900/30';
    }
  };

  const handleRevealCredentialSecret = async (row: any, type: 'password' | 'enable_password') => {
    if (!isAdministrator) return;
    const id = String(row.id || '');
    if (!id) return;
    if (revealedCredentialSecret?.id === id && revealedCredentialSecret.type === type) {
      setRevealedCredentialSecret(null);
      setCredentialSecretCopied(false);
      return;
    }
    const key = `${id}:${type}`;
    setCredentialSecretLoading(key);
    setCredentialSecretCopied(false);
    try {
      const response = await fetch(`/api/credentials/${encodeURIComponent(id)}/secret?type=${encodeURIComponent(type)}`, {
        headers: authHeaders(),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) throw new Error(formatErrorDetail(payload.detail || payload.message));
      setRevealedCredentialSecret({ id, type, secret: String(payload.data?.secret || '') });
    } catch (error: any) {
      setError(error.message || String(error));
    } finally {
      setCredentialSecretLoading(null);
    }
  };

  const handleCopyCredentialSecret = async () => {
    if (!revealedCredentialSecret?.secret) return;
    const { id, type, secret } = revealedCredentialSecret;
    try {
      const auditResponse = await fetch(`/api/credentials/${encodeURIComponent(id)}/secret/copy?type=${encodeURIComponent(type)}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const auditPayload = await auditResponse.json().catch(() => ({}));
      if (!auditResponse.ok || !auditPayload.success) throw new Error(formatErrorDetail(auditPayload.detail || auditPayload.message));
      await navigator.clipboard.writeText(secret);
      setCredentialSecretCopied(true);
      window.setTimeout(() => setCredentialSecretCopied(false), 2000);
    } catch (error: any) {
      setError(error.message || String(error));
    }
  };

  const openBindingModal = (row: any, device: any) => {
    if (!isAdministrator) return;
    setBindingModal({
      credentialId: String(row.id || ''),
      credentialName: String(row.credential_name || row.id || ''),
      deviceId: String(device.id || ''),
      deviceName: String(device.hostname || device.ip_address || device.id || ''),
      bindingRole: device.binding_role === 'admin' ? 'admin' : 'normal',
    });
    setBindingAction('replace');
    setReplacementCredentialId('');
  };

  const submitBindingChange = async () => {
    if (!bindingModal || bindingSaving) return;
    if (bindingAction === 'replace' && !replacementCredentialId) {
      setError(zh ? '请选择替换凭据' : 'Select a replacement credential');
      return;
    }
    setBindingSaving(true);
    setError('');
    try {
      await apiSend(
        `/api/credentials/${encodeURIComponent(bindingModal.credentialId)}/bindings/${encodeURIComponent(bindingModal.deviceId)}`,
        'POST',
        {
          action: bindingAction,
          replacement_credential_id: bindingAction === 'replace' ? replacementCredentialId : undefined,
        },
      );
      setBindingModal(null);
      setNotice(bindingAction === 'replace'
        ? (zh ? '设备凭据已替换，原凭据已保留。' : 'Device credential binding replaced; the original credential was kept.')
        : (zh ? '设备已解除绑定，将按独立设备凭据管理。' : 'Device unbound; it will use independent device credential management.'));
      setExpandedCredentialDevices(previous => ({ ...previous, [bindingModal.credentialId]: false }));
      setCredentialDeviceDetails(previous => {
        const next = { ...previous };
        delete next[bindingModal.credentialId];
        return next;
      });
      await load();
    } catch (error: any) {
      setError(error.message || String(error));
    } finally {
      setBindingSaving(false);
    }
  };

  const renderCell = (row: any, fd: FieldDef) => {
    if (fd.key === 'created_at' || fd.key === 'updated_at' || fd.key === 'last_discovered_at') {
      const raw = String(row[fd.key] || '').trim();
      if (!raw) return <span className="text-black/30 dark:text-white/30">—</span>;
      const parsed = new Date(raw);
      const display = Number.isNaN(parsed.getTime())
        ? raw
        : parsed.toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false });
      return <span className="whitespace-nowrap text-xs">{display}</span>;
    }
    if (tab === 'devices' && fd.key === 'hostname') {
      const val = row.hostname || row.ip_address || row.id;
      return (
        <button
          onClick={() => navigate('/assets/network-devices')}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-cyan-700 hover:text-cyan-900 dark:text-cyan-400 dark:hover:text-cyan-300"
          title={zh ? '查看设备资产' : 'Open device inventory'}
        >
          <Server size={13} />
          {val}
        </button>
      );
    }
    if (tab === 'interfaces' && fd.key === 'device_hostname') {
      const val = row.device_hostname || row.device_ip || row.device_id;
      return (
        <button
          onClick={() => navigate('/assets/network-devices')}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-cyan-700 hover:text-cyan-900 dark:text-cyan-400 dark:hover:text-cyan-300"
          title={zh ? '查看设备资产' : 'Open device inventory'}
        >
          <Server size={13} />
          {val}
        </button>
      );
    }
    if (['interface_count', 'ip_count', 'link_count'].includes(fd.key)) {
      const val = Number(row[fd.key] || 0);
      return (
        <span className="inline-flex min-w-8 justify-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {val}
        </span>
      );
    }
    if (fd.key === 'devices') {
      const devList = row.devices || [];
      if (devList.length === 0) return <span className="text-black/30 dark:text-white/30">—</span>;
      const credentialId = String(row.id || '');
      const isExpanded = Boolean(expandedCredentialDevices[credentialId]);
      const fullList = credentialDeviceDetails[credentialId];
      const displayList = isExpanded && fullList ? fullList : devList;
      const total = Number(row.device_count ?? fullList?.length ?? devList.length);
      const hiddenCount = Math.max(0, total - displayList.length);
      const toggleDetails = async () => {
        if (isExpanded) {
          setExpandedCredentialDevices(previous => ({ ...previous, [credentialId]: false }));
          return;
        }
        setExpandedCredentialDevices(previous => ({ ...previous, [credentialId]: true }));
        if (fullList || !row.devices_truncated) return;
        setCredentialDeviceLoading(previous => ({ ...previous, [credentialId]: true }));
        try {
          const response = await fetch(`/api/credentials/${encodeURIComponent(credentialId)}`, { headers: authHeaders() });
          const payload = await response.json();
          if (!response.ok || !payload.success) throw new Error(formatErrorDetail(payload.detail || payload.message));
          setCredentialDeviceDetails(previous => ({ ...previous, [credentialId]: payload.data?.devices || [] }));
        } catch (error: any) {
          setError(error.message || String(error));
          setExpandedCredentialDevices(previous => ({ ...previous, [credentialId]: false }));
        } finally {
          setCredentialDeviceLoading(previous => ({ ...previous, [credentialId]: false }));
        }
      };
      return (
        <div className="flex max-w-[34rem] flex-wrap items-center gap-1">
          {displayList.slice(0, isExpanded ? displayList.length : 3).map((d: any) => (
            <span key={d.id} className="inline-flex items-center gap-1">
              <button
                type="button"
                onClick={() => navigate(`/assets/network-devices`)}
                className="inline-flex items-center gap-1 rounded-l border border-slate-200/50 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-350 dark:hover:bg-slate-750"
              >
                <Server size={11} className="text-slate-400" />
                {d.hostname || d.ip_address || d.id}
              </button>
              {isAdministrator && (
                <button
                  type="button"
                  onClick={() => openBindingModal(row, d)}
                  className="-ml-1 inline-flex items-center gap-0.5 rounded-r border border-cyan-200 bg-cyan-50 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-700 hover:bg-cyan-100"
                  title={zh ? '替换或解除该设备的凭据绑定' : 'Replace or unbind this device credential'}
                >
                  {d.binding_role === 'admin' ? (zh ? '特权' : 'Priv') : (zh ? '普通' : 'Normal')}
                </button>
              )}
            </span>
          ))}
          {total > 3 && (
            <button
              type="button"
              onClick={() => { void toggleDetails(); }}
              className="inline-flex items-center gap-0.5 rounded border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-100"
              title={zh ? '按需查看全部关联设备' : 'Load all associated devices on demand'}
            >
              {credentialDeviceLoading[credentialId] ? <RefreshCw size={10} className="animate-spin" /> : isExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
              {isExpanded ? (zh ? '收起' : 'Collapse') : `+${hiddenCount} ${zh ? '台' : 'more'}`}
            </button>
          )}
        </div>
      );
    }
    if (fd.secretFlag) {
      if (!row[fd.secretFlag]) return <span className="text-black/30 dark:text-white/30">—</span>;
      if (tab === 'credentials' && isAdministrator) {
        const type = fd.secretFlag === 'has_enable_password' ? 'enable_password' : 'password';
        const credentialId = String(row.id || '');
        const key = `${credentialId}:${type}`;
        const isRevealed = revealedCredentialSecret?.id === credentialId && revealedCredentialSecret.type === type;
        return (
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-900/30 px-2 py-0.5 rounded text-xs font-medium">
              <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
              {zh ? '已配置' : 'Configured'}
            </span>
            <button
              type="button"
              onClick={() => { void handleRevealCredentialSecret(row, type); }}
              className={`inline-flex h-6 w-6 items-center justify-center rounded-md border ${isRevealed ? 'border-cyan-500 bg-cyan-500 text-white' : 'border-slate-200 bg-white text-slate-400 hover:border-cyan-300 hover:text-cyan-600'}`}
              title={isRevealed ? (zh ? '隐藏密码' : 'Hide secret') : (zh ? '查看凭据密码' : 'Reveal credential secret')}
            >
              {credentialSecretLoading === key ? <RefreshCw size={11} className="animate-spin" /> : isRevealed ? <EyeOff size={11} /> : <Eye size={11} />}
            </button>
            {isRevealed && (
              <button
                type="button"
                onClick={() => { void handleCopyCredentialSecret(); }}
                className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-400 hover:border-cyan-300 hover:text-cyan-600"
                title={zh ? '复制并记录审计' : 'Copy and audit'}
              >
                {credentialSecretCopied ? <Check size={11} /> : <Copy size={11} />}
              </button>
            )}
            {isRevealed && <span className="max-w-36 truncate rounded bg-slate-900 px-2 py-1 font-mono text-[10px] text-cyan-300" title={revealedCredentialSecret.secret}>{revealedCredentialSecret.secret}</span>}
          </div>
        );
      }
      return row[fd.secretFlag] ? (
        <span className="inline-flex items-center gap-1 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-900/30 px-2 py-0.5 rounded text-xs font-medium">
          <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
          {zh ? '已配置' : 'Configured'}
        </span>
      ) : (
        <span className="text-black/30 dark:text-white/30">—</span>
      );
    }
    if (fd.key === 'vrf_id') {
      const vrf = vrfs.find(x => x.id === row.vrf_id);
      return <span>{vrf?.vrf_name || row.vrf_id || '-'}</span>;
    }
    if (['device_count', 'port_count', 'mac_count', 'arp_count', 'prefix_count', 'undocumented_port_count'].includes(fd.key)) {
      const count = Number(row[fd.key] || 0);
      const warning = fd.key === 'undocumented_port_count' && count > 0;
      return <span className={`inline-flex min-w-8 justify-center rounded-full border px-2 py-0.5 text-xs font-semibold ${warning ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'}`}>{count}</span>;
    }
    if (fd.key === 'site_id') {
      const s = sites.find(x => x.id === row.site_id);
      return s ? (
        <span className="inline-flex items-center gap-1 text-cyan-700 dark:text-cyan-400 bg-cyan-50 dark:bg-cyan-950/20 border border-cyan-100 dark:border-cyan-900/30 px-2 py-0.5 rounded text-xs font-semibold">
          <Building2 size={12} />
          {s.site_name}
        </span>
      ) : (
        <span className="text-black/30 dark:text-white/30">—</span>
      );
    }
    if (fd.key === 'status') {
      const val = row[fd.key] || 'active';
      const badgeClass = tab === 'sites' || tab === 'devices' ? getSiteStatusStyle(val) : getVlanStatusStyle(val);
      const siteStatusLabel = SITE_STATUS_OPTS.find(option => option.value === val);
      return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${badgeClass}`}>
          {zh && siteStatusLabel ? siteStatusLabel.label : (!zh && siteStatusLabel ? siteStatusLabel.labelEn : val)}
        </span>
      );
    }
    if (tab === 'sites' && ['country', 'state_province', 'city'].includes(fd.key)) {
      const val = String(row[fd.key] || '').trim();
      if (!val) return <span className="text-black/30 dark:text-white/30">—</span>;
      const isChina = CHINA_LEGACY_COUNTRY_VALUES.has(String(row.country || '').trim());
      if (fd.key === 'country') {
        const country = geoCatalog?.countries.find(item => matchesGeoValue(val, item.name, item.isoCode, countryDisplayName(item)));
        return <span>{country ? countryDisplayName(country) : val}</span>;
      }
      if (!isChina) return <span>{val}</span>;
      if (fd.key === 'state_province') {
        const state = geoCatalog?.states.find(item => item.countryCode === 'CN' && matchesGeoValue(val, item.name, item.isoCode, stateDisplayName(item)));
        return <span>{state ? stateDisplayName(state) : val}</span>;
      }
      const state = geoCatalog?.states.find(item => item.countryCode === 'CN' && matchesGeoValue(String(row.state_province || ''), item.name, item.isoCode, stateDisplayName(item)));
      return <span>{cityDisplayName({ name: val, stateCode: state?.isoCode || '', countryCode: 'CN' })}</span>;
    }
    if (fd.key === 'oper_status' || fd.key === 'admin_status') {
      const val = row[fd.key] || 'unknown';
      const statusLabel = val === 'unknown' ? (zh ? '未采集' : 'Not collected') : val;
      const badgeClass = val === 'up'
        ? 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/20 dark:text-emerald-400 dark:border-emerald-900/30'
        : val === 'down'
          ? 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/20 dark:text-rose-400 dark:border-rose-900/30'
          : 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-900/20 dark:text-slate-400 dark:border-slate-800';
      return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${badgeClass}`}>
          {statusLabel}
        </span>
      );
    }
    if (fd.key === 'credential_type') {
      const val = row[fd.key];
      if (!val) return <span className="text-black/30 dark:text-white/30">—</span>;
      return (
        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full border text-[11px] font-medium tracking-wide shadow-sm/5 ${getCredTypeStyle(val)}`}>
          {getCredTypeLabel(val)}
        </span>
      );
    }
    if (fd.key === 'account_role') {
      const role = row.account_role || 'login';
      return (
        <span
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full border text-[11px] font-semibold tracking-wide ${getAccountRoleStyle(role)}`}
          title={zh ? '凭据角色由人工设置，历史数据可根据绑定设备兼容推断' : 'Role is explicit when set; legacy data may be inferred from linked devices'}
        >
          {getAccountRoleLabel(role)}
        </span>
      );
    }

    const isMono = ['vlan_id', 'rd', 'username', 'ip_address', 'device_ip', 'interface_ip', 'mac_address', 'access_vlan'].includes(fd.key);
    const val = row[fd.key];
    if (val === '' || val == null) return <span className="text-black/30 dark:text-white/30">—</span>;
    const displayValue = fd.key === 'mac_address' ? formatMacAddress(val) : String(val);
    if (isMono) {
      return (
        <span className="font-mono text-xs text-black/75 dark:text-white/75 bg-black/[0.03] dark:bg-white/5 px-1.5 py-0.5 rounded border border-black/[0.04] dark:border-white/5">
          {displayValue}
        </span>
      );
    }
    return <span className="text-sm font-medium text-black/75 dark:text-white/85">{displayValue}</span>;
  };

  const filteredRows = useMemo(() => {
    if (!search.trim()) return rows;
    const q = search.toLowerCase();
    const cols = fieldDefs[tab];
    return rows.filter(row => {
      return cols.some(c => {
        const val = row[c.key];
        if (val === '' || val == null) return false;
        return String(val).toLowerCase().includes(q);
      });
    });
  }, [rows, tab, search, fieldDefs]);

  // Compute pagination values
  const totalForTab = (tab === 'sites' || tab === 'vrfs') ? genericListMeta.total : filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(totalForTab / pageSize));
  
  // Clamp page selection
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const paginatedRows = useMemo(() => {
    if (tab === 'sites' || tab === 'vrfs') return filteredRows;
    const start = (page - 1) * pageSize;
    return filteredRows.slice(start, start + pageSize);
  }, [filteredRows, page, pageSize, tab]);

  const vlanFilteredRows = useMemo(() => tab === 'vlans' ? rows : [], [rows, tab]);

  const vlanScopeLabel = useCallback((node: any) => {
    const labels: Record<string, string> = {
      network_device: zh ? '网络设备' : 'Network devices',
      server: zh ? '服务器' : 'Servers',
      other: zh ? '其他资产' : 'Other assets',
      router: zh ? '路由器' : 'Routers',
      switch: zh ? '交换机' : 'Switches',
      firewall: zh ? '防火墙' : 'Firewalls',
      load_balancer: zh ? '负载均衡' : 'Load balancers',
      unassigned: zh ? '未分配' : 'Unassigned',
    };
    return node.kind === 'root' ? (zh ? '全部资产' : 'All assets') : labels[String(node.label)] || node.label || (zh ? '未分配' : 'Unassigned');
  }, [zh]);

  const selectVlanTreeBranch = useCallback((node: any) => {
    const branch = node.branch || {};
    setVlanTreeBranch(branch);
    setVlanSiteFilter(String(branch.site_id || ''));
    setPage(1);
  }, []);

  const toggleVlanTreeNode = useCallback((nodeId: string) => {
    setExpandedVlanTree((current) => ({ ...current, [nodeId]: !current[nodeId] }));
  }, []);

  const renderVlanTreeNode = (node: any, depth = 0): React.ReactNode => {
    const expanded = expandedVlanTree[node.id] !== false;
    const selected = JSON.stringify(vlanTreeBranch) === JSON.stringify(node.branch || {});
    const Icon = node.kind === 'root' ? Layers : node.kind === 'site' ? FolderTree : node.kind === 'type' ? Server : node.kind === 'category' ? Network : UsersIcon;
    return (
      <div key={node.id}>
        <div className={`group flex items-center gap-1.5 rounded-lg px-2 py-2 text-xs ${selected ? 'bg-cyan-50 text-cyan-800' : 'text-slate-600 hover:bg-slate-50'}`} style={{ paddingLeft: `${8 + depth * 14}px` }}>
          {node.children?.length ? <button type="button" onClick={() => toggleVlanTreeNode(node.id)} className="shrink-0 text-slate-400" aria-label={expanded ? 'Collapse' : 'Expand'}><ChevronRight size={14} className={expanded ? 'rotate-90 transition-transform' : 'transition-transform'} /></button> : <span className="w-[14px]" />}
          <button type="button" onClick={() => selectVlanTreeBranch(node)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
            <Icon size={14} className={node.kind === 'site' ? 'text-cyan-600' : node.kind === 'type' ? 'text-indigo-500' : 'text-slate-400'} />
            <span className="truncate">{vlanScopeLabel(node)}</span>
            <span className="ml-auto rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-500">{node.count || 0}</span>
          </button>
        </div>
        {expanded && node.children?.map((child: any) => renderVlanTreeNode(child, depth + 1))}
      </div>
    );
  };

  const vlanTotalPages = Math.max(1, Math.ceil(vlanListMeta.total / pageSize));
  const paginatedVlanRows = vlanFilteredRows;

  const vlanSummary = vlanListMeta.summary;

  useEffect(() => {
    if (tab === 'vlans' && page > vlanTotalPages) setPage(vlanTotalPages);
  }, [page, tab, vlanTotalPages]);

  const interfaceGroups = useMemo(() => {
    if (tab !== 'interfaces') return [] as Array<{ key: string; hostname: string; deviceIp: string; rows: any[] }>;
    const grouped = new Map<string, { key: string; hostname: string; deviceIp: string; rows: any[] }>();
    (tab === 'interfaces' ? rows : paginatedRows).forEach(row => {
      const key = String(row.device_id || row.device_ip || row.device_hostname || 'unknown-device');
      const current = grouped.get(key) || {
        key,
        hostname: String(row.device_hostname || 'Unknown device'),
        deviceIp: String(row.device_ip || ''),
        rows: [],
      };
      current.rows.push(row);
      grouped.set(key, current);
    });
    return Array.from(grouped.values());
  }, [paginatedRows, rows, tab]);

  const renderDataRow = (row: any, index: number | string) => (
    <tr key={idOf(row) || index} className="hover:bg-slate-50/80 transition-colors group">
      {tableColumns.map(c => (
        <td key={c.key} className="px-6 py-4">{renderCell(row, c)}</td>
      ))}
      {!isReadOnlyTab && (
        <td className="px-6 py-4 text-right whitespace-nowrap align-middle">
          <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={() => openEdit(row)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent bg-white text-[#164e63] shadow-sm hover:border-black/10 hover:bg-[#ecfeff] hover:text-[#0891b2] transition-all"
              title={zh ? '编辑' : 'Edit'}
            >
              <Edit2 size={13} />
            </button>
            <button
              onClick={() => openDeleteConfirm(row)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent bg-white text-rose-400 shadow-sm hover:border-rose-100 hover:bg-rose-50 hover:text-rose-600 transition-all"
              title={zh ? '删除' : 'Delete'}
            >
              <Trash2 size={13} />
            </button>
          </div>
        </td>
      )}
    </tr>
  );

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Server}
        eyebrow={zh ? '资产与配置 / CMDB' : 'Assets & Config / CMDB'}
        title={zh ? 'CMDB 基础数据维护' : 'CMDB Inventory'}
        subtitle={zh ? '管理设备、接口、凭据、站点、VRF、VLAN 与租户等核心配置数据。' : 'Manage devices, interfaces, credentials, sites, VRFs, VLANs and tenants.'}
        actions={
          <>
            {!isReadOnlyTab && (
              <button
                onClick={openCreate}
                className="inline-flex h-10 items-center justify-center gap-1.5 rounded-full bg-[#00bceb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(0,188,235,0.24)] transition-all duration-200 hover:-translate-y-0.5 hover:bg-[#00a5d0]"
              >
                <Plus size={14} />
                {zh ? '新建记录' : 'New Record'}
              </button>
            )}
            {tab === 'interfaces' && (
              <button
                onClick={triggerInterfaceSync}
                disabled={interfaceSyncing}
                className="inline-flex h-10 items-center justify-center gap-1.5 rounded-full border border-[#9eeaf7] bg-[#f1fcff] px-4 text-xs font-semibold text-[#007d9d] transition-all duration-200 hover:-translate-y-0.5 hover:bg-[#e5faff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw size={14} className={interfaceSyncing ? 'animate-spin' : ''} />
                {zh ? '立即采集接口' : 'Collect Interfaces'}
              </button>
            )}
            {tab === 'sites' && (
              <>
                <input
                  ref={siteImportInputRef}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  className="hidden"
                  onChange={event => { void handleSiteImportFile(event.target.files?.[0]); }}
                />
                <button
                  onClick={downloadSiteImportTemplate}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-black/8 bg-white text-black/35 transition-colors hover:border-[#00bceb]/25 hover:bg-[#00bceb]/5 hover:text-[#0088b0]"
                  title={zh ? '下载导入模板' : 'Download template'}
                  aria-label={zh ? '下载导入模板' : 'Download template'}
                >
                  <FileSpreadsheet size={14} />
                </button>
                <button
                  onClick={() => siteImportInputRef.current?.click()}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-black/8 bg-white text-black/35 transition-colors hover:border-[#00bceb]/25 hover:bg-[#00bceb]/5 hover:text-[#0088b0]"
                  title={zh ? '导入站点' : 'Import sites'}
                  aria-label={zh ? '导入站点' : 'Import sites'}
                >
                  <Upload size={14} />
                </button>
                <button
                  onClick={exportSiteInventory}
                  disabled={siteExporting}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-black/8 bg-white text-black/35 transition-colors hover:border-[#00bceb]/25 hover:bg-[#00bceb]/5 hover:text-[#0088b0] disabled:cursor-not-allowed disabled:opacity-50"
                  title={zh ? '导出站点' : 'Export sites'}
                  aria-label={zh ? '导出站点' : 'Export sites'}
                >
                  <Download size={14} className={siteExporting ? 'animate-pulse' : ''} />
                </button>
              </>
            )}
            {tab === 'credentials' && (
              <>
                <input
                  ref={credentialImportInputRef}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  className="hidden"
                  onChange={event => { void handleCredentialImportFile(event.target.files?.[0]); }}
                />
                <button
                  onClick={downloadCredentialImportTemplate}
                  disabled={credentialTemplateDownloading}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-black/8 bg-white text-black/35 transition-colors hover:border-[#00bceb]/25 hover:bg-[#00bceb]/5 hover:text-[#0088b0] disabled:cursor-not-allowed disabled:opacity-50"
                  title={zh ? '下载凭据导入模板' : 'Download credential import template'}
                  aria-label={zh ? '下载凭据导入模板' : 'Download credential import template'}
                >
                  <FileSpreadsheet size={14} className={credentialTemplateDownloading ? 'animate-pulse' : ''} />
                </button>
                <button
                  onClick={() => credentialImportInputRef.current?.click()}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#9eeaf7] bg-[#f1fcff] text-[#007d9d] transition-colors hover:border-[#00bceb]/50 hover:bg-[#e5faff]"
                  title={zh ? '上传凭据' : 'Upload credentials'}
                  aria-label={zh ? '上传凭据' : 'Upload credentials'}
                >
                  <Upload size={14} />
                </button>
                <button
                  onClick={exportCredentialInventory}
                  disabled={credentialExporting}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-black/8 bg-white text-black/35 transition-colors hover:border-[#00bceb]/25 hover:bg-[#00bceb]/5 hover:text-[#0088b0] disabled:cursor-not-allowed disabled:opacity-50"
                  title={zh ? '导出凭据（密码为空）' : 'Export credentials (passwords blank)'}
                  aria-label={zh ? '导出凭据（密码为空）' : 'Export credentials (passwords blank)'}
                >
                  <Download size={14} className={credentialExporting ? 'animate-pulse' : ''} />
                </button>
              </>
            )}
            <button
              onClick={load}
              className="inline-flex h-10 items-center justify-center gap-1.5 rounded-full border border-[#d8e5ef] bg-[#f8fafc] px-4 text-xs font-semibold text-[#164e63] transition-all duration-200 hover:-translate-y-0.5 hover:border-[#9eeaf7] hover:bg-white hover:text-[#007d9d]"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </>
        }
        extras={
          <div className="flex items-center justify-end gap-4 mt-3 flex-wrap">
            {tab === 'vlans' && (
              <select
                value={vlanStatusFilter}
                onChange={e => { setVlanStatusFilter(e.target.value); setPage(1); }}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 outline-none focus:ring-2 focus:ring-cyan-500"
              >
                <option value="all">{zh ? '所有状态' : 'All Status'}</option>
                <option value="active">{zh ? '使用中' : 'Active'}</option>
                <option value="reserved">{zh ? '已保留' : 'Reserved'}</option>
                <option value="deprecated">{zh ? '已弃用' : 'Deprecated'}</option>
              </select>
            )}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                placeholder={tab === 'interfaces'
                  ? (zh ? '搜索设备名、设备 IP、接口名或接口 IP...' : 'Search device name/IP, interface name/IP...')
                  : tab === 'vlans'
                    ? (zh ? '搜索 VLAN、网段、网关、设备或业务...' : 'Search VLAN, prefix, gateway, device or business...')
                  : (zh ? '搜索当前列表...' : 'Search current list...')}
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-10 pr-9 py-2 bg-slate-100 border-none rounded-lg text-sm focus:ring-2 focus:ring-cyan-500 w-64 transition-all outline-none"
              />
              {search && (
                <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                  <X size={14} />
                </button>
              )}
            </div>
          </div>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5" style={{ background: 'rgba(248, 250, 252, 0.5)' }}>
        {error && tab !== 'credentials' && (
          <div className="mb-4 px-4 py-3 rounded-2xl text-sm flex items-center gap-2 border bg-rose-50/10 text-rose-500 border-rose-200/30">
            <ShieldAlert size={16} />
            {error}
          </div>
        )}
        {notice && (
          <div className="mb-4 px-4 py-3 rounded-2xl text-sm flex items-center gap-2 border bg-emerald-50 text-emerald-700 border-emerald-200">
            <Check size={16} />
            {notice}
          </div>
        )}

        {tab === 'interfaces' && interfaceJobStatus?.job_id && (() => {
          const targets = Array.isArray(interfaceJobStatus.targets) ? interfaceJobStatus.targets : [];
          const failedTargets = targets.filter((target: any) => ['failed', 'timeout'].includes(String(target.status || '').toLowerCase()));
          const runningTargets = targets.filter((target: any) => String(target.status || '').toLowerCase() === 'running');
          const visibleTargets = [...failedTargets, ...runningTargets.slice(0, 8)];
          const totalCount = Number(interfaceJobStatus.total_targets || targets.length || 0);
          const successCount = Number(interfaceJobStatus.success_count || 0);
          const failedCount = Number(interfaceJobStatus.failed_count || 0);
          const completedCount = successCount + failedCount + Number(interfaceJobStatus.cancelled_count || 0);
          const progress = Math.max(0, Math.min(100, Number(interfaceJobStatus.progress || (totalCount ? (completedCount / totalCount) * 100 : 0))));
          const jobStatus = String(interfaceJobStatus.status || 'queued').toLowerCase();
          const statusLabel = jobStatus === 'succeeded'
            ? (zh ? '已完成' : 'Succeeded')
            : jobStatus === 'partially_failed'
              ? (zh ? '部分失败' : 'Partially failed')
              : jobStatus === 'failed'
                ? (zh ? '失败' : 'Failed')
                : jobStatus === 'running'
                  ? (zh ? '采集中' : 'Collecting')
                  : (zh ? '排队中' : 'Queued');
          return (
            <div className={`mb-4 rounded-2xl border px-4 py-3 ${failedTargets.length ? 'border-rose-200 bg-rose-50/70' : 'border-cyan-200 bg-cyan-50/70'}`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Network size={16} className={failedTargets.length ? 'text-rose-600' : 'text-cyan-600'} />
                  <div>
                    <div className="text-sm font-semibold text-[#164e63]">
                      {zh ? '接口状态采集进度' : 'Interface status collection'}
                      <span className="ml-2 rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-medium text-slate-500">{statusLabel}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      {zh ? `任务 ${interfaceJobStatus.job_id} · 使用 Playbook 接口状态 TextFSM · ${successCount} 成功 / ${failedCount} 失败 / ${totalCount} 总计` : `Job ${interfaceJobStatus.job_id} · Playbook interface-status TextFSM · ${successCount} succeeded / ${failedCount} failed / ${totalCount} total`}
                    </div>
                  </div>
                </div>
                <span className="text-sm font-bold text-cyan-700">{Math.round(progress)}%</span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/80">
                <div className={`h-full rounded-full transition-all ${failedTargets.length ? 'bg-rose-500' : 'bg-cyan-500'}`} style={{ width: `${progress}%` }} />
              </div>
              {(visibleTargets.length > 0 || runningTargets.length > 8 || interfaceJobStatus.targets_truncated) && (
                <div className="mt-3 max-h-44 space-y-1.5 overflow-y-auto pr-1">
                  {runningTargets.length > 8 && <div className="rounded-lg border border-white/80 bg-white/70 px-3 py-2 text-xs text-slate-500">正在处理 {runningTargets.length} 台设备，仅展示前 8 台；完成设备不在进度区重复列出。</div>}
                  {interfaceJobStatus.targets_truncated && <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">设备数量较多，仅展示进行中和异常设备的部分明细。</div>}
                  {visibleTargets.map((target: any) => {
                    const targetStatus = String(target.status || 'queued').toLowerCase();
                    const failed = ['failed', 'timeout'].includes(targetStatus);
                    const targetLabel = target.target_hostname || target.target_ip || target.target_id;
                    const targetStatusLabel = targetStatus === 'succeeded'
                      ? (zh ? '成功' : 'Succeeded')
                      : failed
                        ? (zh ? '失败' : 'Failed')
                        : targetStatus === 'running'
                          ? (zh ? '采集中' : 'Collecting')
                          : (zh ? '等待中' : 'Queued');
                    return (
                      <div key={target.id || target.target_id} className={`rounded-lg border px-3 py-2 text-xs ${failed ? 'border-rose-200 bg-white text-rose-700' : 'border-white/80 bg-white/70 text-slate-600'}`}>
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium">{targetLabel}</span>
                          <span className="font-semibold">{targetStatusLabel}</span>
                        </div>
                        {failed && target.error_message && <div className="mt-1 leading-5 text-rose-600">{target.error_message}</div>}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })()}

        {tab === 'credentials' && credentialJobStatus?.job_id && (() => {
          const targets = Array.isArray(credentialJobStatus.targets) ? credentialJobStatus.targets : [];
          const failedTargets = targets.filter((target: any) => ['failed', 'timeout'].includes(String(target.status || '').toLowerCase()));
          const completedCount = Number(credentialJobStatus.success_count || 0)
            + Number(credentialJobStatus.failed_count || 0)
            + Number(credentialJobStatus.cancelled_count || 0);
          const totalCount = Number(credentialJobStatus.total_targets || targets.length || 0);
          const progress = Math.max(0, Math.min(100, Number(credentialJobStatus.progress || (totalCount ? (completedCount / totalCount) * 100 : 0))));
          const jobStatus = String(credentialJobStatus.status || 'queued').toLowerCase();
          const statusLabel = jobStatus === 'succeeded'
            ? (zh ? '已完成' : 'Succeeded')
            : jobStatus === 'partially_failed'
              ? (zh ? '部分失败' : 'Partially failed')
              : jobStatus === 'failed'
                ? (zh ? '失败' : 'Failed')
                : jobStatus === 'running'
                  ? (zh ? '执行中' : 'Running')
                  : (zh ? '排队中' : 'Queued');
          return (
            <div className={`mb-4 rounded-2xl border px-4 py-3 ${failedTargets.length ? 'border-rose-200 bg-rose-50/70' : 'border-cyan-200 bg-cyan-50/70'}`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <KeyRound size={16} className={failedTargets.length ? 'text-rose-600' : 'text-cyan-600'} />
                  <div>
                    <div className="text-sm font-semibold text-[#164e63]">
                      {zh ? '密码同步进度' : 'Password sync progress'}
                      <span className="ml-2 rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-medium text-slate-500">{statusLabel}</span>
                    </div>
                    <div className="mt-0.5 font-mono text-[10px] text-black/45">{credentialJobStatus.job_id}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-slate-600">{credentialJobStatus.success_count || 0} / {totalCount} {zh ? '成功' : 'succeeded'}</span>
                  <button type="button" onClick={() => navigate('/automation/history')} className="rounded-lg border border-cyan-200 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-cyan-700 hover:bg-cyan-50">
                    {zh ? '执行历史' : 'Execution history'}
                  </button>
                  <button type="button" onClick={() => setCredentialJobDetailsOpen(previous => !previous)} className="rounded-lg border border-black/10 bg-white p-1.5 text-black/45 hover:bg-black/[0.03]" title={credentialJobDetailsOpen ? (zh ? '收起详情' : 'Collapse') : (zh ? '展开详情' : 'Expand')}>
                    {credentialJobDetailsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                </div>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/80">
                <div className={`h-full rounded-full transition-all ${failedTargets.length ? 'bg-rose-500' : 'bg-cyan-500'}`} style={{ width: `${progress}%` }} />
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-black/45">
                <span>{zh ? `已完成 ${completedCount} / ${totalCount} 台` : `${completedCount} / ${totalCount} targets completed`}</span>
                <span>{Math.round(progress)}%</span>
              </div>
              {credentialJobDetailsOpen && (
                <div className="mt-3 space-y-1.5">
                  <div className="flex flex-wrap gap-3 text-[11px] font-medium text-slate-500">
                    <span className="text-emerald-600">✓ {zh ? '成功' : 'Succeeded'} {credentialJobStatus.success_count || 0}</span>
                    <span className="text-rose-600">✕ {zh ? '失败' : 'Failed'} {credentialJobStatus.failed_count || 0}</span>
                    <span className="text-slate-500">◷ {zh ? '运行中/排队' : 'Running/queued'} {Math.max(0, totalCount - completedCount)}</span>
                  </div>
                  {failedTargets.length > 0 ? (
                    <div className="rounded-xl border border-rose-200 bg-white/80 p-2.5">
                      <div className="mb-1.5 text-xs font-semibold text-rose-700">{zh ? '失败设备（凭据中心未更新）' : 'Failed targets (vault unchanged)'}</div>
                      {failedTargets.map((target: any) => (
                        <div key={target.id || target.target_id} className="flex flex-wrap items-start justify-between gap-2 border-t border-rose-100 py-1.5 text-[11px]">
                          <span className="font-medium text-slate-700">{target.target_hostname || target.target_id}{target.target_ip ? ` · ${target.target_ip}` : ''}</span>
                          <span className="max-w-full text-rose-600 sm:max-w-[68%]">{target.error_message || (zh ? '设备执行失败，请查看后端日志。' : 'Target execution failed; check backend logs.')}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-[11px] text-black/45">{jobStatus === 'succeeded' ? (zh ? '全部设备验证成功，凭据中心已提交新密码。' : 'All devices verified; the vault has committed the new password.') : (zh ? '任务正在处理，完成后会在这里显示每台设备结果。' : 'The job is still processing; target results will appear here.')}</div>
                  )}
                </div>
              )}
            </div>
          );
        })()}

        {tab === 'interfaces' && (
          <div className="mb-5 space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                <div className="text-xs font-medium text-slate-500">{zh ? '接口总数' : 'Total Interfaces'}</div>
                <div className="mt-1 text-2xl font-bold text-slate-800 dark:text-slate-100">{interfaceStats.total}</div>
              </div>
              <div className="rounded-2xl border border-emerald-200/80 bg-emerald-50/40 p-4 shadow-sm dark:border-emerald-900/30 dark:bg-emerald-950/20">
                <div className="text-xs font-medium text-emerald-700 dark:text-emerald-400">{zh ? '配置 IP 接口数' : 'Configured IP Interfaces'}</div>
                <div className="mt-1 text-2xl font-bold text-emerald-800 dark:text-emerald-300">{interfaceStats.withIp}</div>
              </div>
              <div className="rounded-2xl border border-cyan-200/80 bg-cyan-50/40 p-4 shadow-sm dark:border-cyan-900/30 dark:bg-cyan-950/20">
                <div className="text-xs font-medium text-cyan-700 dark:text-cyan-400">{zh ? 'Up 状态接口' : 'Oper Status Up'}</div>
                <div className="mt-1 text-2xl font-bold text-cyan-800 dark:text-cyan-300">{interfaceStats.operUp}</div>
              </div>
              <div className="rounded-2xl border border-purple-200/80 bg-purple-50/40 p-4 shadow-sm dark:border-purple-900/30 dark:bg-purple-950/20">
                <div className="text-xs font-medium text-purple-700 dark:text-purple-400">{zh ? '关联拓扑接口' : 'Linked Interfaces'}</div>
                <div className="mt-1 text-2xl font-bold text-purple-800 dark:text-purple-300">{interfaceStats.withLinks}</div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-4 flex-wrap bg-white dark:bg-slate-900 p-3 rounded-2xl border border-black/5 shadow-sm">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-cyan-700 pl-1">{zh ? `仅展示已配置 IP 的三层接口 (${interfaceStats.withIp})；状态来自接口采集` : `L3 interfaces with IP only (${interfaceStats.withIp}); status comes from interface collection`}</span>
              </div>

              {interfaceDeviceOptions.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-slate-500">{zh ? '所属设备：' : 'Device:'}</span>
                  <select
                    value={interfaceDeviceFilter}
                    onChange={e => { setInterfaceDeviceFilter(e.target.value); setInterfacePage(1); }}
                    className="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-medium text-slate-700 dark:text-slate-200 outline-none focus:ring-2 focus:ring-cyan-500"
                  >
                    <option value="">{zh ? '全部设备' : 'All Devices'}</option>
                    {interfaceDeviceOptions.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'vlans' ? (
          <div className={`grid grid-cols-1 gap-5 ${vlanTreeCollapsed ? 'xl:grid-cols-[56px_minmax(0,1fr)]' : 'xl:grid-cols-[240px_minmax(0,1fr)]'}`}>
            <aside className={`relative rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)] ${vlanTreeCollapsed ? 'p-2' : 'p-4'}`}>
              <div className={`border-b border-black/5 px-2 pb-3 ${vlanTreeCollapsed ? 'hidden' : ''}`}>
                <div className="text-sm font-semibold text-[#164e63]">资产分类</div>
                <div className="mt-1 text-xs text-slate-400">按站点查看 VLAN 与网段</div>
              </div>
              <button
                type="button"
                onClick={() => setVlanTreeCollapsed((current) => !current)}
                className={`rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-cyan-50 hover:text-cyan-700 ${vlanTreeCollapsed ? 'mx-auto block' : 'absolute right-5 top-5'}`}
                title={vlanTreeCollapsed ? (zh ? '展开 VLAN 分类' : 'Expand VLAN tree') : (zh ? '折叠 VLAN 分类' : 'Collapse VLAN tree')}
                aria-label={vlanTreeCollapsed ? (zh ? '展开 VLAN 分类' : 'Expand VLAN tree') : (zh ? '折叠 VLAN 分类' : 'Collapse VLAN tree')}
              >
                {vlanTreeCollapsed ? <FolderTree size={15} /> : <ChevronRight size={15} className="rotate-180" />}
              </button>
              <div className={`mt-3 space-y-1 ${vlanTreeCollapsed ? 'hidden' : ''}`}>
                {vlanScopeTree.length ? vlanScopeTree.map((node) => renderVlanTreeNode(node)) : (
                  <button type="button" onClick={() => { setVlanTreeBranch({}); setVlanSiteFilter(''); setPage(1); }} className="flex w-full items-center justify-between rounded-xl bg-cyan-50 px-3 py-2.5 text-left text-sm font-semibold text-cyan-700">
                    <span className="inline-flex items-center gap-2"><Layers size={14} />鍏ㄩ儴璧勪骇</span>
                    <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-500 shadow-sm">{vlanListMeta.total}</span>
                  </button>
                )}
              </div>
            </aside>

            <section className="min-w-0 rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)]">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/5 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-[#164e63]">VLAN 清单</h2>
                   <p className="mt-1 text-xs text-slate-400">以站点为维度聚合，优先查看网关、终端和业务责任；展开行查看完整明细</p>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2 text-xs text-slate-500">
                  <span className="rounded-full bg-cyan-50 px-2.5 py-1 font-semibold text-cyan-700">{vlanListMeta.total} 条记录</span>
                  {vlanSiteFilter && <button type="button" onClick={() => { setVlanTreeBranch({}); setVlanSiteFilter(''); setPage(1); }} className="text-cyan-700 hover:text-cyan-900">清除站点筛选</button>}
                  <button type="button" onClick={() => void exportVlanInventory()} disabled={vlanExporting} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-200 bg-white px-3 py-1.5 font-semibold text-cyan-700 shadow-sm transition-colors hover:border-cyan-300 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-50" title={zh ? '导出完整 VLAN 信息' : 'Export complete VLAN inventory'}>
                    {vlanExporting ? <RefreshCw size={13} className="animate-spin" /> : <Download size={13} />}
                    {vlanExporting ? '导出中' : '导出 VLAN'}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 border-b border-black/5 bg-slate-50/45 p-4 md:grid-cols-5">
                <div className="rounded-2xl border border-cyan-100 bg-cyan-50/70 px-4 py-3"><div className="text-[11px] font-medium text-cyan-700">VLAN 总数</div><div className="mt-1 text-2xl font-bold text-cyan-900">{vlanSummary.total}</div></div>
                <div className="rounded-2xl border border-emerald-100 bg-emerald-50/70 px-4 py-3"><div className="text-[11px] font-medium text-emerald-700">已发现网关</div><div className="mt-1 text-2xl font-bold text-emerald-900">{vlanSummary.gateways}</div></div>
                <div className="rounded-2xl border border-blue-100 bg-blue-50/70 px-4 py-3"><div className="text-[11px] font-medium text-blue-700">ARP 终端</div><div className="mt-1 text-2xl font-bold text-blue-900">{vlanSummary.arp}</div></div>
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3"><div className="text-[11px] font-medium text-slate-500">MAC 记录</div><div className="mt-1 text-2xl font-bold text-slate-800">{vlanSummary.mac}</div></div>
                <div className={`rounded-2xl border px-4 py-3 ${vlanSummary.unbound ? 'border-amber-200 bg-amber-50/80' : 'border-violet-100 bg-violet-50/70'}`}><div className={`text-[11px] font-medium ${vlanSummary.unbound ? 'text-amber-700' : 'text-violet-700'}`}>待补业务</div><div className={`mt-1 text-2xl font-bold ${vlanSummary.unbound ? 'text-amber-900' : 'text-violet-900'}`}>{vlanSummary.unbound}</div></div>
              </div>

              <div className="overflow-x-auto">
                     <DataTable className="min-w-[1080px] text-left">
                  <thead>
                    <tr className="border-b border-black/5 bg-slate-50 text-[11px] font-bold tracking-wide text-slate-400">
                        <th className="px-5 py-3">VLAN / 设备</th><th className="px-5 py-3">网络</th><th className="px-5 py-3">网关</th><th className="px-5 py-3">接入端口</th><th className="px-5 py-3">终端定位</th><th className="px-5 py-3">业务</th><th className="px-5 py-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                      {loading && vlanFilteredRows.length === 0 && <tr><td colSpan={7} className="py-16 text-center text-sm text-slate-400"><RefreshCw size={18} className="mr-2 inline animate-spin text-cyan-600" />正在加载数据...</td></tr>}
                      {!loading && vlanFilteredRows.length === 0 && <tr><td colSpan={7} className="py-16 text-center text-sm text-slate-400">没有匹配的 VLAN 记录</td></tr>}
                    {paginatedVlanRows.map((row, index) => {
                      const rowKey = String(`${row.device_id || row.device_hostname || row.site_id || row.site_name || 'device'}-${row.vlan_id}-${idOf(row) || index}`);
                      const expanded = Boolean(expandedVlans[rowKey]);
                      const prefixes = splitVlanValues(row.prefixes, /[,;\n]+/);
                      const ports = splitVlanValues(row.port_details);
                      const svi = splitVlanValues(row.svi_interfaces, /[,;\n]+/);
                      const businesses = splitVlanValues(row.business_systems, /[,;\n]+/);
                      const endpointDetails = Array.isArray(row.endpoint_details) ? row.endpoint_details : [];
                      const allArpEndpoints = endpointDetails.filter((item: any) => String(item?.source || '').toLowerCase() === 'arp' && item?.ip_address);
                      const gatewayIp = String(row.gateway || '').trim();
                      const gatewayMacs = new Set(allArpEndpoints.filter((item: any) => String(item.ip_address) === gatewayIp).map((item: any) => String(item.mac_address || '')));
                      const arpEndpoints = allArpEndpoints.filter((item: any) => String(item.ip_address) !== gatewayIp);
                      const clientEndpoints = arpEndpoints;
                      const macEndpoints = endpointDetails.filter((item: any) => item?.mac_address && !gatewayMacs.has(String(item.mac_address)));
                      const terminalRecords = clientEndpoints.length ? clientEndpoints : macEndpoints;
                      const accessInterfaces = Array.from(new Set([
                        ...ports.map(value => value.match(/^[^:]+:([^ ]+)/)?.[1] || '').filter(Boolean),
                        ...macEndpoints.map((item: any) => String(item.interface_name || '')).filter(value => value && !/^vlan/i.test(value)),
                      ]));
                      const businessLevel = String(row.highest_business_level || '').trim();
                      const businessOwner = String(row.business_owners || row.owner || '').trim();
                      const businessDepartment = String(row.business_departments || row.department || '').trim();
                      const displayedAccessInterfaces = accessInterfaces.slice(0, 3);
                      const hiddenAccessInterfaceCount = Math.max(0, accessInterfaces.length - displayedAccessInterfaces.length);
                      const displayedPortDetails = ports.slice(0, 50);
                      const hiddenPortDetailCount = Math.max(0, ports.length - displayedPortDetails.length);
                      return (
                        <React.Fragment key={rowKey}>
                          <tr className="group align-top transition-colors hover:bg-cyan-50/30">
                             <td className="px-5 py-4"><div className="flex items-start gap-2"><button type="button" onClick={() => setExpandedVlans(previous => ({ ...previous, [rowKey]: !previous[rowKey] }))} className="mt-1 shrink-0 rounded p-0.5 text-cyan-600 hover:bg-cyan-50" title={expanded ? '收起明细' : '展开明细'}>{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button><div><div className="font-mono text-lg font-bold text-[#164e63]">VLAN {row.vlan_id}</div><div className="mt-1 text-sm font-semibold text-slate-700">{row.device_hostname || '未关联设备'}</div>{row.device_ip && <div className="mt-0.5 font-mono text-[11px] text-slate-500">{row.device_ip}</div>}{row.description && <div className="mt-1 max-w-[190px] truncate text-sm font-medium text-slate-600" title={String(row.description)}>{row.description}</div>}{row.vrf_name && <div className="mt-1 text-[11px] text-slate-400">VRF：{row.vrf_name}</div>}</div></div></td>
                             <td className="px-5 py-4"><div className="font-mono text-sm font-semibold text-slate-700">{prefixes[0] || '暂无网段'}</div>{prefixes.length > 1 && <div className="mt-1 text-[11px] text-cyan-700">+{prefixes.length - 1} 个网段</div>}<div className="mt-2 text-xs text-slate-500">{row.gateway ? `网关 ${row.gateway}` : '暂无网关'}</div></td>
                             <td className="px-5 py-4"><div className="text-sm font-semibold text-slate-700">{row.gateway_device || '未发现网关'}</div>{svi.length ? <div className="mt-1 text-xs text-slate-500">{svi[0]}{svi.length > 1 ? ` +${svi.length - 1}` : ''}</div> : <div className="mt-1 text-xs text-slate-300">暂无三层接口</div>}</td>
                             <td className="px-5 py-4"><div className="text-sm font-semibold text-slate-700">{displayedAccessInterfaces.length ? displayedAccessInterfaces.join('、') : '未发现端口'}{hiddenAccessInterfaceCount > 0 && <span className="ml-1 text-xs font-medium text-cyan-700">+{hiddenAccessInterfaceCount}</span>}</div><div className="mt-1 text-xs text-slate-500">{Number(row.port_count || 0)} 个端口 · {Number(row.device_count || 0)} 台设备</div>{Number(row.undocumented_port_count || 0) > 0 && <div className="mt-1 text-[11px] font-medium text-amber-600">{Number(row.undocumented_port_count)} 个缺少描述</div>}</td>
                              <td className="px-5 py-4">{terminalRecords.length ? <><div className="text-sm font-semibold text-cyan-700">终端 {terminalRecords.length}</div><div className="mt-1 space-y-1.5">{terminalRecords.slice(0, 2).map((item: any, endpointIndex: number) => <div key={`${item.ip_address || item.mac_address}-${endpointIndex}`}><div className="font-mono text-xs font-semibold text-slate-800">{item.ip_address || '未发现 IP'}</div>{item.mac_address && <div className="font-mono text-[11px] text-slate-500">{formatMacAddress(item.mac_address)}</div>}</div>)}{terminalRecords.length > 2 && <div className="text-[11px] text-cyan-700">+{terminalRecords.length - 2} 个终端</div>}</div></> : <div className="text-sm text-slate-400">暂无终端</div>}</td>
                            <td className="px-5 py-4"><div className="flex flex-wrap gap-1.5 text-xs"><span className={`rounded-full border px-2 py-0.5 font-semibold ${businesses.length ? 'border-emerald-100 bg-emerald-50 text-emerald-700' : 'border-amber-100 bg-amber-50 text-amber-700'}`}>{businesses.length ? `已关联 ${businesses.length} 个业务` : '待补充业务'}</span></div>{businesses.slice(0, 2).map(value => <div key={value} className="mt-1 max-w-[180px] truncate text-sm font-medium text-slate-700" title={value}>{value}</div>)}{businesses.length > 2 && <div className="text-xs text-cyan-700">+{businesses.length - 2} 个</div>}{(businessDepartment || businessOwner || businessLevel) && <div className="mt-2 space-y-0.5 text-[11px] text-slate-500">{businessDepartment && <div>部门：{businessDepartment}</div>}{businessOwner && <div>负责人：{businessOwner}</div>}{businessLevel && <div>等级：{businessLevel}</div>}</div>}</td>
                            <td className="px-5 py-4 text-right align-middle"><div className="flex items-center justify-end gap-1.5 opacity-70 transition-opacity group-hover:opacity-100"><button onClick={() => setVlanDetailRow(row)} className="inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-cyan-100 bg-white px-2 text-xs font-semibold text-cyan-700 shadow-sm hover:border-cyan-200 hover:bg-cyan-50" title="查看明细"><Eye size={13} />明细</button>{!isReadOnlyTab && <><button onClick={() => openEdit(row)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent bg-white text-[#164e63] shadow-sm hover:border-black/10 hover:bg-cyan-50 hover:text-cyan-700" title="编辑"><Edit2 size={13} /></button><button onClick={() => openDeleteConfirm(row)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent bg-white text-rose-400 shadow-sm hover:border-rose-100 hover:bg-rose-50 hover:text-rose-600" title="删除"><Trash2 size={13} /></button></>}</div></td>
                          </tr>
                          {expanded && <tr className="bg-slate-50/70"><td colSpan={8} className="px-12 py-5"><div className="space-y-5"><div><div className="mb-2 flex items-center justify-between"><div className="text-xs font-semibold text-slate-600">终端明细（IP / MAC / 设备 / 接口）</div><span className="text-[11px] text-slate-400">ARP 与 MAC 采集结果</span></div>{endpointDetails.length ? <div className="max-h-[360px] overflow-auto rounded-xl border border-slate-200 bg-white"><div className="grid grid-cols-[110px_150px_minmax(120px,1fr)_minmax(120px,1fr)_80px] gap-3 border-b border-slate-100 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-500"><span>来源</span><span>IP 地址</span><span>MAC 地址</span><span>设备 / 接口</span><span>更新时间</span></div>{endpointDetails.map((item: any, endpointIndex: number) => <div key={`${item.source}-${item.ip_address || item.mac_address || endpointIndex}`} className="grid grid-cols-[110px_150px_minmax(120px,1fr)_minmax(120px,1fr)_80px] gap-3 border-b border-slate-100 px-3 py-2 text-xs last:border-b-0"><span className={`w-fit rounded-full border px-2 py-0.5 ${String(item.source).toLowerCase() === 'arp' ? 'border-blue-100 bg-blue-50 text-blue-700' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>{String(item.source).toLowerCase() === 'arp' ? 'ARP' : 'MAC'}</span><span className="font-mono text-slate-700">{item.ip_address || '—'}</span><span className="font-mono text-slate-700">{formatMacAddress(item.mac_address) || '—'}</span><span className="text-slate-600">{item.device_hostname || '—'}{item.interface_name ? ` / ${item.interface_name}` : ''}</span><span className="text-[11px] text-slate-400">{item.last_updated ? new Date(item.last_updated).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false }) : '—'}</span></div>)}</div> : <div className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-4 text-xs text-slate-400">暂无 ARP/MAC 明细</div>}</div><div className="grid gap-4 md:grid-cols-2"><div><div className="mb-2 text-xs font-semibold text-slate-500">端口描述（最多展示 50 条）</div><div className="max-h-[300px] space-y-1.5 overflow-auto text-xs text-slate-700">{displayedPortDetails.length ? displayedPortDetails.map(value => <div key={value} className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono">{value}</div>) : <div className="text-slate-400">暂无端口描述</div>}{hiddenPortDetailCount > 0 && <div className="rounded-lg border border-dashed border-cyan-200 bg-cyan-50 px-3 py-2 text-cyan-700">还有 {hiddenPortDetailCount} 条端口明细未展开，建议使用“导出 VLAN”查看完整清单。</div>}</div></div><div className="space-y-3"><div><div className="text-xs font-semibold text-slate-500">三层接口</div><div className="mt-1 text-xs text-slate-700">{svi.length ? svi.join('、') : '未发现三层接口'}</div></div><div><div className="text-xs font-semibold text-slate-500">数据统计</div><div className="mt-1 text-xs text-slate-700">设备 {Number(row.device_count || 0)} 台 · 端口 {Number(row.port_count || 0)} 个 · MAC {Number(row.mac_count || 0)} 条 · ARP {Number(row.arp_count || 0)} 条</div></div></div></div></div></td></tr>}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </DataTable>
              </div>
              <Pagination currentPage={page} totalItems={vlanListMeta.total} onPageChange={setPage} itemsPerPage={pageSize} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={zh ? 'zh' : 'en'} />
            </section>
          </div>
        ) : (
        <div className="rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden">
          <div className="overflow-x-auto">
            <DataTable className="text-left">
              <thead>
                <tr className="border-b border-black/5 bg-slate-50 text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                  {tableColumns.map(c => (
                    <th key={c.key} className="px-6 py-4">
                      {zh ? c.label : c.labelEn}
                    </th>
                  ))}
                  {!isReadOnlyTab && (
                    <th className="px-6 py-4 text-right" style={{ width: 120 }}>
                      {zh ? '操作' : 'Actions'}
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredRows.length === 0 && !loading && (
                  <tr>
                    <td colSpan={tableColumns.length + (isReadOnlyTab ? 0 : 1)} className="text-center py-16 text-black/40">
                      {zh ? '无匹配的数据记录' : 'No matching records found'}
                    </td>
                  </tr>
                )}
                {loading && filteredRows.length === 0 && (
                  <tr>
                    <td colSpan={tableColumns.length + (isReadOnlyTab ? 0 : 1)} className="text-center py-16 text-black/40">
                      <RefreshCw size={18} className="animate-spin inline mr-2 text-cyan-600" />
                      {zh ? '正在加载数据...' : 'Loading data...'}
                    </td>
                  </tr>
                )}
                {tab === 'interfaces'
                  ? interfaceGroups.flatMap(group => {
                    const expanded = Boolean(expandedInterfaceDevices[group.key]);
                    return [
                      <tr
                        key={`device-${group.key}`}
                        onClick={() => setExpandedInterfaceDevices(previous => ({ ...previous, [group.key]: !expanded }))}
                        className="cursor-pointer bg-cyan-50/45 hover:bg-cyan-50 transition-colors"
                      >
                        <td colSpan={tableColumns.length} className="px-6 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex min-w-0 items-center gap-3">
                              {expanded ? <ChevronUp size={15} className="shrink-0 text-cyan-600" /> : <ChevronDown size={15} className="shrink-0 text-cyan-600" />}
                              <div className="min-w-0">
                                <div className="truncate text-sm font-semibold text-[#164e63]">{group.hostname}</div>
                                {group.deviceIp && <div className="font-mono text-[11px] text-slate-400">{group.deviceIp}</div>}
                              </div>
                            </div>
                            <span className="shrink-0 rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-cyan-700 shadow-sm">
                              {group.rows.length} {zh ? '个三层接口' : 'L3 interfaces'}
                            </span>
                          </div>
                        </td>
                      </tr>,
                      ...(expanded ? group.rows.map((row, index) => renderDataRow(row, `${group.key}-${index}`)) : []),
                    ];
                  })
                  : paginatedRows.map((row, i) => renderDataRow(row, i))}
              </tbody>
            </DataTable>
          </div>

          <Pagination
            currentPage={tab === 'interfaces' ? interfacePage : page}
            totalItems={tab === 'interfaces' ? interfaceListMeta.total : (tab === 'sites' || tab === 'vrfs' ? genericListMeta.total : filteredRows.length)}
            onPageChange={tab === 'interfaces' ? setInterfacePage : setPage}
            itemsPerPage={tab === 'interfaces' ? interfacePageSize : pageSize}
            onItemsPerPageChange={(size) => {
              if (tab === 'interfaces') {
                setInterfacePageSize(size);
                setInterfacePage(1);
              } else {
                setPageSize(size);
                setPage(1);
              }
            }}
            language={zh ? 'zh' : 'en'}
          />
        </div>
        )}
      </div>

      {credentialImportOpen && (
        <div className="fixed inset-0 z-[115] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => !credentialImporting && setCredentialImportOpen(false)} />
          <div className="relative flex max-h-[88vh] w-full max-w-5xl flex-col rounded-3xl border border-black/8 bg-white p-6 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between border-b border-black/5 pb-4">
              <div>
                <h2 className="text-lg font-semibold text-[#164e63]">{zh ? '上传凭据' : 'Upload Credentials'}</h2>
                <p className="mt-1 text-xs text-slate-500">{credentialImportFileName || (zh ? '请选择 Excel 或 CSV 文件' : 'Choose an Excel or CSV file')} · {zh ? 'SSH 与 SNMP 按不同字段分别导入' : 'SSH and SNMP use separate field sets'}</p>
              </div>
              <button disabled={credentialImporting} onClick={() => setCredentialImportOpen(false)} className="rounded-xl border border-black/10 p-1.5 text-black/55 hover:bg-black/[0.03] disabled:opacity-40"><X size={16} /></button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto py-4">
              <div className={`mb-4 rounded-2xl border px-4 py-3 text-sm ${credentialImportErrors.length ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                {credentialImportErrors.length
                  ? (zh ? `发现 ${credentialImportErrors.length} 个校验问题，请修正文件后重新上传` : `${credentialImportErrors.length} validation issue(s) found. Fix the file and upload again.`)
                  : (zh ? `已识别 ${credentialImportRows.length} 条凭据，确认后将写入凭据中心` : `${credentialImportRows.length} credential(s) detected. Confirm to import them.`)}
              </div>
              <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
                {zh ? '安全提示：密码、Enable 密码和 SNMP Community 只会提交到后端加密保存，预览中不会显示明文；导出文件中的这些字段始终为空。' : 'Security: passwords and SNMP Community are sent to the backend for encryption and are never shown in plaintext in the preview or exports.'}
              </div>
              {credentialImportErrors.length > 0 && (
                <div className="mb-4 max-h-36 overflow-y-auto rounded-2xl border border-rose-100 bg-white p-3 text-xs text-rose-700">
                  {credentialImportErrors.map((item, index) => <div key={`${item.sheet}-${item.row}-${index}`} className="py-1">[{item.sheet}] {zh ? `第 ${item.row} 行` : `Row ${item.row}`}: {item.message}</div>)}
                </div>
              )}
              <div className="space-y-4">
                {CREDENTIAL_SHEET_DEFS.map(sheet => {
                  const sheetRows = credentialImportRows.filter(item => item.sheet === sheet.key);
                  return (
                    <div key={sheet.key} className="overflow-hidden rounded-2xl border border-slate-200">
                      <div className="flex items-center justify-between bg-slate-50 px-4 py-2.5">
                        <span className="text-sm font-semibold text-[#164e63]">{sheet.name}</span>
                        <span className="text-xs text-slate-400">{sheetRows.length} {zh ? '条' : 'row(s)'}</span>
                      </div>
                      {sheetRows.length > 0 ? (
                        <div className="overflow-x-auto">
                          <table className="nx-data-table nx-data-table--compact text-left text-xs">
                            <thead className="bg-white text-slate-500">
                              <tr>{sheet.columns.map(column => <th key={column.key} className="whitespace-nowrap px-3 py-2 font-semibold">{column.label}</th>)}</tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {sheetRows.slice(0, 10).map((item, index) => (
                                <tr key={`${item.row}-${index}`}>
                                  {sheet.columns.map(column => {
                                    const value = String(item.values[column.key] || '');
                                    const displayValue = CREDENTIAL_SECRET_FIELDS.has(column.key)
                                      ? (value ? (zh ? '已填写' : 'Provided') : '-')
                                      : (value || '-');
                                    return <td key={column.key} className="max-w-52 truncate whitespace-nowrap px-3 py-2 text-slate-600">{displayValue}</td>;
                                  })}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {sheetRows.length > 10 && <div className="border-t border-slate-100 px-3 py-2 text-xs text-slate-400">{zh ? `仅预览前 10 条，共 ${sheetRows.length} 条` : `Showing 10 of ${sheetRows.length} row(s)`}</div>}
                        </div>
                      ) : (
                        <div className="px-4 py-4 text-xs text-slate-400">{zh ? '该 Sheet 没有可导入数据' : 'No importable data in this sheet'}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-black/5 pt-4">
              <button disabled={credentialTemplateDownloading} onClick={downloadCredentialImportTemplate} className="inline-flex items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-semibold text-cyan-700 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"><FileSpreadsheet size={14} className={credentialTemplateDownloading ? 'animate-pulse' : ''} />{zh ? '下载双 Sheet 模板' : 'Download two-sheet template'}</button>
              <div className="flex items-center gap-2">
                <button disabled={credentialImporting} onClick={() => setCredentialImportOpen(false)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40">{zh ? '取消' : 'Cancel'}</button>
                <button disabled={credentialImporting || !credentialImportRows.length || credentialImportErrors.length > 0} onClick={() => void importCredentialRows()} className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-40">
                  {credentialImporting && <RefreshCw size={14} className="animate-spin" />}
                  {credentialImporting ? (zh ? '导入中...' : 'Importing...') : (zh ? '确认导入' : 'Confirm import')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {siteImportOpen && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => !siteImporting && setSiteImportOpen(false)} />
          <div className="relative flex max-h-[88vh] w-full max-w-4xl flex-col rounded-3xl border border-black/8 bg-white p-6 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between border-b border-black/5 pb-4">
              <div>
                <h2 className="text-lg font-semibold text-[#164e63]">导入站点</h2>
                <p className="mt-1 text-xs text-slate-500">{siteImportFileName || '请选择 Excel 或 CSV 文件'} · 支持中文、英文和字段代码表头</p>
              </div>
              <button disabled={siteImporting} onClick={() => setSiteImportOpen(false)} className="rounded-xl border border-black/10 p-1.5 text-black/55 hover:bg-black/[0.03] disabled:opacity-40"><X size={16} /></button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto py-4">
              <div className={`mb-4 rounded-2xl border px-4 py-3 text-sm ${siteImportErrors.length ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                {siteImportErrors.length
                  ? `发现 ${siteImportErrors.length} 个校验问题，请修正文件后重新导入`
                  : `已识别 ${siteImportRows.length} 行站点数据，确认后将创建站点并自动生成站点编码`}
              </div>
              {siteImportErrors.length > 0 && (
                <div className="mb-4 max-h-36 overflow-y-auto rounded-2xl border border-rose-100 bg-white p-3 text-xs text-rose-700">
                  {siteImportErrors.map((item, index) => <div key={`${item.row}-${index}`} className="py-1">第 {item.row} 行：{item.message}</div>)}
                </div>
              )}
              {siteImportRows.length > 0 && (
                <div className="overflow-x-auto rounded-2xl border border-slate-200">
                  <table className="nx-data-table nx-data-table--compact text-left text-xs">
                    <thead className="bg-slate-50 text-slate-500">
                      <tr>{SITE_IMPORT_COLUMNS.map(column => <th key={column.key} className="whitespace-nowrap px-3 py-2 font-semibold">{column.header}</th>)}</tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {siteImportRows.slice(0, 10).map((row, index) => (
                        <tr key={index}>
                          {SITE_IMPORT_COLUMNS.map(column => <td key={column.key} className="max-w-48 truncate whitespace-nowrap px-3 py-2 text-slate-600">{row[column.key] || '-'}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {siteImportRows.length > 10 && <div className="border-t border-slate-100 px-3 py-2 text-xs text-slate-400">仅预览前 10 行，共 {siteImportRows.length} 行</div>}
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-black/5 pt-4">
              <button onClick={downloadSiteImportTemplate} className="inline-flex items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-semibold text-cyan-700 hover:bg-cyan-100"><FileSpreadsheet size={14} />下载模板</button>
              <div className="flex items-center gap-2">
                <button disabled={siteImporting} onClick={() => setSiteImportOpen(false)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40">取消</button>
                <button disabled={siteImporting || !siteImportRows.length || siteImportErrors.length > 0} onClick={() => void importSiteRows()} className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-40">
                  {siteImporting && <RefreshCw size={14} className="animate-spin" />}
                  {siteImporting ? '导入中...' : '确认导入'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Create/Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setModalOpen(false)} />
          <div className="relative flex max-h-[88vh] w-full max-w-md flex-col rounded-3xl border border-black/8 bg-white p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between mb-4 border-b border-black/5 pb-3">
              <h2 className="text-lg font-semibold text-[#164e63]">
                {editing ? (zh ? '编辑记录' : 'Edit Record') : (zh ? '新建记录' : 'New Record')} · {zh ? tabs.find(t => t.key === tab)?.label : tabs.find(t => t.key === tab)?.labelEn}
              </h2>
              <button onClick={() => setModalOpen(false)} className="rounded-xl border border-black/10 p-1.5 text-black/55 hover:bg-black/[0.03] transition-colors"><X size={16} /></button>
            </div>
            <div className={`${tab === 'credentials' ? 'grid grid-cols-2 items-start gap-x-3 gap-y-4' : 'space-y-4'} min-h-0 flex-1 overflow-y-auto pr-1`}>
              {fieldDefs[tab].filter(fd => !fd.hideInForm && (!fd.hideInCreate || Boolean(editing))
                && !(tab === 'credentials' && form.credential_type === 'snmpv2'
                  && ['username', 'account_role', 'old_password', 'old_enable_password', 'password', 'enable_password'].includes(fd.key))
                && !(tab === 'credentials' && !String(form.credential_type || '').startsWith('snmp')
                  && ['snmp_community', 'snmp_server'].includes(fd.key))).map(fd => {
                const opts = fd.key === 'site_id'
                  ? siteOptions
                  : fd.key === 'vrf_id'
                    ? vrfOptions
                    : fd.key === 'vlan_id' && tab === 'vlan-business'
                      ? vlanBusinessOptions
                      : fd.options;
                const isGeoField = tab === 'sites' && ['country', 'state_province', 'city', 'district'].includes(fd.key);
                const geoOpts = isGeoField ? geoSelectOptions[fd.key as 'country' | 'state_province' | 'city' | 'district'] : [];
                const geoFieldDisabled = geoLoading || Boolean(geoError)
                  || (fd.key === 'state_province' && !selectedGeoCountry)
                  || (fd.key === 'city' && (!selectedGeoCountry || (geoStates.length > 0 && !selectedGeoState)))
                  || (fd.key === 'district' && (!selectedGeoCountry || !selectedGeoState || !selectedGeoCity));
                const isSiteContact = tab === 'sites' && ['contact_name', 'contact_phone', 'contact_email'].includes(fd.key);
                const contactKey = isSiteContact ? fd.key as SiteContactField : null;
                const fieldError = contactKey
                  ? fieldErrors[contactKey]
                  : tab === 'credentials'
                    ? fieldErrors[fd.key]
                    : '';
                const phoneRule = phoneRuleForCountry(selectedGeoCountry?.isoCode);
                const phoneLocal = fd.key === 'contact_phone' ? phoneLocalValue(form.contact_phone, phoneRule) : '';
                const updateContactError = (nextValue: string) => {
                  if (!contactKey) return;
                  const originalValue = editing ? String(editing[contactKey] ?? '').trim() : '';
                  if (editing && originalValue === nextValue.trim()) {
                    setFieldErrors(previous => ({ ...previous, [contactKey]: '' }));
                    return;
                  }
                  const required = !editing || originalValue !== nextValue.trim();
                  setFieldErrors(previous => ({
                    ...previous,
                    [contactKey]: siteContactError(contactKey, nextValue, required, zh, phoneRule),
                  }));
                };
                const isCredentialSecret = tab === 'credentials'
                  && ['old_password', 'old_enable_password', 'password', 'enable_password', 'snmp_community'].includes(fd.key);
                return (
                  <div key={fd.key} className={tab === 'credentials' && !isCredentialSecret ? 'col-span-2' : ''}>
                    <label className="block text-xs font-semibold mb-1 text-black/50">
                      {zh ? fd.label : fd.labelEn}{fd.required && <span className="text-rose-500"> *</span>}
                      {fd.secretFlag && editing && (
                        <span className="ml-1 text-[10px] text-black/30 font-normal">
                          {zh ? '（留空保持不变）' : '(leave blank to keep)'}
                        </span>
                      )}
                    </label>
                    {isGeoField ? (
                      <SearchableGeoSelect
                        value={form[fd.key] ?? ''}
                        options={geoOpts}
                        allowCustom={fd.key === 'city' || fd.key === 'district'}
                        disabled={geoFieldDisabled}
                        placeholder={
                          geoLoading ? '正在加载国家和省州数据…'
                            : geoCityLoading && fd.key === 'city' ? '正在加载城市数据…'
                              : fd.key === 'state_province' && !selectedGeoCountry ? '请先选择国家'
                                : fd.key === 'city' && geoStates.length > 0 && !selectedGeoState ? '请先选择省份 / 州'
                                  : fd.key === 'district' && !selectedGeoCity ? '请先选择城市'
                                    : geoError ? '地理数据不可用' : `请选择${zh ? fd.label : fd.labelEn}`
                        }
                        emptyText={fd.key === 'city' && geoCityError ? geoCityError : fd.key === 'city' && selectedGeoState && !geoCities.length ? '该省份 / 州暂无城市数据，可直接手动填写' : fd.key === 'district' && !geoDistricts.length ? '该城市暂无区县目录，可直接手动填写' : '没有匹配的选项'}
                        onChange={next => {
                          if (fd.key === 'country') {
                            const nextCountry = geoCatalog?.countries.find(country => matchesGeoValue(next, country.name, country.isoCode, countryDisplayName(country)));
                            const nextPhoneRule = phoneRuleForCountry(nextCountry?.isoCode);
                            const previousPhoneLocal = phoneLocalValue(form.contact_phone, phoneRuleForCountry(selectedGeoCountry?.isoCode));
                            setForm({ ...form, country: next, state_province: '', city: '', district: '', contact_phone: previousPhoneLocal ? composePhoneValue(previousPhoneLocal, nextPhoneRule) : '' });
                            setFieldErrors(previous => ({ ...previous, contact_phone: '' }));
                            setGeoError('');
                          } else if (fd.key === 'state_province') {
                            setForm({ ...form, state_province: next, city: '', district: '' });
                          } else if (fd.key === 'city') {
                            setForm({ ...form, city: next, district: '' });
                          } else {
                            setForm({ ...form, [fd.key]: next });
                          }
                        }}
                      />
                    ) : fd.type === 'select' && opts ? (
                      <select
                        value={form[fd.key] ?? ''}
                        onChange={e => {
                          const nextValue = e.target.value;
                          if (tab === 'vlan-business' && fd.key === 'site_id') {
                            const currentVlan = String(form.vlan_id || '');
                            const stillValid = vlanCatalog.some(vlan => String(vlan.site_id || '') === nextValue && String(vlan.vlan_id) === currentVlan);
                            setForm({ ...form, site_id: nextValue, vlan_id: stillValid ? currentVlan : '' });
                          } else {
                            setForm({ ...form, [fd.key]: nextValue });
                          }
                        }}
                        className="w-full px-3 py-2 rounded-xl text-sm border border-black/10 bg-white text-[#164e63] outline-none focus:border-[#06b6d4]/45 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                      >
                        {opts.map(o => <option key={o.value} value={o.value}>{zh ? o.label : (o.labelEn || o.label)}</option>)}
                      </select>
                    ) : fd.key === 'contact_phone' && tab === 'sites' ? (
                      <div className={`flex items-center rounded-xl border bg-white transition-all ${fieldError ? 'border-rose-400' : 'border-black/10 focus-within:border-[#06b6d4]/45'}`}>
                        <span className="px-3 text-sm text-[#164e63] border-r border-black/10 select-none">+{phoneRule.callingCode}</span>
                        <input
                          type="tel"
                          value={phoneLocal}
                          placeholder={fd.placeholder}
                          maxLength={phoneRule.maxDigits}
                          inputMode="tel"
                          required={fd.required && !editing}
                          autoComplete="tel-national"
                          onChange={e => {
                            const nextValue = composePhoneValue(e.target.value, phoneRule);
                            setForm({ ...form, contact_phone: nextValue });
                            updateContactError(nextValue);
                          }}
                          onBlur={() => updateContactError(String(form.contact_phone ?? ''))}
                          className="w-full px-3 py-2 rounded-r-xl text-sm bg-transparent text-[#164e63] outline-none"
                        />
                      </div>
                    ) : fd.type === 'password' ? (
                      <div className="relative">
                        <input
                          type={visiblePasswordFields[fd.key] ? 'text' : 'password'}
                          value={form[fd.key] ?? ''}
                          placeholder={fd.placeholder}
                          maxLength={fd.maxLength}
                          inputMode={fd.inputMode}
                          required={fd.required && !editing}
                          autoComplete="new-password"
                          onChange={e => setForm({ ...form, [fd.key]: e.target.value })}
                          className={`w-full px-3 py-2 pr-10 rounded-xl text-sm border bg-white text-[#164e63] outline-none transition-all ${fieldError ? 'border-rose-400 focus:border-rose-400 focus:ring-2 focus:ring-rose-500/10' : 'border-black/10 focus:border-[#06b6d4]/45 focus:ring-2 focus:ring-[#06b6d4]/10'}`}
                        />
                        <button
                          type="button"
                          onClick={() => setVisiblePasswordFields(prev => ({ ...prev, [fd.key]: !prev[fd.key] }))}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60 focus:outline-none"
                          title={visiblePasswordFields[fd.key] ? (zh ? '隐藏密码' : 'Hide Password') : (zh ? '显示密码' : 'Show Password')}
                        >
                          {visiblePasswordFields[fd.key] ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    ) : (
                      <input
                        type={fd.type === 'number' ? 'number' : fd.type === 'email' ? 'email' : fd.type === 'tel' ? 'tel' : 'text'}
                        value={form[fd.key] ?? ''}
                        placeholder={fd.placeholder}
                        maxLength={fd.maxLength}
                        inputMode={fd.inputMode}
                        required={fd.required && !editing}
                        autoComplete="off"
                        onChange={e => {
                          setForm({ ...form, [fd.key]: e.target.value });
                          updateContactError(e.target.value);
                        }}
                        onBlur={() => updateContactError(String(form[fd.key] ?? ''))}
                        className={`w-full px-3 py-2 rounded-xl text-sm border bg-white text-[#164e63] outline-none focus:ring-2 transition-all ${fieldError ? 'border-rose-400 focus:border-rose-400 focus:ring-rose-500/10' : 'border-black/10 focus:border-[#06b6d4]/45 focus:ring-[#06b6d4]/10'}`}
                      />
                    )}
                    {fieldError ? (
                      <div className="mt-1 text-[11px] leading-4 text-rose-500 flex items-start gap-1" role="alert">
                        <ShieldAlert size={12} className="mt-0.5 flex-shrink-0" />
                        <span>{fieldError}</span>
                      </div>
                    ) : fd.hint && (
                      <div className="mt-1 text-[11px] leading-4 text-black/45">
                        {zh ? fd.key === 'contact_phone' ? `国家区号 +${phoneRule.callingCode}，后接 ${phoneRule.minDigits === phoneRule.maxDigits ? phoneRule.minDigits : `${phoneRule.minDigits}-${phoneRule.maxDigits}`} 位号码` : fd.hint : fd.labelEn === 'Contact' ? '2-50 Chinese or English letters' : fd.labelEn === 'Contact Phone' ? `Country code +${phoneRule.callingCode}, followed by ${phoneRule.minDigits === phoneRule.maxDigits ? phoneRule.minDigits : `${phoneRule.minDigits}-${phoneRule.maxDigits}`} digits` : 'Enter a valid email address'}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {tab === 'sites' && geoError && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{geoError}</div>
            )}
            
            {error && (
              <div className="mt-4 max-h-24 shrink-0 overflow-y-auto rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-600 flex items-start gap-1.5" role="alert">
                <ShieldAlert size={14} className="flex-shrink-0" />
                <span><strong className="font-semibold">{zh ? '保存失败：' : 'Save failed: '}</strong>{error}</span>
              </div>
            )}
            
            <div className="mt-6 flex shrink-0 justify-end gap-2 border-t border-black/5 pt-3">
              <button
                onClick={() => setModalOpen(false)}
                className="h-10 px-4 rounded-xl border border-black/10 bg-white text-sm font-semibold text-black/60 hover:bg-black/[0.02] transition-colors"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                onClick={submit}
                className="inline-flex h-10 px-5 items-center justify-center gap-1.5 rounded-xl bg-[#06b6d4] text-sm font-semibold text-white shadow-md hover:bg-[#0891b2] transition-all"
              >
                <Check size={14} />
                {zh ? '保存' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {vlanDetailRow && (
        <div className="fixed inset-0 z-[105] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setVlanDetailRow(null)} />
          <div className="relative flex max-h-[88vh] w-full max-w-7xl flex-col overflow-hidden rounded-3xl border border-black/8 bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
              <div>
                <h3 className="text-lg font-semibold text-[#164e63]">VLAN {vlanDetailRow.vlan_id} 明细表</h3>
                <p className="mt-1 text-xs text-slate-500">{vlanDetailRow.device_hostname || '未关联设备'} · {vlanDetailRow.device_ip || '—'} · {vlanDetailRow.description || '暂无描述'} · 网段 {vlanDetailRow.prefixes || '—'} · 网关 {vlanDetailRow.gateway || '—'}</p>
              </div>
              <button type="button" onClick={() => setVlanDetailRow(null)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="关闭"><X size={18} /></button>
            </div>
            <div className="overflow-auto p-5">
              {(() => {
                const endpointRows = Array.isArray(vlanDetailRow.endpoint_details) ? vlanDetailRow.endpoint_details : [];
                const portRows = Array.isArray(vlanDetailRow.port_detail_rows) && vlanDetailRow.port_detail_rows.length
                  ? vlanDetailRow.port_detail_rows.map((item: any) => ({
                    source: '接口',
                    ip_address: '',
                    mac_address: '',
                    device_hostname: item.device_hostname || '',
                    device_ip: item.device_ip || '',
                    interface_name: item.interface_name || '',
                    description: item.description || '',
                    last_updated: vlanDetailRow.last_discovered_at || '',
                  }))
                  : splitVlanValues(vlanDetailRow.port_details).map(value => {
                  const [left, ...descriptionParts] = value.split(' - ');
                  const separatorIndex = left.indexOf(':');
                  return {
                    source: '接口',
                    ip_address: '',
                    mac_address: '',
                    device_hostname: separatorIndex >= 0 ? left.slice(0, separatorIndex) : left,
                    device_ip: '',
                    interface_name: separatorIndex >= 0 ? left.slice(separatorIndex + 1) : '',
                    description: descriptionParts.join(' - '),
                    last_updated: vlanDetailRow.last_discovered_at || '',
                  };
                });
                const detailRows = [...portRows, ...endpointRows];
                return detailRows.length ? (
                  <table className="nx-data-table nx-data-table--compact min-w-[980px] text-left text-xs">
                    <thead className="sticky top-0 bg-slate-50 text-[11px] font-semibold text-slate-500">
                      <tr className="border-b border-slate-200"><th className="px-3 py-3">来源</th><th className="px-3 py-3">设备名称</th><th className="px-3 py-3">设备 IP</th><th className="px-3 py-3">接口</th><th className="px-3 py-3">接口描述</th><th className="px-3 py-3">IP 地址</th><th className="px-3 py-3">MAC 地址</th><th className="px-3 py-3">来源时间</th></tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {detailRows.map((item: any, detailIndex: number) => (
                        <tr key={`${item.source}-${item.device_hostname}-${item.interface_name}-${item.ip_address}-${detailIndex}`} className="hover:bg-cyan-50/30">
                          <td className="px-3 py-3"><span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-600">{String(item.source || '—').toUpperCase()}</span></td>
                          <td className="px-3 py-3 font-semibold text-slate-700">{item.device_hostname || '—'}</td>
                          <td className="px-3 py-3 font-mono text-slate-600">{item.device_ip || '—'}</td>
                          <td className="px-3 py-3 font-mono text-slate-700">{item.interface_name || '—'}</td>
                          <td className="px-3 py-3 text-slate-600">{item.description || '—'}</td>
                          <td className="px-3 py-3 font-mono text-slate-700">{item.ip_address || '—'}</td>
                          <td className="px-3 py-3 font-mono text-slate-700">{formatMacAddress(item.mac_address) || '—'}</td>
                          <td className="px-3 py-3 whitespace-nowrap text-slate-500">{item.last_updated ? new Date(item.last_updated).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false }) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <div className="rounded-xl border border-dashed border-slate-200 px-4 py-12 text-center text-sm text-slate-400">暂无接口或 ARP/MAC 明细</div>;
              })()}
            </div>
          </div>
        </div>
      )}

      {bindingModal && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/45 backdrop-blur-sm"
            onClick={() => { if (!bindingSaving) setBindingModal(null); }}
          />
          <div className="relative w-full max-w-lg rounded-3xl border border-black/8 bg-white p-6 shadow-2xl dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4 border-b border-black/5 pb-4">
              <div>
                <h3 className="text-lg font-semibold text-[#164e63] dark:text-cyan-300">
                  {zh ? '管理设备凭据绑定' : 'Manage device credential binding'}
                </h3>
                <p className="mt-1 text-xs text-black/50 dark:text-white/50">
                  {bindingModal.deviceName} · {bindingModal.bindingRole === 'admin' ? (zh ? '特权账号' : 'Privileged account') : (zh ? '普通账号' : 'Normal account')}
                </p>
              </div>
              <button type="button" disabled={bindingSaving} onClick={() => setBindingModal(null)} className="text-black/35 hover:text-black/65 disabled:opacity-40">
                <X size={18} />
              </button>
            </div>

            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setBindingAction('replace')}
                className={`rounded-2xl border p-3 text-left transition-colors ${bindingAction === 'replace' ? 'border-cyan-400 bg-cyan-50 text-cyan-800' : 'border-slate-200 bg-white text-slate-600 hover:border-cyan-200'}`}
              >
                <div className="text-sm font-semibold">{zh ? '替换为新凭据' : 'Replace credential'}</div>
                <div className="mt-1 text-[11px] leading-4 opacity-70">{zh ? '仅切换绑定关系，原凭据不会删除' : 'Switch binding only; the original credential is kept'}</div>
              </button>
              <button
                type="button"
                onClick={() => setBindingAction('unbind')}
                className={`rounded-2xl border p-3 text-left transition-colors ${bindingAction === 'unbind' ? 'border-amber-400 bg-amber-50 text-amber-800' : 'border-slate-200 bg-white text-slate-600 hover:border-amber-200'}`}
              >
                <div className="text-sm font-semibold">{zh ? '解除绑定' : 'Unbind credential'}</div>
                <div className="mt-1 text-[11px] leading-4 opacity-70">{zh ? '设备改为独立凭据管理，不删除当前凭据' : 'Use independent device credentials; keep the current credential'}</div>
              </button>
            </div>

            {bindingAction === 'replace' && (
              <div className="mt-5">
                <label className="mb-2 block text-xs font-semibold text-slate-600 dark:text-slate-300">
                  {zh ? '选择替换凭据' : 'Replacement credential'}
                </label>
                <select
                  value={replacementCredentialId}
                  onChange={event => setReplacementCredentialId(event.target.value)}
                  className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/10"
                >
                  <option value="">{zh ? '请选择凭据' : 'Select a credential'}</option>
                  {rows
                    .filter(candidate => {
                      const candidateId = String(candidate.id || '');
                      const role = String(candidate.account_role || 'unbound').toLowerCase();
                      if (!candidateId || candidateId === bindingModal.credentialId) return false;
                      return bindingModal.bindingRole === 'admin' ? role !== 'normal' : role !== 'admin';
                    })
                    .map(candidate => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.credential_name || candidate.id} · {candidate.username || '-'} · {getAccountRoleLabel(candidate.account_role || 'unbound')}
                      </option>
                    ))}
                </select>
              </div>
            )}

            <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50/70 p-3 text-xs leading-5 text-amber-900">
              {bindingAction === 'replace'
                ? (zh ? '注意：本操作只修改 Nexora 中的设备—凭据绑定，不会登录设备或修改交换机上的密码。若新凭据的实际密码尚未在设备生效，后续连接可能失败。' : 'This changes only the Nexora device-to-credential binding. It does not log in to the device or change its hardware password.')
                : (zh ? '注意：解除后设备进入独立凭据管理。当前凭据仍保留，设备上的实际密码不会被修改；请在设备/资产密码管理中维护独立密码。' : 'After unbinding, the device uses independent credential management. The current credential is kept and the hardware password is not changed.')}
            </div>

            <div className="mt-6 flex justify-end gap-2 border-t border-black/5 pt-4">
              <button type="button" disabled={bindingSaving} onClick={() => setBindingModal(null)} className="h-10 rounded-xl border border-black/10 bg-white px-4 text-sm font-semibold text-black/60 hover:bg-black/[0.02] disabled:opacity-40">
                {zh ? '取消' : 'Cancel'}
              </button>
              <button type="button" disabled={bindingSaving || (bindingAction === 'replace' && !replacementCredentialId)} onClick={() => { void submitBindingChange(); }} className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-cyan-500 px-5 text-sm font-semibold text-white shadow-md hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-50">
                {bindingSaving ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
                {bindingAction === 'replace' ? (zh ? '确认替换' : 'Confirm replace') : (zh ? '确认解除' : 'Confirm unbind')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirm */}
      {confirmDelete && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setConfirmDelete(null)} />
          <div className="relative w-full max-w-sm rounded-3xl border border-black/8 bg-white p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-50">
                <Trash2 size={20} className="text-red-500" />
              </div>
              <h3 className="text-lg font-semibold text-[#164e63]">
                {zh ? '确认删除' : 'Confirm Delete'}
              </h3>
              <p className="text-sm text-black/50">
                {zh ? '此操作不可撤销，确定要删除该记录吗？' : 'This action cannot be undone. Are you sure you want to delete this record?'}
              </p>
            </div>
            
            {tab === 'sites' && (
              <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50/70 p-3 text-left">
                <div className="text-xs font-semibold text-amber-900">
                  {zh ? '如站点仍被引用，请先选择迁移目标' : 'If this site is referenced, select a replacement site first'}
                </div>
                <select
                  value={siteReplacementId}
                  onChange={event => setSiteReplacementId(event.target.value)}
                  className="mt-2 h-10 w-full rounded-xl border border-amber-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-cyan-500"
                >
                  <option value="">{zh ? '不迁移，直接尝试删除' : 'No replacement; try direct deletion'}</option>
                  {sites.filter(site => site.id !== idOf(confirmDelete)).map(site => (
                    <option key={site.id} value={site.id}>
                      {site.site_code} · {site.site_name}
                    </option>
                  ))}
                </select>
                {siteDeleteError && (
                  <p className="mt-2 text-xs leading-5 text-rose-600">{siteDeleteError}</p>
                )}
              </div>
            )}

            <div className="flex justify-center gap-2 mt-6">
              <button
                onClick={() => setConfirmDelete(null)}
                className="h-10 px-5 rounded-xl border border-black/10 bg-white text-sm font-semibold text-black/60 hover:bg-black/[0.02] transition-colors"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                onClick={doDelete}
                className="inline-flex h-10 px-5 items-center justify-center gap-1.5 rounded-xl bg-red-500 text-sm font-semibold text-white shadow-md hover:bg-red-600 transition-all"
              >
                <Trash2 size={14} />
                {zh ? '删除' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CmdbManagementTab;
