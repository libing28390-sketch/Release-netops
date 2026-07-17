import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Edit2, Trash2, RefreshCw, X, KeyRound, Building2, Network, Layers, Users as UsersIcon, Server, Search, Check, ShieldAlert, Eye, EyeOff } from 'lucide-react';
import PageHero from '../components/PageHero';
import Pagination from '../components/Pagination';

/* ────────────────────────────────────────────────────────────
 * CMDB Management — unified CRUD for the foundational CMDB tables:
 *   credentials · devices · interfaces · sites · vrfs · vlans · tenants
 * Consumes the /api/credentials and /api/cmdb/* endpoints.
 * ──────────────────────────────────────────────────────────── */

interface Props {
  language?: string;
  cmdbPage?: string;
}

type EntityKey = 'credentials' | 'devices' | 'interfaces' | 'sites' | 'vrfs' | 'vlans' | 'tenants';

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

async function apiList<T>(url: string): Promise<T[]> {
  const res = await fetch(url, { headers: authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(formatErrorDetail(json.detail || json.message));
  return (json.data || []) as T[];
}

async function apiSend(url: string, method: 'POST' | 'PUT' | 'DELETE', body?: Record<string, unknown>): Promise<void> {
  const res = await fetch(url, {
    method,
    headers: authHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({ success: res.ok }));
  if (!res.ok || json.success === false) throw new Error(formatErrorDetail(json.detail || json.message));
}

interface FieldDef {
  key: string;
  label: string;
  labelEn: string;
  type?: 'text' | 'number' | 'password' | 'select';
  options?: { value: string; label: string; labelEn?: string }[];
  required?: boolean;
  placeholder?: string;
  /** Hidden from the table list view */
  hideInTable?: boolean;
  /** Hidden from the edit/create form */
  hideInForm?: boolean;
  /** Shown as a masked presence flag in table (e.g. has_password) */
  secretFlag?: string;
}

const SITE_STATUS_OPTS = [
  { value: 'active', label: '在用', labelEn: 'Active' },
  { value: 'planned', label: '规划中', labelEn: 'Planned' },
  { value: 'staging', label: '建设中', labelEn: 'Staging' },
  { value: 'decommissioned', label: '已退役', labelEn: 'Decommissioned' },
  { value: 'offline', label: '离线', labelEn: 'Offline' },
];

const CRED_TYPE_OPTS = [
  { value: 'ssh_password', label: 'ssh_password' },
  { value: 'ssh_key', label: 'ssh_key' },
  { value: 'snmpv2', label: 'snmpv2' },
  { value: 'snmpv3', label: 'snmpv3' },
  { value: 'api_token', label: 'api_token' },
];

const VLAN_STATUS_OPTS = [
  { value: 'active', label: 'active' },
  { value: 'reserved', label: 'reserved' },
  { value: 'deprecated', label: 'deprecated' },
];

interface GeoCountry { name: string; isoCode: string }
interface GeoState { name: string; isoCode: string; countryCode: string }
interface GeoCity { name: string; stateCode: string; countryCode: string }
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
};

function cityDisplayName(city: GeoCity): string {
  if (city.countryCode !== 'CN') return city.name;
  return CHINA_CITY_LABELS[city.name.replace(/[\s-]/g, '')] || city.name;
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
  const filteredOptions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return options;
    return options.filter(option => `${option.label} ${option.value} ${option.searchText || ''}`.toLocaleLowerCase().includes(normalized));
  }, [options, query]);

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

const CmdbManagementTab: React.FC<Props> = ({ language, cmdbPage }) => {
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [visiblePasswordFields, setVisiblePasswordFields] = useState<Record<string, boolean>>({});
  const [form, setForm] = useState<Record<string, any>>({});
  const [confirmDelete, setConfirmDelete] = useState<any | null>(null);
  const [siteReplacementId, setSiteReplacementId] = useState('');
  const [siteDeleteError, setSiteDeleteError] = useState('');
  const [geoCatalog, setGeoCatalog] = useState<GeoCatalog | null>(null);
  const [geoCityCache, setGeoCityCache] = useState<Record<string, GeoCity[]>>({});
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoCityLoading, setGeoCityLoading] = useState(false);
  const [geoError, setGeoError] = useState('');
  const [geoCityError, setGeoCityError] = useState('');
  const [search, setSearch] = useState('');
  const readOnlyTabs = useMemo(() => new Set<EntityKey>(['devices', 'interfaces']), []);
  const isReadOnlyTab = readOnlyTabs.has(tab);

  // Pagination states
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const tabs: { key: EntityKey; label: string; labelEn: string; icon: React.ReactNode }[] = [
    { key: 'credentials', label: '凭据中心', labelEn: 'Credentials', icon: <KeyRound size={14} /> },
    { key: 'devices', label: '设备骨架', labelEn: 'Devices', icon: <Server size={14} /> },
    { key: 'interfaces', label: '接口骨架', labelEn: 'Interfaces', icon: <Network size={14} /> },
    { key: 'sites', label: '站点', labelEn: 'Sites', icon: <Building2 size={14} /> },
    { key: 'vrfs', label: 'VRF', labelEn: 'VRFs', icon: <Network size={14} /> },
    { key: 'vlans', label: 'VLAN', labelEn: 'VLANs', icon: <Layers size={14} /> },
    { key: 'tenants', label: '租户', labelEn: 'Tenants', icon: <UsersIcon size={14} /> },
  ];

  const siteOptions = useMemo(
    () => [{ value: '', label: '（无）', labelEn: '(none)' }, ...sites.map(s => ({ value: s.id, label: `${s.site_code} · ${s.site_name}`, labelEn: `${s.site_code} · ${s.site_name}` }))],
    [sites, zh]
  );

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
        (geoCatalog?.countries || []).map(country => ({ value: countryDisplayName(country), label: countryDisplayName(country), searchText: country.name })),
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
    };
  }, [form, geoCatalog, geoCities, geoStates]);

  const fieldDefs: Record<EntityKey, FieldDef[]> = useMemo(() => ({
    credentials: [
      { key: 'credential_name', label: '凭据名称', labelEn: 'Name', required: true },
      { key: 'credential_type', label: '类型', labelEn: 'Type', type: 'select', options: CRED_TYPE_OPTS },
      { key: 'username', label: '用户名', labelEn: 'Username' },
      { key: 'account_role', label: '账号角色', labelEn: 'Account Role', hideInForm: true },
      { key: 'password', label: '密码', labelEn: 'Password', type: 'password', hideInTable: true, secretFlag: 'has_password' },
      { key: 'enable_password', label: 'Enable 密码', labelEn: 'Enable Password', type: 'password', hideInTable: true, secretFlag: 'has_enable_password' },
      { key: 'snmp_community', label: 'SNMP Community', labelEn: 'SNMP Community', type: 'password', hideInTable: true, secretFlag: 'has_snmp_community' },
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
      { key: 'interface_name', label: '接口名称', labelEn: 'Interface', hideInForm: true },
      { key: 'device_hostname', label: '所属设备', labelEn: 'Device', hideInForm: true },
      { key: 'device_ip', label: '设备IP', labelEn: 'Device IP', hideInForm: true },
      { key: 'oper_status', label: '运行状态', labelEn: 'Oper Status', hideInForm: true },
      { key: 'admin_status', label: '管理状态', labelEn: 'Admin Status', hideInForm: true },
      { key: 'mac_address', label: 'MAC', labelEn: 'MAC', hideInForm: true },
      { key: 'switchport_mode', label: '交换模式', labelEn: 'Switchport', hideInForm: true },
      { key: 'access_vlan', label: 'Access VLAN', labelEn: 'Access VLAN', hideInForm: true },
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
      { key: 'vlan_id', label: 'VLAN ID', labelEn: 'VLAN ID', type: 'number', required: true, placeholder: '1-4094' },
      { key: 'name', label: '名称', labelEn: 'Name', required: true },
      { key: 'site_id', label: '站点', labelEn: 'Site', type: 'select' },
      { key: 'status', label: '状态', labelEn: 'Status', type: 'select', options: VLAN_STATUS_OPTS },
    ],
    tenants: [
      { key: 'name', label: '租户名称', labelEn: 'Name', required: true },
      { key: 'description', label: '描述', labelEn: 'Description' },
    ],
  }), []);

  const endpointFor = (key: EntityKey, id?: string) => {
    const base = key === 'credentials' ? '/api/credentials' : `/api/cmdb/${key}`;
    return id ? `${base}/${id}` : base;
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiList<any>(endpointFor(tab));
      setRows(data);
      if (tab === 'vlans' && sites.length === 0) {
        setSites(await apiList<any>('/api/cmdb/sites').catch(() => []));
      }
    } catch (e: any) {
      setError(e.message || String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  // Preload sites so the VLAN form's site dropdown is ready.
  useEffect(() => { apiList<any>('/api/cmdb/sites').then(setSites).catch(() => {}); }, []);

  // Reset page number on tab or search change
  useEffect(() => {
    setPage(1);
  }, [tab, search]);

  const openCreate = () => {
    if (isReadOnlyTab) return;
    const defaults: Record<string, any> = {};
    fieldDefs[tab].forEach(f => {
      if (f.hideInForm) return;
      if (f.type === 'select' && f.options?.length) defaults[f.key] = f.options[0].value;
      else if (f.key === 'timezone') defaults[f.key] = 'Asia/Shanghai';
      else defaults[f.key] = '';
    });
    setForm(defaults);
    setEditing(null);
    setError('');
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
    setVisiblePasswordFields({});
    setModalOpen(true);
  };

  const idOf = (row: any) => row.id;

  const submit = async () => {
    if (isReadOnlyTab) return;
    setError('');
    const defs = fieldDefs[tab].filter(fd => !fd.hideInForm);
    // basic required validation
    for (const fd of defs) {
      if (fd.required && (form[fd.key] === '' || form[fd.key] == null)) {
        setError(zh ? `请填写「${fd.label}」` : `${fd.labelEn} is required`);
        return;
      }
    }
    // Build payload; omit blank secrets on edit so they stay unchanged.
    const payload: Record<string, any> = {};
    defs.forEach(fd => {
      let v = form[fd.key];
      if (fd.type === 'number') v = v === '' ? undefined : Number(v);
      if (fd.secretFlag && editing && (v === '' || v == null)) return; // keep existing secret
      if (fd.key === 'site_id' && v === '') { payload[fd.key] = null; return; }
      if (v !== undefined) payload[fd.key] = v;
    });
    try {
      if (editing) await apiSend(endpointFor(tab, idOf(editing)), 'PUT', payload);
      else await apiSend(endpointFor(tab), 'POST', payload);
      setModalOpen(false);
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
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
        case 'admin': return 'Admin';
        case 'mixed': return 'Mixed';
        case 'unbound': return 'Unbound';
        case 'login':
        default: return 'Login';
      }
    }
    switch (role) {
      case 'normal': return '普通账号';
      case 'admin': return '管理员账号';
      case 'mixed': return '多角色';
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
      case 'unbound':
        return 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-900/20 dark:text-slate-400 dark:border-slate-800';
      case 'login':
      default:
        return 'bg-indigo-50 text-indigo-700 border-indigo-100 dark:bg-indigo-950/20 dark:text-indigo-400 dark:border-indigo-900/30';
    }
  };

  const renderCell = (row: any, fd: FieldDef) => {
    if (tab === 'devices' && fd.key === 'hostname') {
      const val = row.hostname || row.ip_address || row.id;
      return (
        <button
          onClick={() => navigate('/assets/devices')}
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
          onClick={() => navigate('/assets/devices')}
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
      return (
        <div className="flex flex-wrap gap-1">
          {devList.map((d: any) => (
            <span
              key={d.id}
              onClick={() => navigate(`/assets/devices`)}
              className="cursor-pointer inline-flex items-center gap-1 text-slate-700 dark:text-slate-350 bg-slate-100 dark:bg-slate-800 border border-slate-200/50 dark:border-slate-700 px-2 py-0.5 rounded text-xs font-medium hover:bg-slate-200 dark:hover:bg-slate-750 transition-colors"
            >
              <Server size={11} className="text-slate-400" />
              {d.hostname}
            </span>
          ))}
        </div>
      );
    }
    if (fd.secretFlag) {
      return row[fd.secretFlag] ? (
        <span className="inline-flex items-center gap-1 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-900/30 px-2 py-0.5 rounded text-xs font-medium">
          <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
          {zh ? '已配置' : 'Configured'}
        </span>
      ) : (
        <span className="text-black/30 dark:text-white/30">—</span>
      );
    }
    if (fd.key === 'site_id') {
      const s = sites.find(x => x.id === row.site_id);
      return s ? (
        <span className="inline-flex items-center gap-1 text-cyan-700 dark:text-cyan-400 bg-cyan-50 dark:bg-cyan-950/20 border border-cyan-100 dark:border-cyan-900/30 px-2 py-0.5 rounded text-xs font-semibold">
          <Building2 size={12} />
          {s.site_code}
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
    if (tab === 'sites' && fd.key === 'city') {
      const val = String(row.city || '').trim();
      if (!val) return <span className="text-black/30 dark:text-white/30">—</span>;
      const isChina = CHINA_LEGACY_COUNTRY_VALUES.has(String(row.country || '').trim());
      const display = isChina ? cityDisplayName({ name: val, stateCode: '', countryCode: 'CN' }) : val;
      return <span>{display}</span>;
    }
    if (fd.key === 'oper_status' || fd.key === 'admin_status') {
      const val = row[fd.key] || 'unknown';
      const badgeClass = val === 'up'
        ? 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/20 dark:text-emerald-400 dark:border-emerald-900/30'
        : val === 'down'
          ? 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/20 dark:text-rose-400 dark:border-rose-900/30'
          : 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-900/20 dark:text-slate-400 dark:border-slate-800';
      return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${badgeClass}`}>
          {val}
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
          title={zh ? '根据绑定设备的普通账号/管理员账号字段推断' : 'Inferred from linked device normal/admin username fields'}
        >
          {row.account_role_label || getAccountRoleLabel(role)}
        </span>
      );
    }

    const isMono = ['vlan_id', 'rd', 'username', 'ip_address', 'device_ip', 'mac_address', 'access_vlan'].includes(fd.key);
    const val = row[fd.key];
    if (val === '' || val == null) return <span className="text-black/30 dark:text-white/30">—</span>;
    if (isMono) {
      return (
        <span className="font-mono text-xs text-black/75 dark:text-white/75 bg-black/[0.03] dark:bg-white/5 px-1.5 py-0.5 rounded border border-black/[0.04] dark:border-white/5">
          {String(val)}
        </span>
      );
    }
    return <span className="text-sm font-medium text-black/75 dark:text-white/85">{String(val)}</span>;
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
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  
  // Clamp page selection
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const paginatedRows = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredRows.slice(start, start + pageSize);
  }, [filteredRows, page, pageSize]);

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
                className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl bg-[#06b6d4] px-4 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(6,182,212,0.22)] transition-all duration-200 hover:-translate-y-0.5 hover:bg-[#0891b2]"
              >
                <Plus size={14} />
                {zh ? '新建记录' : 'New Record'}
              </button>
            )}
            <button
              onClick={load}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[#d8e1eb] bg-[#f8fafc] px-4 text-sm font-semibold text-[#164e63] transition-all duration-200 hover:-translate-y-0.5 hover:border-[#c7d4e2] hover:bg-white hover:text-[#0891b2]"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </>
        }
        extras={
          <div className="flex items-center justify-end gap-4 mt-3 flex-wrap">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                placeholder={zh ? '搜索当前列表...' : 'Search current list...'}
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
        {error && (
          <div className="mb-4 px-4 py-3 rounded-2xl text-sm flex items-center gap-2 border bg-rose-50/10 text-rose-500 border-rose-200/30">
            <ShieldAlert size={16} />
            {error}
          </div>
        )}

        <div className="rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
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
                {paginatedRows.map((row, i) => (
                  <tr key={idOf(row) || i} className="hover:bg-slate-50/80 transition-colors group">
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
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            currentPage={page}
            totalItems={filteredRows.length}
            onPageChange={setPage}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
            language={zh ? 'zh' : 'en'}
          />
        </div>
      </div>

      {/* Create/Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setModalOpen(false)} />
          <div className="relative w-full max-w-md rounded-3xl border border-black/8 bg-white p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between mb-4 border-b border-black/5 pb-3">
              <h2 className="text-lg font-semibold text-[#164e63]">
                {editing ? (zh ? '编辑记录' : 'Edit Record') : (zh ? '新建记录' : 'New Record')} · {zh ? tabs.find(t => t.key === tab)?.label : tabs.find(t => t.key === tab)?.labelEn}
              </h2>
              <button onClick={() => setModalOpen(false)} className="rounded-xl border border-black/10 p-1.5 text-black/55 hover:bg-black/[0.03] transition-colors"><X size={16} /></button>
            </div>
            <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
              {fieldDefs[tab].filter(fd => !fd.hideInForm).map(fd => {
                const opts = fd.key === 'site_id' ? siteOptions : fd.options;
                const isGeoField = tab === 'sites' && ['country', 'state_province', 'city'].includes(fd.key);
                const geoOpts = isGeoField ? geoSelectOptions[fd.key as 'country' | 'state_province' | 'city'] : [];
                const geoFieldDisabled = geoLoading || Boolean(geoError)
                  || (fd.key === 'state_province' && !selectedGeoCountry)
                  || (fd.key === 'city' && (!selectedGeoCountry || (geoStates.length > 0 && !selectedGeoState)));
                return (
                  <div key={fd.key}>
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
                        allowCustom={fd.key === 'city'}
                        disabled={geoFieldDisabled}
                        placeholder={
                          geoLoading ? '正在加载国家和省州数据…'
                            : geoCityLoading && fd.key === 'city' ? '正在加载城市数据…'
                              : fd.key === 'state_province' && !selectedGeoCountry ? '请先选择国家'
                                : fd.key === 'city' && geoStates.length > 0 && !selectedGeoState ? '请先选择省份 / 州'
                                  : geoError ? '地理数据不可用' : `请选择${zh ? fd.label : fd.labelEn}`
                        }
                        emptyText={fd.key === 'city' && geoCityError ? geoCityError : fd.key === 'city' && selectedGeoState && !geoCities.length ? '该省份 / 州暂无城市数据，可直接手动填写' : '没有匹配的选项'}
                        onChange={next => {
                          if (fd.key === 'country') {
                            setForm({ ...form, country: next, state_province: '', city: '' });
                            setGeoError('');
                          } else if (fd.key === 'state_province') {
                            setForm({ ...form, state_province: next, city: '' });
                          } else {
                            setForm({ ...form, city: next });
                          }
                        }}
                      />
                    ) : fd.type === 'select' && opts ? (
                      <select
                        value={form[fd.key] ?? ''}
                        onChange={e => setForm({ ...form, [fd.key]: e.target.value })}
                        className="w-full px-3 py-2 rounded-xl text-sm border border-black/10 bg-white text-[#164e63] outline-none focus:border-[#06b6d4]/45 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                      >
                        {opts.map(o => <option key={o.value} value={o.value}>{zh ? o.label : (o.labelEn || o.label)}</option>)}
                      </select>
                    ) : fd.type === 'password' ? (
                      <div className="relative">
                        <input
                          type={visiblePasswordFields[fd.key] ? 'text' : 'password'}
                          value={form[fd.key] ?? ''}
                          placeholder={fd.placeholder}
                          autoComplete="new-password"
                          onChange={e => setForm({ ...form, [fd.key]: e.target.value })}
                          className="w-full px-3 py-2 pr-10 rounded-xl text-sm border border-black/10 bg-white text-[#164e63] outline-none focus:border-[#06b6d4]/45 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
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
                        type={fd.type === 'number' ? 'number' : 'text'}
                        value={form[fd.key] ?? ''}
                        placeholder={fd.placeholder}
                        autoComplete="off"
                        onChange={e => setForm({ ...form, [fd.key]: e.target.value })}
                        className="w-full px-3 py-2 rounded-xl text-sm border border-black/10 bg-white text-[#164e63] outline-none focus:border-[#06b6d4]/45 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                      />
                    )}
                  </div>
                );
              })}
            </div>
            {tab === 'sites' && geoError && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{geoError}</div>
            )}
            
            {error && (
              <div className="mt-4 px-3 py-2 rounded-xl text-xs flex items-center gap-1.5 border bg-rose-50/10 text-rose-500 border-rose-200/30">
                <ShieldAlert size={14} className="flex-shrink-0" />
                {error}
              </div>
            )}
            
            <div className="flex justify-end gap-2 mt-6 pt-3 border-t border-black/5">
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
