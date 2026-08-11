import React, { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Code2,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileCode2,
  FileCog,
  FileJson,
  Filter,
  FolderOpen,
  History,
  Import,
  Layers,
  Loader2,
  Maximize2,
  Minimize2,
  Plus,
  Pencil,
  RefreshCw,
  Save,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Star,
  Trash2,
  Upload,
  WandSparkles,
  WrapText,
  X,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { ConfigTemplate, Device } from '../types';
import PageHero from '../components/PageHero';
import { apiRequest, authHeaders } from '../api/http';
import { VENDOR_PLATFORMS } from './AssetManagement/constants';

type ConfigWorkspaceView = 'source' | 'rendered' | 'checks';
type TemplateType = 'Jinja2' | 'YAML';
type ToastTone = 'success' | 'error' | 'warning' | 'info';
type PreviewTab = 'preview' | 'source' | 'json' | 'checks' | 'versions';
type RenderState = 'idle' | 'rendering' | 'success' | 'warning' | 'error';

interface GlobalVarItem {
  id?: string;
  key: string;
  value: string;
}

interface TemplateVariable {
  name: string;
  label: string;
  description?: string;
  type: string;
  required: boolean;
  default_value?: unknown;
  example_value?: unknown;
  placeholder?: string;
  validation_rules?: Record<string, unknown>;
  options?: Array<string | { value: string; label?: string }>;
  sort_order?: number;
  group_name?: string;
  is_secret?: boolean;
  is_advanced?: boolean;
  allow_multiline?: boolean;
}

interface TemplateVersion {
  id: string;
  version: string;
  change_summary?: string;
  checksum?: string;
  status?: string;
  created_by?: string;
  created_at?: string;
  published_at?: string;
}

interface TemplateDetail extends ConfigTemplate {
  variable_schema: TemplateVariable[];
  example_values: Record<string, unknown>;
  quality: { score: number; checks: Record<string, boolean> };
  is_favorite: boolean;
  variable_count: number;
  versions: TemplateVersion[];
  version: {
    version: string;
    source: string;
    rollback_source?: string;
    variable_schema: TemplateVariable[];
    example_values: Record<string, unknown>;
  };
  compatibility?: Array<Record<string, unknown>>;
}

interface TemplateEditorForm {
  name: string;
  vendor: string;
  platform: string;
  category: string;
  description: string;
  software_version: string;
  usage_notes: string;
  risk_notes: string;
  content: string;
  rollback: string;
  example_values: string;
  variable_schema: TemplateVariable[];
}

interface RenderIssue {
  field?: string;
  code?: string;
  line?: number;
  message: string;
}

interface RenderResult {
  success: boolean;
  render_status: string;
  rendered_output: string;
  rendered_rollback?: string;
  line_count: number;
  command_count: number;
  used_variables: string[];
  defaulted_variables: string[];
  warnings: RenderIssue[];
  errors: RenderIssue[];
  risk_level: string;
  risk_items: Array<{ line: number; command: string; message: string }>;
  source_map: Array<{ output_line: number; variable: string; value: string; source: string }>;
  quality_score?: number;
  parameter_validation?: {
    sources?: Record<string, string>;
    normalized_values?: Record<string, unknown>;
  };
}

interface ParameterProfile {
  id: string;
  template_version: string;
  name: string;
  description?: string;
  values: Record<string, unknown>;
  value_sources: Record<string, string>;
  scope: string;
  is_default: boolean;
  created_by?: string;
  updated_at?: string;
}

interface PlatformSettingsTabProps {
  t: (key: string) => string;
  language: string;
  sectionHeaderRowClass: string;
  configTemplates: ConfigTemplate[];
  configVariableKeys: string[];
  configMissingVariables: string[];
  configScopedDevices: Device[];
  configScopedOnlineCount: number;
  configReadinessScore: number;
  configValidationIssues: string[];
  configValidationWarnings: string[];
  configWorkspaceView: ConfigWorkspaceView;
  selectedTemplateId: string;
  selectedConfigTemplate: ConfigTemplate | null;
  globalVars: GlobalVarItem[];
  editorContent: string;
  configRenderedPreview: string;
  configScopePlatform: string;
  configScopeRole: string;
  configScopeSite: string;
  configPlatformOptions: string[];
  configRoleOptions: string[];
  configSiteOptions: string[];
  extractVars: (text: string) => string[];
  getPlatformLabel: (platform: string) => string;
  onImportVars: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onCreateTemplate: () => void;
  onSelectTemplateIdChange: (templateId: string) => void;
  onAddVar: () => void;
  onDeleteVar: (id: string) => void;
  onSelectedTemplateNameChange: (value: string) => void;
  onSelectedTemplateVendorChange: (value: string) => void;
  onSelectedTemplateTypeChange: (value: TemplateType) => void;
  onDiscardChanges: () => void;
  onConfigWorkspaceViewChange: (view: ConfigWorkspaceView) => void;
  onValidate: () => void;
  onSaveTemplate: () => void;
  onCreateScenarioDraft: () => void;
  onSendToAutomation: () => void;
  onEditorContentChange: (value: string) => void;
  onConfigScopePlatformChange: (value: string) => void;
  onConfigScopeRoleChange: (value: string) => void;
  onConfigScopeSiteChange: (value: string) => void;
  showToast: (message: string, tone: ToastTone) => void;
}

const VENDOR_STYLE: Record<string, { chip: string; gradient: string; label: string }> = {
  Cisco: { chip: 'bg-sky-50 text-sky-700 ring-sky-100', gradient: 'from-sky-500 to-cyan-500', label: 'Cisco' },
  Huawei: { chip: 'bg-rose-50 text-rose-700 ring-rose-100', gradient: 'from-rose-500 to-red-600', label: 'Huawei' },
  H3C: { chip: 'bg-amber-50 text-amber-700 ring-amber-100', gradient: 'from-amber-500 to-orange-500', label: 'H3C' },
  Juniper: { chip: 'bg-emerald-50 text-emerald-700 ring-emerald-100', gradient: 'from-emerald-500 to-teal-600', label: 'Juniper' },
  Arista: { chip: 'bg-orange-50 text-orange-700 ring-orange-100', gradient: 'from-orange-500 to-amber-500', label: 'Arista' },
  Ruijie: { chip: 'bg-violet-50 text-violet-700 ring-violet-100', gradient: 'from-violet-500 to-fuchsia-500', label: 'Ruijie' },
  ZTE: { chip: 'bg-indigo-50 text-indigo-700 ring-indigo-100', gradient: 'from-indigo-500 to-blue-600', label: 'ZTE' },
  Maipu: { chip: 'bg-teal-50 text-teal-700 ring-teal-100', gradient: 'from-teal-500 to-emerald-500', label: 'Maipu' },
  DPtech: { chip: 'bg-orange-50 text-orange-700 ring-orange-100', gradient: 'from-orange-500 to-red-500', label: 'DPtech' },
  Custom: { chip: 'bg-slate-100 text-slate-600 ring-slate-200', gradient: 'from-slate-500 to-slate-700', label: 'Custom' },
};

const CONFIG_VENDOR_PLATFORM_OPTIONS: Record<string, Array<{ value: string; label: string }>> = {
  ...VENDOR_PLATFORMS,
  Cisco: [
    { value: 'cisco_ios', label: 'Cisco IOS' },
    { value: 'cisco_iosxe', label: 'Cisco IOS XE' },
    { value: 'cisco_xe', label: 'Cisco IOS-XE' },
    { value: 'cisco_nxos', label: 'Cisco NX-OS' },
    { value: 'cisco_iosxr', label: 'Cisco IOS-XR' },
    { value: 'cisco_asa', label: 'Cisco ASA' },
  ],
  Huawei: [
    { value: 'huawei_vrp', label: 'Huawei VRP' },
    { value: 'huawei_vrpv8', label: 'Huawei VRP8' },
    { value: 'huawei_smartax', label: 'Huawei SmartAX' },
    { value: 'huawei_usg', label: 'Huawei USG' },
  ],
  H3C: [
    { value: 'h3c_comware', label: 'H3C Comware' },
  ],
  Ruijie: [{ value: 'ruijie_rgos', label: 'Ruijie RGOS' }, { value: 'ruijie_os', label: 'Ruijie OS (alias)' }],
  ZTE: [{ value: 'zte_zxros', label: 'ZTE ZXROS' }],
  Maipu: [{ value: 'maipu', label: 'Maipu MyPowerOS' }, { value: 'maipu_mypower', label: 'Maipu MyPower (alias)' }],
  DPtech: [
    { value: 'dptech_ios', label: 'DPTech IOS' },
    { value: 'dptech_conplat', label: 'DPTech Conplat' },
    { value: 'dptech_conplat_fw', label: 'DPTech Conplat FW' },
  ],
  Custom: [{ value: 'custom', label: 'Custom platform' }],
};

const CONFIG_VENDOR_OPTIONS = Object.keys(CONFIG_VENDOR_PLATFORM_OPTIONS);

const SOURCE_LABELS: Record<string, string> = {
  user: '用户填写',
  template_default: '模板默认值',
  example: '示例值',
  profile: '参数方案',
  system: '系统计算',
  device: '设备上下文',
};

const PARAMETER_TYPE_LABELS: Record<string, { zh: string; en: string }> = {
  string: { zh: '文本', en: 'Text' },
  text: { zh: '单行文本', en: 'Single-line text' },
  integer: { zh: '整数', en: 'Integer' },
  vlan_id: { zh: 'VLAN 编号', en: 'VLAN ID' },
  ipv4_address: { zh: 'IPv4 地址', en: 'IPv4 address' },
  ipv4_netmask: { zh: 'IPv4 子网掩码', en: 'IPv4 netmask' },
  ipv4_wildcard_mask: { zh: 'IPv4 通配符掩码', en: 'IPv4 wildcard mask' },
  ipv4_network: { zh: 'IPv4 网段', en: 'IPv4 network' },
  ipv6_address: { zh: 'IPv6 地址', en: 'IPv6 address' },
  ipv6_network: { zh: 'IPv6 网段', en: 'IPv6 network' },
  interface: { zh: '接口名称', en: 'Interface name' },
  asn: { zh: 'BGP ASN', en: 'BGP ASN' },
  ospf_area: { zh: 'OSPF 区域 ID', en: 'OSPF area ID' },
  vlan_list: { zh: 'VLAN 列表', en: 'VLAN list' },
  hostname: { zh: '主机名', en: 'Hostname' },
  mac_address: { zh: 'MAC 地址', en: 'MAC address' },
  boolean: { zh: '开关', en: 'Boolean' },
  list: { zh: '列表', en: 'List' },
  password: { zh: '敏感值', en: 'Secret' },
};

const parameterTypeLabel = (type: string, zh: boolean) => PARAMETER_TYPE_LABELS[type]?.[zh ? 'zh' : 'en'] || type;

const hasParameterValue = (value: unknown) => value !== undefined && value !== null && value !== '';

const isSensitiveVariable = (item: TemplateVariable) => {
  if (item.is_secret || item.type === 'password') return true;
  const normalized = item.name.toLowerCase().replace(/[.\-]+/g, '_');
  if (['public_key', 'key_id', 'key_name', 'key_type'].includes(normalized) || normalized.startsWith('public_key_')) return false;
  const tokens = new Set(normalized.split('_').filter(Boolean));
  return ['password', 'passwd', 'secret', 'community', 'token', 'credential', 'private', 'shared'].some((token) => tokens.has(token))
    || normalized === 'key'
    || normalized.endsWith('_key');
};

const sourceLabel = (source: string, zh: boolean) => {
  if (zh) return SOURCE_LABELS[source] || source;
  const labels: Record<string, string> = {
    user: 'User input',
    template_default: 'Template default',
    example: 'Example',
    profile: 'Parameter profile',
    system: 'System',
    device: 'Device context',
  };
  return labels[source] || source;
};

const riskLabel = (risk: string | undefined, zh: boolean) => ({
  none: zh ? '无风险' : 'None',
  low: zh ? '低风险' : 'Low',
  medium: zh ? '中风险' : 'Medium',
  high: zh ? '高风险' : 'High',
  critical: zh ? '严重风险' : 'Critical',
}[risk || 'none'] || risk || (zh ? '无风险' : 'None'));

const PREVIEW_TABS: Array<{ id: PreviewTab; zh: string; en: string; icon: React.ReactNode }> = [
  { id: 'preview', zh: '命令预览', en: 'Preview', icon: <FileCode2 size={13} /> },
  { id: 'source', zh: '模板源码', en: 'Source', icon: <Code2 size={13} /> },
  { id: 'json', zh: '参数 JSON', en: 'Parameters', icon: <FileJson size={13} /> },
  { id: 'checks', zh: '校验结果', en: 'Validation', icon: <ShieldCheck size={13} /> },
  { id: 'versions', zh: '版本差异', en: 'Version diff', icon: <History size={13} /> },
];

const fieldClass = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100';

const parseJson = <T,>(value: string | undefined, fallback: T): T => {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

const formatModelPattern = (pattern: unknown) => {
  const raw = String(pattern || '').trim();
  if (!raw) return '';
  const readable = raw
    .replace(/\\s\*/g, ' ')
    .replace(/\\s\?/g, ' ')
    .replace(/\\s/g, ' ')
    .replace(/\\([.*+?^${}()|[\]\\])/g, '$1')
    .replace(/\\d(?:\{\d+,?\d*\}|\+)/g, '数字')
    .replace(/\(\?:/g, '')
    .replace(/[()]/g, '')
    .replace(/[?$^]/g, '')
    .replace(/\|/g, ' / ')
    .replace(/\s+/g, ' ')
    .trim();
  return readable || raw;
};

const formatLastUsed = (value: string | null | undefined, zh: boolean) => {
  if (value === null || value === undefined || value === '') return zh ? '从未使用' : 'Never used';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return zh ? '时间格式错误' : 'Invalid time';
  return parsed.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const safeFileName = (value: string) => value.replace(/[^\w\u4e00-\u9fa5-]+/g, '_').slice(0, 80) || 'config';

const downloadText = (content: string, filename: string, type = 'text/plain;charset=utf-8') => {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

const copyText = async (content: string) => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(content);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = content;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('Clipboard is unavailable');
};

interface TemplateLibraryCardProps {
  template: ConfigTemplate;
  selected: boolean;
  zh: boolean;
  onSelect: (templateId: string) => void;
  onFavorite: (template: ConfigTemplate) => void;
  onEdit: (template: ConfigTemplate) => void;
  onArchive: (template: ConfigTemplate) => void;
  onCopy: (template: ConfigTemplate) => void;
}

const TemplateLibraryCard = React.memo<TemplateLibraryCardProps>(({
  template,
  selected,
  zh,
  onSelect,
  onFavorite,
  onEdit,
  onArchive,
  onCopy,
}) => {
  const brand = VENDOR_STYLE[template.vendor || 'Custom'] || VENDOR_STYLE.Custom;
  const official = Boolean(template.is_official || template.source_type === 'official');
  const variableCount = parseJson<TemplateVariable[]>(template.variable_schema_json, []).length;
  return (
    <div
      className={`group relative rounded-xl border transition ${selected ? 'border-cyan-300 bg-cyan-50/50 shadow-sm ring-1 ring-cyan-100' : 'border-slate-200 bg-white hover:border-cyan-200'}`}
      style={{ contentVisibility: 'auto', containIntrinsicSize: '0 124px' }}
    >
      <button type="button" onClick={() => onSelect(template.id)} className="w-full p-3 pr-9 text-left">
        <div className="flex items-center gap-1.5">
          <span className={`rounded px-1.5 py-0.5 text-[9px] font-black ring-1 ${brand.chip}`}>{template.vendor || 'Custom'}</span>
          {template.platform_family && <span className="max-w-24 truncate rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-500">{template.platform_family}</span>}
          <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${official ? 'bg-blue-50 text-blue-700' : 'bg-violet-50 text-violet-700'}`}>
            {official ? (zh ? '官方' : 'Official') : (zh ? '自定义' : 'Custom')}
          </span>
        </div>
        <p className="mt-2 truncate text-[13px] font-black text-slate-800">{template.name}</p>
        <p className="mt-1 line-clamp-2 min-h-8 text-[10px] leading-4 text-slate-500">{template.description || (zh ? '暂无模板说明' : 'No description')}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1 text-[9px] text-slate-400">
          <span>{variableCount || '—'} {zh ? '变量' : 'vars'}</span>
          <span>· v{template.current_version || '1.0'}</span>
          <span>· {template.risk_level || 'low'}</span>
          <span>· {formatLastUsed(template.lastUsed, zh)}</span>
        </div>
      </button>
      <button type="button" onClick={() => void onFavorite(template)} className={`absolute right-2 top-2 rounded-lg p-1.5 transition ${template.is_favorite ? 'text-amber-500' : 'text-slate-300 opacity-0 hover:text-amber-500 group-hover:opacity-100'}`} title={zh ? '收藏模板' : 'Favorite'}>
        <Star size={13} fill={template.is_favorite ? 'currentColor' : 'none'} />
      </button>
      {!official && (
        <>
          <button type="button" onClick={() => onEdit(template)} className="absolute right-9 top-2 rounded-lg p-1.5 text-slate-300 opacity-0 transition hover:bg-cyan-50 hover:text-cyan-700 group-hover:opacity-100" title={zh ? '编辑自定义模板' : 'Edit custom template'}>
            <Pencil size={12} />
          </button>
          <button type="button" onClick={() => void onArchive(template)} className="absolute bottom-2 right-2 rounded-lg p-1.5 text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100" title={zh ? '归档模板' : 'Archive template'}>
            <Trash2 size={12} />
          </button>
        </>
      )}
      <button type="button" onClick={() => void onCopy(template)} className="absolute bottom-2 right-9 rounded-lg p-1.5 text-slate-300 opacity-0 transition hover:bg-cyan-50 hover:text-cyan-700 group-hover:opacity-100" title={zh ? '复制为自定义模板' : 'Copy as custom template'}>
        <Copy size={12} />
      </button>
    </div>
  );
});

TemplateLibraryCard.displayName = 'TemplateLibraryCard';

const PlatformSettingsTab: React.FC<PlatformSettingsTabProps> = ({
  t,
  language,
  configTemplates,
  selectedTemplateId,
  globalVars,
  onSelectTemplateIdChange,
  showToast,
}) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const importRef = useRef<HTMLInputElement>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);

  const [templates, setTemplates] = useState<ConfigTemplate[]>(configTemplates);
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [vendorFilter, setVendorFilter] = useState('all');
  const [platformFilter, setPlatformFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortBy, setSortBy] = useState<'name' | 'updated' | 'usage' | 'quality'>('updated');
  const [advancedFiltersOpen, setAdvancedFiltersOpen] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [leftWidth, setLeftWidth] = useState(326);
  const [parameterWidth, setParameterWidth] = useState(400);
  const [previewTab, setPreviewTab] = useState<PreviewTab>('preview');
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [parameterSources, setParameterSources] = useState<Record<string, string>>({});
  const [groupCollapsed, setGroupCollapsed] = useState<Record<string, boolean>>({});
  const [renderState, setRenderState] = useState<RenderState>('idle');
  const [renderResult, setRenderResult] = useState<RenderResult | null>(null);
  const [lastSuccessfulResult, setLastSuccessfulResult] = useState<RenderResult | null>(null);
  const [sourceContent, setSourceContent] = useState('');
  const [sourceDirty, setSourceDirty] = useState(false);
  const [wrapPreview, setWrapPreview] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [previewSearch, setPreviewSearch] = useState('');
  const [profiles, setProfiles] = useState<ParameterProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [profileName, setProfileName] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileExpanded, setProfileExpanded] = useState(false);
  const [sourceSaving, setSourceSaving] = useState(false);
  const [taskCreating, setTaskCreating] = useState(false);
  const [versionFrom, setVersionFrom] = useState('');
  const [versionTo, setVersionTo] = useState('');
  const [versionDiff, setVersionDiff] = useState<string[]>([]);
  const [versionDiffLoading, setVersionDiffLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);
  const [createForm, setCreateForm] = useState<TemplateEditorForm>({
    name: '', vendor: 'Cisco', platform: 'cisco_iosxe', category: 'interface',
    description: '', software_version: '', usage_notes: '', risk_notes: '',
    content: '', rollback: '', example_values: '{}', variable_schema: [],
  });
  const [creatingTemplate, setCreatingTemplate] = useState(false);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
  const [revealedSecrets, setRevealedSecrets] = useState<Record<string, boolean>>({});
  const parameterDrafts = useRef<Record<string, Record<string, unknown>>>({});
  const previousTemplateIdRef = useRef(selectedTemplateId);
  const activeTemplateIdRef = useRef(selectedTemplateId);
  const loadRequestRef = useRef(0);
  const loadingTemplateIdRef = useRef('');
  const templateLoadAbortRef = useRef<AbortController | null>(null);
  const templateCacheRef = useRef<Map<string, { detail: TemplateDetail; profiles: ParameterProfile[] }>>(new Map());
  const detailRef = useRef<TemplateDetail | null>(null);
  const sourceContentRef = useRef('');
  const draftStorageKey = (templateId: string) => `nexora.config-template-draft.${templateId}`;

  detailRef.current = detail;
  sourceContentRef.current = sourceContent;

  useEffect(() => {
    setTemplates(configTemplates);
  }, [configTemplates]);

  const refreshTemplates = useCallback(async () => {
    try {
      const result = await apiRequest<{ items: ConfigTemplate[] }>('/api/config-templates?page=1&page_size=200&sort=updated');
      setTemplates(result.items || []);
      return result.items || [];
    } catch {
      return templates;
    }
  }, [templates]);

  const applyLoadedTemplate = useCallback((
    templateId: string,
    templateDetail: TemplateDetail,
    templateProfiles: ParameterProfile[],
  ) => {
    if (activeTemplateIdRef.current !== templateId) return;
    let storedDraft: { parameters?: Record<string, unknown>; source?: string } | null = null;
    try {
      const raw = window.localStorage.getItem(`nexora.config-template-draft.${templateId}`);
      storedDraft = raw ? JSON.parse(raw) as { parameters?: Record<string, unknown>; source?: string } : null;
    } catch {
      storedDraft = null;
    }
    const draft = parameterDrafts.current[templateId] || storedDraft?.parameters;
    const versions = templateDetail.versions || [];
    startTransition(() => {
      setDetail(templateDetail);
      setProfiles(templateProfiles);
      setSourceContent(storedDraft?.source || templateDetail.version?.source || templateDetail.content || '');
      setSourceDirty(Boolean(storedDraft?.source));
      setParameters(draft || {});
      setParameterSources(draft ? Object.fromEntries(Object.keys(draft).map((name) => [name, 'user'])) : {});
      setSelectedProfileId('');
      setProfileName('');
      setRenderResult(null);
      setLastSuccessfulResult(null);
      setRenderState('idle');
      setPreviewTab('preview');
      setPreviewSearch('');
      setGroupCollapsed({});
      setReviewAcknowledged(false);
      setRevealedSecrets({});
      setProfileExpanded(false);
      setVersionTo(templateDetail.current_version || versions[0]?.version || '1.0');
      setVersionFrom(versions[1]?.version || versions[0]?.version || '1.0');
    });
  }, []);

  const loadTemplate = useCallback(async (templateId: string, force = false) => {
    if (!templateId || templateId.startsWith('draft-')) return;
    if (loadingTemplateIdRef.current === templateId) return;
    const cached = force ? undefined : templateCacheRef.current.get(templateId);
    if (cached) {
      templateLoadAbortRef.current?.abort();
      templateLoadAbortRef.current = null;
      loadingTemplateIdRef.current = '';
      loadRequestRef.current += 1;
      applyLoadedTemplate(templateId, cached.detail, cached.profiles);
      setDetailLoading(false);
      return;
    }
    templateLoadAbortRef.current?.abort();
    const abortController = new AbortController();
    templateLoadAbortRef.current = abortController;
    loadingTemplateIdRef.current = templateId;
    const requestId = ++loadRequestRef.current;
    setDetailLoading(true);
    const profilesPromise = apiRequest<ParameterProfile[]>(`/api/config-templates/${encodeURIComponent(templateId)}/parameter-profiles`, { signal: abortController.signal })
      .catch(() => [] as ParameterProfile[]);
    try {
      const templateDetail = await apiRequest<TemplateDetail>(`/api/config-templates/${encodeURIComponent(templateId)}`, { signal: abortController.signal });
      if (requestId !== loadRequestRef.current || activeTemplateIdRef.current !== templateId) return;
      templateCacheRef.current.set(templateId, { detail: templateDetail, profiles: [] });
      applyLoadedTemplate(templateId, templateDetail, []);
      void profilesPromise.then((templateProfiles) => {
        templateCacheRef.current.set(templateId, { detail: templateDetail, profiles: templateProfiles || [] });
        if (activeTemplateIdRef.current === templateId) setProfiles(templateProfiles || []);
      });
    } catch (error) {
      if (requestId !== loadRequestRef.current || activeTemplateIdRef.current !== templateId) return;
      if (error && typeof error === 'object' && 'name' in error && error.name === 'AbortError') return;
      showToast(
        error instanceof Error ? error.message : (zh ? '模板详情加载失败' : 'Failed to load template details'),
        'error',
      );
    } finally {
      if (requestId === loadRequestRef.current) {
        if (templateLoadAbortRef.current === abortController) templateLoadAbortRef.current = null;
        loadingTemplateIdRef.current = '';
        setDetailLoading(false);
      }
    }
  }, [applyLoadedTemplate, showToast, zh]);

  useEffect(() => () => {
    templateLoadAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    const previousId = previousTemplateIdRef.current;
    activeTemplateIdRef.current = selectedTemplateId;
    if (previousId && previousId !== selectedTemplateId) {
      // Keep the current detail visible until the next response arrives. This
      // avoids a full three-pane teardown and lets keyed drafts remain isolated
      // without scanning and deleting all localStorage entries on every click.
      setReviewAcknowledged(false);
      setRevealedSecrets({});
      setProfileExpanded(false);
    }
    previousTemplateIdRef.current = selectedTemplateId;
  }, [selectedTemplateId]);

  useEffect(() => {
    if (!selectedTemplateId) {
      if (templates.length > 0) {
        onSelectTemplateIdChange(templates[0].id);
      }
      return;
    }
    // Shared template lookups refresh in the background. Do not reload the
    // current detail when only the left-hand list changed; that would reset
    // in-progress parameters, preview results, and the selected preview tab.
    if (detail?.id !== selectedTemplateId) {
      void loadTemplate(selectedTemplateId);
    }
  }, [detail?.id, loadTemplate, onSelectTemplateIdChange, selectedTemplateId, templates]);

  const schema = detail?.variable_schema || detail?.version?.variable_schema || [];

  const effectiveParameterValue = useCallback((item: TemplateVariable) => {
    const explicitValue = parameters[item.name];
    if (hasParameterValue(explicitValue)) return explicitValue;
    if (hasParameterValue(item.default_value)) return item.default_value;
    return '';
  }, [parameters]);

  const groupedSchema = useMemo(() => {
    const groups = new Map<string, TemplateVariable[]>();
    schema
      .slice()
      .sort((left, right) => (left.sort_order || 0) - (right.sort_order || 0))
      .forEach((item) => {
        const group = item.group_name || (zh ? '基础参数' : 'Basic');
        groups.set(group, [...(groups.get(group) || []), item]);
      });
    return Array.from(groups.entries());
  }, [schema, zh]);

  const requiredVariables = useMemo(() => schema.filter((item) => item.required), [schema]);
  const completedRequired = useMemo(
    () => requiredVariables.filter((item) => hasParameterValue(effectiveParameterValue(item))).length,
    [effectiveParameterValue, requiredVariables],
  );
  const filledParameterCount = useMemo(
    () => schema.filter((item) => hasParameterValue(effectiveParameterValue(item))).length,
    [effectiveParameterValue, schema],
  );
  const availableDefaultCount = useMemo(
    () => schema.filter((item) => !hasParameterValue(parameters[item.name]) && hasParameterValue(item.default_value)).length,
    [parameters, schema],
  );

  const fieldErrors = useMemo(() => {
    const map = new Map<string, string>();
    renderResult?.errors.forEach((issue) => {
      if (issue.field) map.set(issue.field, issue.message);
    });
    return map;
  }, [renderResult]);

  useEffect(() => {
    const groupsWithErrors = new Set<string>();
    schema.forEach((item) => {
      if (fieldErrors.has(item.name)) groupsWithErrors.add(item.group_name || (zh ? '基础参数' : 'Basic'));
    });
    if (groupsWithErrors.size > 0) {
      setGroupCollapsed((current) => {
        const next = { ...current };
        groupsWithErrors.forEach((group) => { next[group] = false; });
        return next;
      });
    }
  }, [fieldErrors, schema, zh]);

  const runRender = useCallback(async (showFeedback = false) => {
    if (!detail?.id || detail.id !== activeTemplateIdRef.current) return;
    const templateId = detail.id;
    setRenderState('rendering');
    try {
      const result = await apiRequest<RenderResult>(`/api/config-templates/${encodeURIComponent(templateId)}/render`, {
        method: 'POST',
        body: JSON.stringify({
          version: detail.current_version || detail.version?.version || '',
          parameters,
          parameter_profile_id: selectedProfileId,
          options: {
            strict: true,
            trim_blank_lines: true,
            include_source_map: true,
          },
        }),
      });
      if (activeTemplateIdRef.current !== templateId) return;
      setRenderResult(result);
      if (result.success) {
        setLastSuccessfulResult(result);
        setRenderState(result.warnings.length > 0 ? 'warning' : 'success');
        if (showFeedback) showToast(zh ? '模板渲染成功' : 'Template rendered', 'success');
      } else {
        setRenderState('error');
        if (showFeedback) showToast(zh ? '参数或模板校验未通过' : 'Validation failed', 'warning');
      }
    } catch (error) {
      if (activeTemplateIdRef.current !== templateId) return;
      setRenderState('error');
      if (showFeedback) {
        showToast(error instanceof Error ? error.message : (zh ? '渲染失败' : 'Render failed'), 'error');
      }
    }
  }, [detail, parameters, selectedProfileId, showToast, zh]);

  useEffect(() => {
    if (!detail?.id) return undefined;
    const timer = window.setTimeout(() => {
      void runRender(false);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [detail?.id, parameters, runRender]);

  useEffect(() => {
    setReviewAcknowledged(false);
  }, [detail?.current_version, detail?.id, parameters]);

  const filteredTemplates = useMemo(() => {
    const normalized = keyword.trim().toLowerCase();
    const list = templates.filter((template) => {
      if (normalized) {
        const haystack = [
          template.id,
          template.code,
          template.name,
          template.description,
          template.vendor,
          template.platform_family,
          template.category,
          template.content,
          ...(parseJson<string[]>(template.tags_json, [])),
        ].join(' ').toLowerCase();
        if (!haystack.includes(normalized)) return false;
      }
      if (vendorFilter !== 'all' && (template.vendor || 'Custom') !== vendorFilter) return false;
      if (platformFilter !== 'all' && (template.platform_family || '') !== platformFilter) return false;
      if (categoryFilter !== 'all' && (template.category || '') !== categoryFilter) return false;
      if (sourceFilter !== 'all' && (template.source_type || 'custom') !== sourceFilter) return false;
      if (statusFilter !== 'all' && (template.status || 'draft') !== statusFilter) return false;
      return true;
    });
    return list.sort((left, right) => {
      if (sortBy === 'name') return left.name.localeCompare(right.name, zh ? 'zh-CN' : 'en');
      if (sortBy === 'usage') return (right.use_count || 0) - (left.use_count || 0);
      if (sortBy === 'quality') return (right.quality_score || 0) - (left.quality_score || 0);
      return String(right.updated_at || '').localeCompare(String(left.updated_at || ''));
    });
  }, [categoryFilter, keyword, platformFilter, sortBy, sourceFilter, statusFilter, templates, vendorFilter, zh]);

  const distinct = useCallback((key: keyof ConfigTemplate) => (
    Array.from(new Set(templates.map((item) => String(item[key] || '')).filter(Boolean))).sort()
  ), [templates]);

  const vendorOptions = useMemo(() => (
    Array.from(new Set([
      ...CONFIG_VENDOR_OPTIONS,
      ...templates.map((item) => String(item.vendor || '')).filter(Boolean),
    ])).sort()
  ), [templates]);

  const platformOptions = useMemo(() => {
    const catalogPlatforms = vendorFilter !== 'all'
      ? (CONFIG_VENDOR_PLATFORM_OPTIONS[vendorFilter] || []).map((item) => item.value)
      : [];
    const templatePlatforms = templates
      .filter((item) => vendorFilter === 'all' || String(item.vendor || '') === vendorFilter)
      .map((item) => String(item.platform_family || ''))
      .filter(Boolean);
    return Array.from(new Set([...catalogPlatforms, ...templatePlatforms])).sort();
  }, [templates, vendorFilter]);

  useEffect(() => {
    if (platformFilter !== 'all' && !platformOptions.includes(platformFilter)) {
      setPlatformFilter('all');
    }
  }, [platformFilter, platformOptions]);

  const activeFilterCount = [vendorFilter, platformFilter, categoryFilter, sourceFilter, statusFilter]
    .filter((value) => value !== 'all').length;

  const clearFilters = useCallback(() => {
    setVendorFilter('all');
    setPlatformFilter('all');
    setCategoryFilter('all');
    setSourceFilter('all');
    setStatusFilter('all');
    setSortBy('updated');
  }, []);

  const selectTemplate = useCallback((id: string) => {
    if (id === activeTemplateIdRef.current) return;
    activeTemplateIdRef.current = id;
    onSelectTemplateIdChange(id);
  }, [onSelectTemplateIdChange]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
      if (!['ArrowUp', 'ArrowDown'].includes(event.key) || filteredTemplates.length === 0) return;
      event.preventDefault();
      const current = filteredTemplates.findIndex((item) => item.id === selectedTemplateId);
      const next = event.key === 'ArrowDown'
        ? Math.min(filteredTemplates.length - 1, current + 1)
        : Math.max(0, current <= 0 ? 0 : current - 1);
      selectTemplate(filteredTemplates[next].id);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [filteredTemplates, selectTemplate, selectedTemplateId]);

  const updateParameter = useCallback((name: string, value: unknown, source = 'user') => {
    setParameters((current) => {
      const next = { ...current, [name]: value };
      if (detail?.id) parameterDrafts.current[detail.id] = next;
      if (detail?.id) {
        try {
          window.localStorage.setItem(draftStorageKey(detail.id), JSON.stringify({ parameters: next, source: sourceContent }));
        } catch {
          // Draft recovery is best effort and must never block parameter editing.
        }
      }
      return next;
    });
    setParameterSources((current) => ({ ...current, [name]: source }));
  }, [detail?.id, sourceContent]);

  const loadExamples = useCallback(() => {
    if (!detail) return;
    const next: Record<string, unknown> = { ...detail.example_values };
    schema.forEach((item) => {
      if (next[item.name] === undefined && item.example_value !== undefined && item.example_value !== null) {
        next[item.name] = item.example_value;
      }
    });
    setParameters(next);
    setParameterSources(Object.fromEntries(Object.keys(next).map((name) => [name, 'example'])));
    if (detail.id) parameterDrafts.current[detail.id] = next;
  }, [detail, schema]);

  const applyTemplateDefaults = useCallback(() => {
    if (!detail) return;
    const defaults = Object.fromEntries(
      schema
        .filter((item) => hasParameterValue(item.default_value))
        .map((item) => [item.name, item.default_value]),
    );
    const next = { ...defaults, ...parameters };
    setParameters(next);
    setParameterSources((current) => ({
      ...Object.fromEntries(Object.keys(defaults).map((name) => [name, 'template_default'])),
      ...current,
    }));
    if (detail.id) parameterDrafts.current[detail.id] = next;
    showToast(
      zh ? `已应用 ${Object.keys(defaults).length} 个模板默认值` : `Applied ${Object.keys(defaults).length} template defaults`,
      'success',
    );
  }, [detail, parameters, schema, showToast, zh]);

  const resetParameters = useCallback(() => {
    setParameters({});
    setParameterSources({});
    setSelectedProfileId('');
    if (detail?.id) parameterDrafts.current[detail.id] = {};
    if (detail?.id) {
      try { window.localStorage.removeItem(draftStorageKey(detail.id)); } catch { /* best effort */ }
    }
  }, [detail?.id]);

  const loadProfile = useCallback((profileId: string) => {
    setSelectedProfileId(profileId);
    const profile = profiles.find((item) => item.id === profileId);
    if (!profile) return;
    const allowed = new Set(schema.map((item) => item.name));
    const compatibleValues = Object.fromEntries(
      Object.entries(profile.values || {}).filter(([key, value]) => allowed.has(key) && value !== '***'),
    );
    setParameters(compatibleValues);
    setParameterSources(Object.fromEntries(Object.keys(compatibleValues).map((name) => [name, 'profile'])));
    if (detail?.id) parameterDrafts.current[detail.id] = compatibleValues;
    const missing = requiredVariables.filter((item) => {
      const value = compatibleValues[item.name];
      return value === undefined || value === null || value === '';
    }).length;
    if (profile.template_version !== detail?.current_version || missing > 0) {
      showToast(zh ? `参数方案部分兼容，仍需补充 ${missing} 个必填参数` : `Profile is partially compatible; ${missing} required values remain`, 'warning');
    }
  }, [detail?.current_version, detail?.id, profiles, requiredVariables, schema, showToast, zh]);

  const saveProfile = useCallback(async () => {
    if (!detail?.id || !profileName.trim()) return;
    setSavingProfile(true);
    try {
      await apiRequest(`/api/config-templates/${encodeURIComponent(detail.id)}/parameter-profiles`, {
        method: 'POST',
        body: JSON.stringify({
          name: profileName.trim(),
          description: '',
          version: detail.current_version || '1.0',
          values: parameters,
          value_sources: parameterSources,
          scope: 'private',
          is_default: false,
        }),
      });
      const list = await apiRequest<ParameterProfile[]>(`/api/config-templates/${encodeURIComponent(detail.id)}/parameter-profiles`);
      setProfiles(list);
      setProfileName('');
      showToast(zh ? '参数方案已保存' : 'Parameter profile saved', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '参数方案保存失败' : 'Failed to save profile'), 'error');
    } finally {
      setSavingProfile(false);
    }
  }, [detail, parameterSources, parameters, profileName, showToast, zh]);

  const deleteProfile = useCallback(async () => {
    if (!detail?.id || !selectedProfileId) return;
    try {
      await apiRequest(`/api/config-templates/${encodeURIComponent(detail.id)}/parameter-profiles/${encodeURIComponent(selectedProfileId)}`, { method: 'DELETE' });
      setProfiles((items) => items.filter((item) => item.id !== selectedProfileId));
      setSelectedProfileId('');
      showToast(zh ? '参数方案已删除' : 'Profile deleted', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '删除失败' : 'Delete failed'), 'error');
    }
  }, [detail?.id, selectedProfileId, showToast, zh]);

  const toggleFavorite = useCallback(async (template: ConfigTemplate) => {
    const favorite = !(template as TemplateDetail).is_favorite;
    try {
      await apiRequest(`/api/config-templates/${encodeURIComponent(template.id)}/favorite?favorite=${favorite}`, { method: 'PUT' });
      setTemplates((items) => items.map((item) => item.id === template.id ? { ...item, is_favorite: favorite } as ConfigTemplate : item));
      setDetail((current) => current?.id === template.id ? { ...current, is_favorite: favorite } : current);
      const cached = templateCacheRef.current.get(template.id);
      if (cached) templateCacheRef.current.set(template.id, { ...cached, detail: { ...cached.detail, is_favorite: favorite } });
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '收藏操作失败' : 'Favorite action failed'), 'error');
    }
  }, [showToast, zh]);

  const resetEditorForm = useCallback(() => {
    setCreateForm({
      name: '', vendor: 'Cisco', platform: 'cisco_iosxe', category: 'interface',
      description: '', software_version: '', usage_notes: '', risk_notes: '',
      content: zh
        ? '! 自定义配置模板\n! 使用 {{ description | default("example") }} 定义带默认值的参数\n'
        : '! Custom configuration template\n! Use {{ description | default("example") }} for a parameter with a default\n',
      rollback: '', example_values: '{}', variable_schema: [],
    });
  }, [zh]);

  const openTemplateEditor = useCallback((template?: ConfigTemplate | TemplateDetail) => {
    const selected = template as TemplateDetail | undefined;
    const schema = selected?.variable_schema
      || parseJson<TemplateVariable[]>(selected?.variable_schema_json, []);
    const examples = selected?.example_values
      || parseJson<Record<string, unknown>>(selected?.example_values_json, {});
    const currentDetail = detailRef.current;
    const source = selected?.id === currentDetail?.id
      ? sourceContentRef.current
      : (selected?.version?.source || selected?.content || '');
    setEditingTemplateId(selected?.id || null);
    setCreateForm({
      name: selected?.name || '',
      vendor: selected?.vendor || 'Cisco',
      platform: selected?.platform_family || 'cisco_iosxe',
      category: selected?.category || 'interface',
      description: selected?.description || '',
      software_version: selected?.software_version || '',
      usage_notes: selected?.usage_notes || '',
      risk_notes: selected?.risk_notes || '',
      content: source || (zh ? '! 请在此输入配置命令\n' : '! Enter configuration commands here\n'),
      rollback: selected?.rollback || selected?.version?.rollback_source || '',
      example_values: JSON.stringify(examples, null, 2),
      variable_schema: schema,
    });
    setShowCreate(true);
  }, [zh]);

  const updateEditorVariable = useCallback((index: number, patch: Partial<TemplateVariable>) => {
    setCreateForm((current) => ({
      ...current,
      variable_schema: current.variable_schema.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item),
    }));
  }, []);

  const saveTemplateEditor = useCallback(async () => {
    if (!createForm.name.trim() || !createForm.content.trim()) return;
    let exampleValues: Record<string, unknown>;
    try {
      const parsed = JSON.parse(createForm.example_values || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Example values must be a JSON object');
      exampleValues = parsed as Record<string, unknown>;
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '示例值 JSON 格式错误' : 'Example values must be valid JSON'), 'error');
      return;
    }
    setCreatingTemplate(true);
    try {
      const payload = {
        name: createForm.name.trim(),
        type: 'Jinja2',
        category: createForm.category,
        vendor: createForm.vendor,
        platform_family: createForm.platform,
        software_version: createForm.software_version,
        description: createForm.description,
        usage_notes: createForm.usage_notes,
        risk_notes: createForm.risk_notes,
        content: createForm.content,
        rollback: createForm.rollback,
        variable_schema: createForm.variable_schema,
        example_values: exampleValues,
      };
      const result = await apiRequest<{ id?: string; success: boolean }>(
        editingTemplateId ? `/api/config-templates/${encodeURIComponent(editingTemplateId)}` : '/api/config-templates',
        { method: editingTemplateId ? 'PUT' : 'POST', body: JSON.stringify(payload) },
      );
      const items = await refreshTemplates();
      const targetId = result.id || editingTemplateId || '';
      if (targetId) templateCacheRef.current.delete(targetId);
      setShowCreate(false);
      setEditingTemplateId(null);
      if (targetId && items.some((item) => item.id === targetId)) {
        selectTemplate(targetId);
        await loadTemplate(targetId, true);
      }
      showToast(editingTemplateId ? (zh ? '自定义模板已更新，字段和示例已同步' : 'Custom template updated') : (zh ? '自定义模板已创建，字段和示例已生成' : 'Custom template created'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '模板保存失败' : 'Failed to save template'), 'error');
    } finally {
      setCreatingTemplate(false);
    }
  }, [createForm, editingTemplateId, loadTemplate, refreshTemplates, selectTemplate, showToast, zh]);

  const deleteTemplate = useCallback(async (template: ConfigTemplate) => {
    if (template.is_official || template.source_type === 'official') {
      showToast(zh ? '内置模板不可删除，请先复制为自定义模板' : 'Official templates are read-only; copy one first', 'warning');
      return;
    }
    if (!window.confirm(zh ? `确定归档自定义模板“${template.name}”吗？归档后不会再出现在模板库中。` : `Archive custom template "${template.name}"? It will be hidden from the library.`)) return;
    try {
      await apiRequest(`/api/config-templates/${encodeURIComponent(template.id)}`, { method: 'DELETE' });
      templateCacheRef.current.delete(template.id);
      const items = await refreshTemplates();
      if (activeTemplateIdRef.current === template.id) {
        setDetail(null);
        const next = items[0];
        if (next) selectTemplate(next.id);
      }
      showToast(zh ? '模板已归档' : 'Template archived', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '模板删除失败' : 'Failed to archive template'), 'error');
    }
  }, [refreshTemplates, selectTemplate, showToast, zh]);

  const copyTemplate = useCallback(async (template: ConfigTemplate) => {
    try {
      const result = await apiRequest<{ id: string }>(`/api/config-templates/${encodeURIComponent(template.id)}/copy`, { method: 'POST' });
      const items = await refreshTemplates();
      const copied = items.find((item) => item.id === result.id);
      if (copied) {
        selectTemplate(copied.id);
        await loadTemplate(copied.id);
      }
      showToast(zh ? `已复制“${template.name}”，现在可以编辑自定义副本` : `Copied “${template.name}” as an editable custom template`, 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '复制模板失败' : 'Failed to copy template'), 'error');
    }
  }, [loadTemplate, refreshTemplates, selectTemplate, showToast, zh]);

  const saveSource = useCallback(async () => {
    if (!detail?.id || !sourceContent.trim()) return;
    setSourceSaving(true);
    try {
      await apiRequest(`/api/config-templates/${encodeURIComponent(detail.id)}`, {
        method: 'PUT',
        body: JSON.stringify({
          ...detail,
          content: sourceContent,
          lastUsed: detail.lastUsed,
        }),
      });
      setSourceDirty(false);
      try { window.localStorage.removeItem(draftStorageKey(detail.id)); } catch { /* best effort */ }
      await refreshTemplates();
      templateCacheRef.current.delete(detail.id);
      await loadTemplate(detail.id, true);
      showToast(zh ? '模板源码已保存，审核状态已重置为草稿' : 'Template saved and review status reset to draft', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '模板保存失败' : 'Failed to save template'), 'error');
    } finally {
      setSourceSaving(false);
    }
  }, [detail, loadTemplate, refreshTemplates, showToast, sourceContent, zh]);

  const importTemplate = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const raw = JSON.parse(await file.text());
      const result = await apiRequest<{ id: string }>('/api/config-templates/import', {
        method: 'POST',
        body: JSON.stringify({
          template: raw.template || raw,
          version: raw.template?.version || raw.version || {},
          expected_checksum: raw.checksum || '',
        }),
      });
      await refreshTemplates();
      selectTemplate(result.id);
      showToast(zh ? '模板导入成功并已按自定义草稿处理' : 'Template imported as a custom draft', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '模板导入失败' : 'Failed to import template'), 'error');
    }
  }, [refreshTemplates, selectTemplate, showToast, zh]);

  const exportTemplate = useCallback(async () => {
    if (!detail?.id) return;
    try {
      const response = await fetch(`/api/config-templates/${encodeURIComponent(detail.id)}/export`, { headers: authHeaders() });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      downloadText(await response.text(), `${safeFileName(detail.name)}.template.json`, 'application/json;charset=utf-8');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '模板导出失败' : 'Failed to export template'), 'error');
    }
  }, [detail, showToast, zh]);

  const createTaskDraft = useCallback(async () => {
    if (!detail?.id || !lastSuccessfulResult?.success) return;
    setTaskCreating(true);
    try {
      const result = await apiRequest<{ redirect_path: string; message: string }>('/api/automation/tasks/from-template', {
        method: 'POST',
        body: JSON.stringify({
          template_id: detail.id,
          version: detail.current_version || '1.0',
          parameters,
          parameter_profile_id: selectedProfileId,
          options: { strict: true, trim_blank_lines: true, include_source_map: true },
          device_ids: [],
        }),
      });
      showToast(result.message || (zh ? '任务草稿已创建' : 'Task draft created'), 'success');
      navigate(result.redirect_path);
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '任务草稿创建失败' : 'Failed to create task draft'), 'error');
    } finally {
      setTaskCreating(false);
    }
  }, [detail, lastSuccessfulResult?.success, navigate, parameters, selectedProfileId, showToast, zh]);

  const loadVersionDiff = useCallback(async () => {
    if (!detail?.id || !versionFrom || !versionTo) return;
    setVersionDiffLoading(true);
    try {
      const result = await apiRequest<{ diff: string[] }>(
        `/api/config-templates/${encodeURIComponent(detail.id)}/versions/diff?from_version=${encodeURIComponent(versionFrom)}&to_version=${encodeURIComponent(versionTo)}`,
      );
      setVersionDiff(result.diff || []);
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '版本差异加载失败' : 'Failed to load version diff'), 'error');
    } finally {
      setVersionDiffLoading(false);
    }
  }, [detail?.id, showToast, versionFrom, versionTo, zh]);

  useEffect(() => {
    if (previewTab === 'versions' && versionFrom && versionTo) void loadVersionDiff();
  }, [loadVersionDiff, previewTab, versionFrom, versionTo]);

  const startResize = useCallback((target: 'left' | 'parameters', event: React.MouseEvent) => {
    event.preventDefault();
    const startX = event.clientX;
    const initial = target === 'left' ? leftWidth : parameterWidth;
    const move = (moveEvent: MouseEvent) => {
      const next = initial + moveEvent.clientX - startX;
      if (target === 'left') setLeftWidth(Math.max(260, Math.min(430, next)));
      else setParameterWidth(Math.max(340, Math.min(520, next)));
    };
    const stop = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', stop);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', stop);
  }, [leftWidth, parameterWidth]);

  const visibleRender = renderResult?.success ? renderResult : lastSuccessfulResult;
  const safePreviewOutput = useMemo(() => {
    let output = visibleRender?.rendered_output || '';
    const secretValues = schema
      .filter(isSensitiveVariable)
      .map((item) => String(effectiveParameterValue(item) || ''))
      .filter((value) => value.length >= 3)
      .sort((left, right) => right.length - left.length);
    secretValues.forEach((value) => {
      output = output.split(value).join('••••••••');
    });
    return output;
  }, [effectiveParameterValue, schema, visibleRender?.rendered_output]);
  const safeParameterValues = useMemo(() => {
    const sensitiveNames = new Set(schema.filter(isSensitiveVariable).map((item) => item.name));
    return Object.fromEntries(
      Object.entries(parameters).map(([name, value]) => [name, sensitiveNames.has(name) && hasParameterValue(value) ? '***' : value]),
    );
  }, [parameters, schema]);
  const effectiveParameterSources = useMemo(() => ({
    ...(renderResult?.parameter_validation?.sources || {}),
    ...parameterSources,
  }), [parameterSources, renderResult?.parameter_validation?.sources]);
  const warningCount = renderResult?.warnings.length || 0;
  const errorCount = renderResult?.errors.length || 0;
  const highRisk = ['high', 'critical'].includes(visibleRender?.risk_level || 'none');
  const requiresReviewAcknowledgement = warningCount > 0 || highRisk;
  const workflowStep = !detail
    ? 1
    : completedRequired < requiredVariables.length
      ? 2
      : !visibleRender?.success || errorCount > 0 || (requiresReviewAcknowledgement && !reviewAcknowledged)
        ? 3
        : 4;
  const canCreateTask = Boolean(
    lastSuccessfulResult?.success
    && !taskCreating
    && errorCount === 0
    && (!requiresReviewAcknowledgement || reviewAcknowledged),
  );
  const taskBlockedReason = !lastSuccessfulResult?.success
    ? (zh ? '请先完成参数并生成有效配置' : 'Complete the parameters and generate a valid configuration')
    : errorCount > 0
      ? (zh ? `仍有 ${errorCount} 个错误需要处理` : `${errorCount} errors still need attention`)
      : requiresReviewAcknowledgement && !reviewAcknowledged
        ? (zh ? '请先查看并确认警告或高风险命令' : 'Review and acknowledge warnings or high-risk commands first')
        : '';
  const workflowSteps = [
    { number: 1, title: zh ? '选择模板' : 'Select', detail: detail?.name || (zh ? '从模板库开始' : 'Choose from the library') },
    { number: 2, title: zh ? '填写参数' : 'Parameters', detail: `${completedRequired}/${requiredVariables.length} ${zh ? '个必填已完成' : 'required complete'}` },
    { number: 3, title: zh ? '检查配置' : 'Review', detail: errorCount > 0 ? `${errorCount} ${zh ? '个错误' : 'errors'}` : warningCount > 0 ? `${warningCount} ${zh ? '条警告待确认' : 'warnings to review'}` : (zh ? '语法、风险与回滚' : 'Syntax, risk, and rollback') },
    { number: 4, title: zh ? '创建任务' : 'Create task', detail: workflowStep === 4 ? (zh ? '可以进入任务中心' : 'Ready for Automation') : (zh ? '完成检查后继续' : 'Available after review') },
  ];
  const previewLines = useMemo(() => {
    const lines = safePreviewOutput.split('\n');
    const search = previewSearch.trim().toLowerCase();
    if (!search) return lines.map((content, index) => ({ content, number: index + 1 }));
    return lines
      .map((content, index) => ({ content, number: index + 1 }))
      .filter((line) => line.content.toLowerCase().includes(search));
  }, [previewSearch, safePreviewOutput]);

  const renderPreviewContent = useCallback((line: string, lineNumber: number) => {
    const maps = visibleRender?.source_map.filter((item) => item.output_line === lineNumber && item.value) || [];
    if (maps.length === 0) return line;
    const values = maps.slice().sort((a, b) => b.value.length - a.value.length);
    const pattern = new RegExp(`(${values.map((item) => item.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
    return line.split(pattern).map((part, index) => {
      const source = values.find((item) => item.value === part);
      return source
        ? (
          <span
            key={`${lineNumber}-${index}`}
            title={`${zh ? '变量' : 'Variable'}: ${source.variable}\n${zh ? '来源' : 'Source'}: ${SOURCE_LABELS[source.source] || source.source}\n${zh ? '当前值' : 'Value'}: ${source.value}`}
            className="rounded bg-cyan-400/20 px-0.5 text-cyan-200 underline decoration-cyan-500/40 decoration-dotted underline-offset-2"
          >
            {part}
          </span>
        )
        : <React.Fragment key={`${lineNumber}-${index}`}>{part}</React.Fragment>;
    });
  }, [visibleRender?.source_map, zh]);

  const renderVariableInput = (item: TemplateVariable) => {
    const value = effectiveParameterValue(item);
    const sensitive = isSensitiveVariable(item);
    const commonProps = {
      value: String(value),
      onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => updateParameter(item.name, event.target.value),
      className: `${fieldClass} ${fieldErrors.has(item.name) ? 'border-rose-400 ring-2 ring-rose-100' : ''}`,
      placeholder: item.placeholder || (item.example_value !== undefined ? String(item.example_value) : ''),
    };
    if (sensitive) {
      const revealed = Boolean(revealedSecrets[item.name]);
      return (
        <div className="relative">
          <input
            {...commonProps}
            type={revealed ? 'text' : 'password'}
            autoComplete="new-password"
            className={`${commonProps.className} pr-10`}
          />
          <button
            type="button"
            onClick={() => setRevealedSecrets((current) => ({ ...current, [item.name]: !revealed }))}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label={revealed ? (zh ? '隐藏敏感值' : 'Hide secret') : (zh ? '显示敏感值' : 'Show secret')}
            title={revealed ? (zh ? '隐藏敏感值' : 'Hide secret') : (zh ? '显示敏感值' : 'Show secret')}
          >
            {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      );
    }
    if (item.type === 'boolean') {
      return (
        <button
          type="button"
          onClick={() => updateParameter(item.name, !(value === true || value === 'true'))}
          className={`relative h-6 w-11 rounded-full transition ${value === true || value === 'true' ? 'bg-cyan-600' : 'bg-slate-300'}`}
        >
          <span className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition ${value === true || value === 'true' ? 'left-6' : 'left-1'}`} />
        </button>
      );
    }
    if (item.type === 'select') {
      return (
        <select {...commonProps}>
          <option value="">{zh ? '请选择' : 'Select'}</option>
          {(item.options || []).map((option) => {
            const optionValue = typeof option === 'string' ? option : option.value;
            const label = typeof option === 'string' ? option : (option.label || option.value);
            return <option key={optionValue} value={optionValue}>{label}</option>;
          })}
        </select>
      );
    }
    if (item.type === 'multi_select') {
      const selected = Array.isArray(parameters[item.name]) ? parameters[item.name] as unknown[] : String(value).split(',').filter(Boolean);
      return (
        <select
          multiple
          value={selected.map(String)}
          onChange={(event) => updateParameter(item.name, Array.from(event.target.selectedOptions).map((option) => option.value))}
          className={`${fieldClass} min-h-24`}
        >
          {(item.options || []).map((option) => {
            const optionValue = typeof option === 'string' ? option : option.value;
            const label = typeof option === 'string' ? option : (option.label || option.value);
            return <option key={optionValue} value={optionValue}>{label}</option>;
          })}
        </select>
      );
    }
    if (item.type === 'text' && item.allow_multiline === false) {
      return <input {...commonProps} type="text" autoComplete="off" />;
    }
    if (['text', 'list', 'object', 'command_block'].includes(item.type)) {
      return <textarea {...commonProps} rows={item.type === 'text' ? 3 : 2} />;
    }
    return (
      <input
        {...commonProps}
        type={item.type === 'password' ? 'password' : ['integer', 'vlan_id'].includes(item.type) ? 'number' : 'text'}
        min={item.type === 'vlan_id' ? 1 : undefined}
        max={item.type === 'vlan_id' ? 4094 : undefined}
        autoComplete={item.type === 'password' ? 'new-password' : undefined}
      />
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-50">
      <PageHero
        icon={FileCog}
        title={zh ? '配置模板中心' : 'Configuration Template Center'}
        subtitle={zh ? '多厂商网络配置模板、结构化参数填写与实时命令生成' : 'Multi-vendor templates, structured parameters, and real-time command generation'}
        actions={(
          <>
            <input ref={importRef} type="file" accept=".json" className="hidden" onChange={(event) => void importTemplate(event)} />
            <button type="button" onClick={() => importRef.current?.click()} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-600 shadow-sm hover:border-cyan-300 hover:text-cyan-700">
              <Import size={14} /> {zh ? '导入模板' : 'Import'}
            </button>
            <button type="button" onClick={() => { resetEditorForm(); setEditingTemplateId(null); setShowCreate(true); }} className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 px-4 py-2 text-xs font-black text-white shadow-lg shadow-cyan-200">
              <Plus size={14} /> {zh ? '新建模板' : 'New template'}
            </button>
          </>
        )}
      />

      <div className="shrink-0 px-5 pt-2">
        <div className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 shadow-sm">
          <div className="grid grid-cols-2 gap-1 lg:grid-cols-4">
            {workflowSteps.map((step, index) => {
              const active = workflowStep === step.number;
              const complete = workflowStep > step.number;
              return (
                <div key={step.number} className="relative flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1">
                  <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-black ${complete ? 'bg-emerald-100 text-emerald-700' : active ? 'bg-cyan-600 text-white shadow-sm shadow-cyan-200' : 'bg-slate-100 text-slate-400'}`}>
                    {complete ? <Check size={11} /> : step.number}
                  </span>
                  <div className="min-w-0">
                    <p className={`text-[11px] font-black ${active ? 'text-cyan-800' : complete ? 'text-emerald-700' : 'text-slate-600'}`}>{step.title}</p>
                    <p className="truncate text-[9px] text-slate-400">{step.detail}</p>
                  </div>
                  {index < workflowSteps.length - 1 && <ChevronRight size={11} className="absolute -right-1 hidden text-slate-300 lg:block" />}
                </div>
              );
            })}
          </div>
          <div className="mt-0.5 flex min-h-5 flex-wrap items-center gap-1.5 border-t border-slate-100 pt-1 text-[9px] text-slate-500">
            <span>{templates.length} {zh ? '个模板' : 'templates'}</span>
            <span>·</span>
            <span>{schema.length} {zh ? '个参数' : 'parameters'}，{availableDefaultCount} {zh ? '个使用模板默认值' : 'using defaults'}</span>
            <span>·</span>
            <button type="button" onClick={() => setPreviewTab('checks')} className={`${warningCount > 0 ? 'font-bold text-amber-700 hover:text-amber-800' : 'text-slate-500'}`}>
              {errorCount > 0 ? `${errorCount} ${zh ? '个错误' : 'errors'}` : warningCount > 0 ? `${warningCount} ${zh ? '条警告' : 'warnings'}` : (zh ? '校验正常' : 'Validation clear')}
            </button>
            <span className="ml-auto">{zh ? '模板质量' : 'Quality'} {detail?.quality?.score ?? detail?.quality_score ?? 0}</span>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-0 overflow-hidden p-5 pt-4">
        <aside
          className={`relative flex min-h-0 shrink-0 flex-col overflow-hidden rounded-l-2xl border border-slate-200 bg-white shadow-sm transition-all ${leftCollapsed ? 'w-12' : ''}`}
          style={leftCollapsed ? undefined : { width: leftWidth }}
        >
          {leftCollapsed ? (
            <button type="button" onClick={() => setLeftCollapsed(false)} className="flex h-full flex-col items-center gap-3 py-4 text-slate-400 hover:text-cyan-700">
              <ChevronRight size={16} />
              <Layers size={16} />
              <span className="vertical-text text-[10px] font-bold">{zh ? '模板库' : 'Templates'}</span>
            </button>
          ) : (
            <>
              <div className="shrink-0 border-b border-slate-100 p-3">
                <div className="flex items-center gap-2">
                  <Layers size={14} className="text-cyan-600" />
                  <h2 className="flex-1 text-xs font-black text-slate-800">{zh ? '模板库' : 'Template library'}</h2>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-bold text-slate-500">{filteredTemplates.length}</span>
                  <button type="button" onClick={() => setLeftCollapsed(true)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"><ChevronLeft size={13} /></button>
                </div>
                <div className="relative mt-3">
                  <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder={zh ? '名称、描述、厂商、平台、命令…' : 'Name, vendor, platform, commands…'} className={`${fieldClass} pl-9`} />
                </div>
                <div className="mt-2 grid grid-cols-2 gap-1.5">
                  <select value={vendorFilter} onChange={(event) => setVendorFilter(event.target.value)} className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-[10px] font-semibold text-slate-600 outline-none focus:border-cyan-300">
                    <option value="all">{zh ? '全部厂商' : 'All vendors'}</option>
                    {vendorOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                  <select value={platformFilter} onChange={(event) => setPlatformFilter(event.target.value)} className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-[10px] font-semibold text-slate-600 outline-none focus:border-cyan-300">
                    <option value="all">{zh ? '全部平台' : 'All platforms'}</option>
                    {platformOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <button type="button" onClick={() => setAdvancedFiltersOpen((value) => !value)} className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] font-bold ${advancedFiltersOpen || activeFilterCount > 0 ? 'border-cyan-200 bg-cyan-50 text-cyan-700' : 'border-slate-200 text-slate-500'}`}>
                    <Filter size={11} />{zh ? '高级筛选' : 'More filters'}{activeFilterCount > 0 && <span className="rounded-full bg-cyan-600 px-1.5 text-[8px] text-white">{activeFilterCount}</span>}
                  </button>
                  {(activeFilterCount > 0 || sortBy !== 'updated') && <button type="button" onClick={clearFilters} className="text-[10px] font-bold text-slate-400 hover:text-rose-600">{zh ? '清空' : 'Clear'}</button>}
                  <span className="ml-auto text-[10px] text-slate-400">{filteredTemplates.length}/{templates.length}</span>
                </div>
                {advancedFiltersOpen && (
                  <div className="mt-2 grid grid-cols-2 gap-1.5 rounded-xl border border-slate-100 bg-slate-50/70 p-2">
                    <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)} className="min-w-0 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-slate-600"><option value="all">{zh ? '全部场景' : 'All scenarios'}</option>{distinct('category').map((option) => <option key={option} value={option}>{option}</option>)}</select>
                    <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} className="min-w-0 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-slate-600"><option value="all">{zh ? '全部来源' : 'All sources'}</option>{['official', 'custom', 'team', 'mine'].map((option) => <option key={option} value={option}>{option}</option>)}</select>
                    <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="min-w-0 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-slate-600"><option value="all">{zh ? '全部状态' : 'All statuses'}</option>{['published', 'draft', 'review', 'archived'].map((option) => <option key={option} value={option}>{option}</option>)}</select>
                    <select value={sortBy} onChange={(event) => setSortBy(event.target.value as typeof sortBy)} className="min-w-0 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-slate-600"><option value="updated">{zh ? '最近更新' : 'Recently updated'}</option><option value="name">{zh ? '名称' : 'Name'}</option><option value="usage">{zh ? '使用次数' : 'Usage'}</option><option value="quality">{zh ? '质量' : 'Quality'}</option></select>
                  </div>
                )}
              </div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2.5">
                {filteredTemplates.length === 0 ? (
                  <div className="py-12 text-center">
                    <Filter size={24} className="mx-auto text-slate-200" />
                    <p className="mt-2 text-[10px] text-slate-400">{zh ? '没有匹配模板' : 'No matching templates'}</p>
                  </div>
                ) : filteredTemplates.map((template) => (
                  <TemplateLibraryCard
                    key={template.id}
                    template={template}
                    selected={template.id === selectedTemplateId}
                    zh={zh}
                    onSelect={selectTemplate}
                    onFavorite={toggleFavorite}
                    onEdit={openTemplateEditor}
                    onArchive={deleteTemplate}
                    onCopy={copyTemplate}
                  />
                ))}
              </div>
            </>
          )}
          {!leftCollapsed && <div onMouseDown={(event) => startResize('left', event)} className="absolute bottom-0 right-0 top-0 z-10 w-1 cursor-col-resize hover:bg-cyan-300" />}
        </aside>

        <section className="relative flex min-h-0 shrink-0 flex-col overflow-hidden border-y border-slate-200 bg-white" style={{ width: parameterWidth }}>
          <div className="shrink-0 border-b border-slate-100 p-3">
            <div className="flex items-start gap-3">
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-xs font-black text-white ${VENDOR_STYLE[detail?.vendor || 'Custom']?.gradient || VENDOR_STYLE.Custom.gradient}`}>
                {(detail?.vendor || 'NA').slice(0, 2).toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-sm font-black text-slate-800">{detail?.name || (zh ? '请选择模板' : 'Select a template')}</h2>
                <p className="mt-0.5 text-[9px] text-slate-400">
                  {zh ? '版本' : 'Version'} v{detail?.current_version || '—'} · {zh ? '必填' : 'required'} {requiredVariables.length}
                </p>
              </div>
              {detailLoading && <Loader2 size={14} className="animate-spin text-cyan-600" />}
            </div>
            {detail && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button type="button" onClick={() => void copyTemplate(detail)} className="rounded-lg border border-violet-200 bg-violet-50 px-2 py-1 text-[10px] font-bold text-violet-700 hover:bg-violet-100"><Copy size={11} className="mr-1 inline" />{zh ? '复制为自定义' : 'Copy as custom'}</button>
                {!detail.is_official && detail.source_type !== 'official' && <button type="button" onClick={() => openTemplateEditor(detail)} className="rounded-lg border border-cyan-200 bg-cyan-50 px-2 py-1 text-[10px] font-bold text-cyan-700 hover:bg-cyan-100"><Pencil size={11} className="mr-1 inline" />{zh ? '编辑模板' : 'Edit template'}</button>}
                <button type="button" onClick={loadExamples} className="rounded-lg border border-slate-200 px-2 py-1 text-[10px] font-bold text-slate-600 hover:border-cyan-200 hover:text-cyan-700"><Sparkles size={11} className="mr-1 inline" />{zh ? '加载示例' : 'Example'}</button>
                {availableDefaultCount > 0 && <button type="button" onClick={applyTemplateDefaults} className="rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700 hover:bg-emerald-100"><Check size={11} className="mr-1 inline" />{zh ? `应用默认值 (${availableDefaultCount})` : `Apply defaults (${availableDefaultCount})`}</button>}
                <button type="button" onClick={resetParameters} className="rounded-lg border border-slate-200 px-2 py-1 text-[10px] font-bold text-slate-600 hover:border-cyan-200 hover:text-cyan-700"><RefreshCw size={11} className="mr-1 inline" />{zh ? '重置参数' : 'Reset'}</button>
                <button type="button" onClick={() => void runRender(true)} className="rounded-lg bg-slate-900 px-2 py-1 text-[10px] font-bold text-white"><WandSparkles size={11} className="mr-1 inline" />{zh ? '刷新预览' : 'Refresh preview'}</button>
              </div>
            )}
          </div>

          {detail ? (
            <>
              <div className="shrink-0 border-b border-slate-100 bg-slate-50 p-3">
                <button type="button" onClick={() => setProfileExpanded((value) => !value)} className="flex w-full items-center gap-2 text-left">
                  <ChevronDown size={12} className={`text-slate-400 transition ${profileExpanded ? '' : '-rotate-90'}`} />
                  <span className="text-[10px] font-black text-slate-600">{zh ? '参数方案' : 'Parameter profile'}</span>
                  <span className="ml-auto max-w-48 truncate text-[10px] text-slate-400">
                    {profiles.find((profile) => profile.id === selectedProfileId)?.name || (zh ? '可选：保存并复用一组参数' : 'Optional: save and reuse values')}
                  </span>
                </button>
                {profileExpanded && (
                  <div className="mt-2">
                    <div className="flex gap-1.5">
                      <select value={selectedProfileId} onChange={(event) => loadProfile(event.target.value)} className={`${fieldClass} min-w-0 flex-1`}>
                        <option value="">{zh ? '未使用参数方案' : 'No profile'}</option>
                        {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · v{profile.template_version}</option>)}
                      </select>
                      <button type="button" disabled={!selectedProfileId} onClick={() => void deleteProfile()} className="rounded-xl border border-slate-200 p-2 text-slate-400 hover:border-rose-200 hover:text-rose-600 disabled:opacity-30" title={zh ? '删除参数方案' : 'Delete profile'}><Trash2 size={13} /></button>
                    </div>
                    <div className="mt-1.5 flex gap-1.5">
                      <input value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder={zh ? '输入方案名称后保存当前参数' : 'Profile name'} className={`${fieldClass} min-w-0 flex-1`} />
                      <button type="button" disabled={!profileName.trim() || savingProfile} onClick={() => void saveProfile()} className="inline-flex items-center gap-1 rounded-xl bg-cyan-600 px-3 text-[10px] font-bold text-white disabled:opacity-40">
                        {savingProfile ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />} {zh ? '保存' : 'Save'}
                      </button>
                    </div>
                    <p className="mt-1.5 text-[9px] leading-4 text-slate-400">{zh ? '敏感参数不会保存明文，加载方案后需要重新输入。' : 'Secret values are never stored in plain text and must be re-entered.'}</p>
                  </div>
                )}
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                <div className="mb-3 grid grid-cols-4 gap-1.5 rounded-xl bg-slate-50 p-2 text-center">
                  {[
                    [zh ? '总数' : 'Total', schema.length],
                    [zh ? '必填' : 'Required', requiredVariables.length],
                    [zh ? '已填写' : 'Filled', filledParameterCount],
                    [zh ? '未完成' : 'Missing', Math.max(0, requiredVariables.length - completedRequired)],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <p className="text-sm font-black text-slate-700">{value}</p>
                      <p className="text-[9px] text-slate-400">{label}</p>
                    </div>
                  ))}
                </div>

                {(detail.compatibility || []).length > 0 && (
                  <div className="mb-3 rounded-xl border border-cyan-100 bg-cyan-50/50 p-3">
                    <div className="flex items-center gap-1.5 text-[10px] font-black text-cyan-800">
                      <Layers size={12} /> {zh ? '平台与型号系列适配' : 'Platform and model/series compatibility'}
                    </div>
                    <p className="mt-1 text-[9px] leading-4 text-cyan-700">
                      {zh ? '平台表示命令行/操作系统方言；型号和系列仅用于兼容性预检，不会被误当成新的平台。' : 'Platform means the CLI/OS dialect; model and series are used for compatibility pre-checks, not as new platforms.'}
                    </p>
                    <div className="mt-2 space-y-1.5">
                      {(detail.compatibility || []).map((item, index) => (
                        <div key={`${String(item.platform || '')}-${index}`} className="flex flex-wrap items-center gap-1.5 text-[8px] text-slate-600">
                          <span className="rounded bg-white px-1.5 py-0.5 font-bold text-cyan-700">{String(item.vendor || detail.vendor || '')}</span>
                          <code className="rounded bg-white px-1.5 py-0.5 text-slate-500">{String(item.platform || detail.platform_family || '')}</code>
                          {item.model_pattern && <span className="truncate rounded bg-white px-1.5 py-0.5" title={zh ? '适用型号/系列' : 'Supported model/series'}>{zh ? '型号/系列' : 'Model/series'}: {formatModelPattern(item.model_pattern)}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {groupedSchema.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center">
                    <FileJson size={24} className="mx-auto text-slate-200" />
                    <p className="mt-2 text-[10px] text-slate-400">{zh ? '当前模板没有参数' : 'This template has no parameters'}</p>
                  </div>
                ) : groupedSchema.map(([group, items]) => {
                  const collapsed = groupCollapsed[group];
                  const errorCount = items.filter((item) => fieldErrors.has(item.name)).length;
                  return (
                    <div key={group} className="mb-3 overflow-hidden rounded-xl border border-slate-200">
                      <button type="button" onClick={() => setGroupCollapsed((current) => ({ ...current, [group]: !collapsed }))} className="flex w-full items-center gap-2 bg-slate-50 px-3 py-2 text-left">
                        <ChevronDown size={12} className={`text-slate-400 transition ${collapsed ? '-rotate-90' : ''}`} />
                        <span className="flex-1 text-[10px] font-black text-slate-700">{group}</span>
                        {errorCount > 0 && <span className="rounded-full bg-rose-100 px-1.5 py-0.5 text-[8px] font-bold text-rose-700">{errorCount}</span>}
                        <span className="text-[8px] text-slate-400">{items.length}</span>
                      </button>
                      {!collapsed && (
                        <div className="space-y-3 p-3">
                          {items.map((item) => {
                            const source = effectiveParameterSources[item.name] || (hasParameterValue(item.default_value) ? 'template_default' : '');
                            return (
                              <label key={item.name} className="block">
                                <div className="mb-1.5 flex items-center gap-2">
                                  <span className="text-[11px] font-bold text-slate-700">{item.label || item.name}</span>
                                  {item.required ? <span className="text-[9px] font-black text-rose-500">*</span> : <span className="text-[8px] text-slate-400">{zh ? '可选' : 'optional'}</span>}
                                  <code className="ml-auto text-[9px] text-slate-400">{parameterTypeLabel(item.type, zh)}</code>
                                </div>
                                {renderVariableInput(item)}
                                <div className="mt-1 flex items-start gap-2">
                                  {fieldErrors.has(item.name) ? (
                                    <p className="flex-1 text-[10px] leading-4 text-rose-600">{fieldErrors.get(item.name)}</p>
                                  ) : (
                                    <p className="flex-1 text-[10px] leading-4 text-slate-400">{item.description || item.placeholder || ''}</p>
                                  )}
                                  {source && <span className="shrink-0 rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] font-bold text-cyan-700">{sourceLabel(source, zh)}</span>}
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}

                {(detail.usage_notes || detail.risk_notes || detail.official_reference) && (
                  <div className="space-y-2 rounded-xl border border-blue-100 bg-blue-50/40 p-3">
                    <p className="flex items-center gap-1.5 text-[10px] font-black text-blue-800"><BookOpen size={12} /> {zh ? '模板说明' : 'Template guidance'}</p>
                    {detail.usage_notes && <p className="text-[9px] leading-4 text-slate-600">{detail.usage_notes}</p>}
                    {detail.risk_notes && <p className="text-[9px] leading-4 text-amber-700"><ShieldAlert size={10} className="mr-1 inline" />{detail.risk_notes}</p>}
                    {detail.official_reference && <a href={detail.official_reference} target="_blank" rel="noreferrer" className="block truncate text-[9px] font-bold text-blue-700 underline">{zh ? '查看厂商官方参考' : 'Official vendor reference'}</a>}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-6 text-center text-xs text-slate-400">{zh ? '请从左侧选择一个配置模板' : 'Select a template from the left'}</div>
          )}
          <div onMouseDown={(event) => startResize('parameters', event)} className="absolute bottom-0 right-0 top-0 z-10 w-1 cursor-col-resize hover:bg-cyan-300" />
        </section>

        <section className={`${fullscreen ? 'fixed inset-4 z-50 rounded-2xl shadow-2xl' : 'min-w-[520px] flex-1 rounded-r-2xl'} flex min-h-0 min-w-0 flex-col overflow-hidden border border-slate-200 bg-white shadow-sm`}>
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2">
            <div className="flex rounded-lg bg-slate-100 p-1">
              {PREVIEW_TABS.map((tab) => (
                <button type="button" key={tab.id} onClick={() => setPreviewTab(tab.id)} className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[9px] font-bold transition ${previewTab === tab.id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>
                  {tab.icon}{zh ? tab.zh : tab.en}
                  {tab.id === 'checks' && renderResult && (renderResult.errors.length + renderResult.warnings.length > 0) && <span className="rounded-full bg-amber-100 px-1 text-[8px] text-amber-700">{renderResult.errors.length + renderResult.warnings.length}</span>}
                </button>
              ))}
            </div>
            <div className="ml-auto flex items-center gap-1.5">
              {previewTab === 'preview' && (
                <>
                  <div className="relative hidden xl:block">
                    <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input value={previewSearch} onChange={(event) => setPreviewSearch(event.target.value)} placeholder={zh ? '搜索命令' : 'Search output'} className="w-32 rounded-lg border border-slate-200 py-1.5 pl-7 pr-2 text-[9px] outline-none focus:border-cyan-300" />
                  </div>
                  <button type="button" onClick={() => setWrapPreview((value) => !value)} className={`rounded-lg border p-1.5 ${wrapPreview ? 'border-cyan-200 bg-cyan-50 text-cyan-700' : 'border-slate-200 text-slate-500'}`} title={zh ? '自动换行' : 'Wrap'}><WrapText size={12} /></button>
                  <button type="button" disabled={!safePreviewOutput} onClick={() => {
                    void copyText(safePreviewOutput)
                      .then(() => showToast(t('copied'), 'success'))
                      .catch(() => showToast(zh ? '复制失败，请手动选择文本复制' : 'Copy failed; select the text manually', 'error'));
                  }} className="rounded-lg border border-slate-200 p-1.5 text-slate-500 disabled:opacity-30" title={zh ? '复制全部' : 'Copy all'}><Copy size={12} /></button>
                  <button type="button" disabled={!safePreviewOutput} onClick={() => {
                    downloadText(safePreviewOutput, `${safeFileName(detail?.name || 'config')}.txt`);
                    showToast(zh ? '已下载 TXT 配置' : 'TXT configuration downloaded', 'success');
                  }} className="rounded-lg border border-slate-200 p-1.5 text-slate-500 disabled:opacity-30" title="TXT" aria-label={zh ? '下载 TXT 配置' : 'Download TXT'}><Download size={12} /></button>
                  <button type="button" disabled={!safePreviewOutput} onClick={() => {
                    downloadText(safePreviewOutput, `${safeFileName(detail?.name || 'config')}.cfg`);
                    showToast(zh ? '已下载 CFG 配置' : 'CFG configuration downloaded', 'success');
                  }} className="rounded-lg border border-slate-200 px-2 py-1 text-[8px] font-bold text-slate-500 disabled:opacity-30" aria-label={zh ? '下载 CFG 配置' : 'Download CFG'}>CFG</button>
                </>
              )}
              <button type="button" onClick={() => setFullscreen((value) => !value)} className="rounded-lg border border-slate-200 p-1.5 text-slate-500">{fullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}</button>
            </div>
          </div>

          <div className={`flex shrink-0 items-center gap-3 border-b px-4 py-2 ${errorCount > 0 ? 'border-rose-100 bg-rose-50/60' : warningCount > 0 ? 'border-amber-100 bg-amber-50/60' : 'border-slate-100 bg-slate-50'}`}>
            {renderState === 'rendering' ? <Loader2 size={13} className="animate-spin text-cyan-600" /> : renderState === 'success' ? <CheckCircle2 size={13} className="text-emerald-600" /> : renderState === 'warning' ? <AlertTriangle size={13} className="text-amber-600" /> : renderState === 'error' ? <AlertCircle size={13} className="text-rose-600" /> : <Code2 size={13} className="text-slate-400" />}
            <button type="button" onClick={() => (errorCount > 0 || warningCount > 0) && setPreviewTab('checks')} className={`text-left text-[10px] font-bold ${errorCount > 0 ? 'text-rose-700' : warningCount > 0 ? 'text-amber-700' : 'text-slate-600'}`}>
              {renderState === 'rendering' ? (zh ? '参数已变化，正在实时渲染…' : 'Rendering parameter changes…') : renderState === 'success' ? (zh ? '渲染成功' : 'Rendered successfully') : renderState === 'warning' ? (zh ? '渲染成功，但存在警告' : 'Rendered with warnings') : renderState === 'error' ? (zh ? '渲染失败，已保留上一次成功结果' : 'Render failed; previous result retained') : (zh ? '等待参数输入' : 'Waiting for parameters')}
              {(errorCount > 0 || warningCount > 0) && <span className="ml-1 font-normal underline decoration-dotted">{zh ? '查看详情' : 'View details'}</span>}
            </button>
            {visibleRender && <span className="text-[9px] text-slate-400">{visibleRender.line_count} {zh ? '行' : 'lines'} · {visibleRender.used_variables.length} {zh ? '个参数' : 'variables'} · {visibleRender.defaulted_variables.length} {zh ? '个默认值' : 'defaults'}</span>}
            <span className={`ml-auto rounded-full px-2 py-0.5 text-[8px] font-black uppercase ${visibleRender?.risk_level === 'critical' ? 'bg-rose-100 text-rose-700' : visibleRender?.risk_level === 'high' ? 'bg-orange-100 text-orange-700' : 'bg-emerald-100 text-emerald-700'}`}>
              {zh ? '风险' : 'Risk'} {riskLabel(visibleRender?.risk_level, zh)}
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-hidden">
            {previewTab === 'preview' && (
              <div ref={previewScrollRef} className="h-full overflow-auto bg-[#0b1220] py-3 font-mono text-[11px] leading-5 text-slate-300">
                {!detail ? (
                  <EmptyState icon={Layers} title={zh ? '请从左侧选择一个配置模板' : 'Select a template'} />
                ) : !safePreviewOutput ? (
                  <EmptyState icon={WandSparkles} title={requiredVariables.length > completedRequired ? (zh ? `请先完成 ${requiredVariables.length - completedRequired} 个必填参数` : `Complete ${requiredVariables.length - completedRequired} required parameters`) : (zh ? '模板尚未生成命令，请检查条件表达式' : 'No commands generated')} />
                ) : previewLines.map((line) => (
                  <div key={line.number} className="flex min-w-max px-3 hover:bg-white/[0.035]">
                    <span className="w-12 shrink-0 select-none pr-3 text-right text-slate-600">{line.number}</span>
                    <code className={`${wrapPreview ? 'whitespace-pre-wrap break-all' : 'whitespace-pre'} min-w-0 flex-1 pr-4`}>{renderPreviewContent(line.content, line.number)}</code>
                  </div>
                ))}
              </div>
            )}

            {previewTab === 'source' && (
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex shrink-0 items-center gap-2 border-b border-slate-100 bg-amber-50 px-3 py-2 text-[9px] text-amber-800">
                  <AlertTriangle size={11} />
                  <span className="flex-1">{zh ? '编辑模板源码会重置官方审核状态；保存后请重新校验并发布新版本。' : 'Editing source resets review status; validate and publish a new version after saving.'}</span>
                  <button type="button" onClick={() => void exportTemplate()} className="rounded-lg border border-amber-200 bg-white px-2 py-1 font-bold"><Upload size={10} className="mr-1 inline" />{zh ? '导出' : 'Export'}</button>
                  <button type="button" disabled={!sourceDirty || sourceSaving} onClick={() => void saveSource()} className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-2 py-1 font-bold text-white disabled:opacity-30">
                    {sourceSaving ? <Loader2 size={10} className="animate-spin" /> : <Save size={10} />}{zh ? '保存源码' : 'Save'}
                  </button>
                </div>
                <textarea value={sourceContent} onChange={(event) => {
                  const nextSource = event.target.value;
                  setSourceContent(nextSource);
                  setSourceDirty(true);
                  if (detail?.id) {
                    try { window.localStorage.setItem(draftStorageKey(detail.id), JSON.stringify({ parameters, source: nextSource })); } catch { /* best effort */ }
                  }
                }} spellCheck={false} className="min-h-0 flex-1 resize-none bg-[#0b1220] p-5 font-mono text-xs leading-6 text-slate-300 outline-none" />
              </div>
            )}

            {previewTab === 'json' && (
              <div className="h-full overflow-auto bg-[#0b1220] p-5">
                <pre className="whitespace-pre-wrap font-mono text-xs leading-6 text-cyan-100">{JSON.stringify({
                  template_id: detail?.id || null,
                  template_version: detail?.current_version || null,
                  parameter_profile_id: selectedProfileId || null,
                  parameters: safeParameterValues,
                  parameter_sources: effectiveParameterSources,
                }, null, 2)}</pre>
              </div>
            )}

            {previewTab === 'checks' && (
              <div className="h-full space-y-4 overflow-y-auto bg-slate-50 p-4">
                <ValidationSection
                  title={zh ? '阻断错误' : 'Blocking errors'}
                  items={renderResult?.errors || []}
                  tone="error"
                  empty={zh ? '没有阻断错误' : 'No blocking errors'}
                />
                <ValidationSection
                  title={zh ? '警告与提示' : 'Warnings and advisories'}
                  items={renderResult?.warnings || []}
                  tone="warning"
                  empty={zh ? '没有额外警告' : 'No warnings'}
                />
                {visibleRender && visibleRender.risk_items.length > 0 && (
                  <ValidationSection
                    title={zh ? '高风险命令' : 'Risky commands'}
                    items={visibleRender.risk_items.map((item) => ({ ...item, message: `${zh ? '第' : 'Line'} ${item.line}: ${item.message} — ${item.command}` }))}
                    tone="error"
                    empty=""
                  />
                )}
                <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
                  <p className="text-xs font-black text-blue-800">{zh ? '流程边界' : 'Workflow boundary'}</p>
                  <p className="mt-1 text-[10px] leading-5 text-blue-700">
                    {zh ? '模板中心只负责参数校验、命令预览、静态检查和创建任务草稿，不会登录设备或直接下发。设备选择、审批、MFA、执行、验证与回滚在任务中心完成。' : 'This center validates, previews, checks, and creates drafts only. Device selection, approval, MFA, execution, verification, and rollback happen in Automation.'}
                  </p>
                </div>
              </div>
            )}

            {previewTab === 'versions' && (
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex shrink-0 items-center gap-2 border-b border-slate-100 p-3">
                  <select value={versionFrom} onChange={(event) => setVersionFrom(event.target.value)} className={`${fieldClass} max-w-40`}>
                    {(detail?.versions || []).map((version) => <option key={version.version} value={version.version}>A · v{version.version}</option>)}
                  </select>
                  <ChevronRight size={14} className="text-slate-400" />
                  <select value={versionTo} onChange={(event) => setVersionTo(event.target.value)} className={`${fieldClass} max-w-40`}>
                    {(detail?.versions || []).map((version) => <option key={version.version} value={version.version}>B · v{version.version}</option>)}
                  </select>
                  <button type="button" onClick={() => void loadVersionDiff()} className="rounded-xl bg-slate-900 px-3 py-2 text-[9px] font-bold text-white">{zh ? '刷新差异' : 'Refresh diff'}</button>
                </div>
                <div className="min-h-0 flex-1 overflow-auto bg-[#0b1220] p-4 font-mono text-[10px] leading-5">
                  {versionDiffLoading ? (
                    <Loader2 size={20} className="mx-auto mt-16 animate-spin text-cyan-500" />
                  ) : versionDiff.length === 0 ? (
                    <p className="mt-16 text-center text-slate-500">{zh ? '两个版本没有源码差异，或当前只有一个版本。' : 'No source differences, or only one version exists.'}</p>
                  ) : versionDiff.map((line, index) => (
                    <div key={`${index}-${line}`} className={`whitespace-pre px-2 ${line.startsWith('+') && !line.startsWith('+++') ? 'bg-emerald-500/10 text-emerald-300' : line.startsWith('-') && !line.startsWith('---') ? 'bg-rose-500/10 text-rose-300' : line.startsWith('@@') ? 'text-cyan-400' : 'text-slate-400'}`}>{line}</div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-slate-100 bg-white px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{zh ? '下一步' : 'Next step'}</p>
              {requiresReviewAcknowledgement ? (
                <label className="mt-1 flex cursor-pointer items-start gap-2 text-[10px] leading-4 text-slate-600">
                  <input type="checkbox" checked={reviewAcknowledged} onChange={(event) => setReviewAcknowledged(event.target.checked)} className="mt-0.5 accent-cyan-600" />
                  <span>{zh ? `我已查看并确认 ${warningCount > 0 ? `${warningCount} 条警告` : '高风险命令'}` : `I reviewed and acknowledge ${warningCount > 0 ? `${warningCount} warning(s)` : 'high-risk commands'}`}</span>
                </label>
              ) : (
                <p className="truncate text-[10px] text-slate-600">{zh ? '将当前模板、版本、参数和校验摘要带入任务中心' : 'Send the template, version, parameters, and validation summary to Automation'}</p>
              )}
              {!canCreateTask && taskBlockedReason && <p className="mt-1 truncate text-[10px] text-amber-700">{taskBlockedReason}</p>}
            </div>
            <button type="button" disabled={!canCreateTask} title={taskBlockedReason || undefined} onClick={() => void createTaskDraft()} className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 px-4 py-2 text-xs font-black text-white shadow-lg shadow-cyan-200 disabled:cursor-not-allowed disabled:opacity-40">
              {taskCreating ? <Loader2 size={14} className="animate-spin" /> : <ClipboardList size={14} />}
              {zh ? '基于当前结果创建任务' : 'Create task from result'}
            </button>
          </div>
        </section>
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm">
          <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-white/40 bg-white shadow-2xl">
            <div className="flex shrink-0 items-center gap-3 border-b border-slate-100 p-5">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-50 text-cyan-700">{editingTemplateId ? <Pencil size={17} /> : <Plus size={18} />}</span>
              <div className="flex-1"><h3 className="text-sm font-black text-slate-800">{editingTemplateId ? (zh ? '编辑自定义模板' : 'Edit custom template') : (zh ? '新建自定义模板' : 'New custom template')}</h3><p className="text-[10px] text-slate-400">{zh ? '保存后自动解析字段、生成示例上下文并执行 Jinja2 语法校验；内置模板不可直接修改。' : 'Saving infers fields, builds the example context, and validates Jinja2 syntax; built-in templates stay read-only.'}</p></div>
              <button type="button" onClick={() => setShowCreate(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={15} /></button>
            </div>
            <div className="min-h-0 overflow-y-auto p-5">
              <div className="grid grid-cols-2 gap-3">
                <label className="col-span-2 space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '模板名称' : 'Name'} *</span><input value={createForm.name} onChange={(event) => setCreateForm((current) => ({ ...current, name: event.target.value }))} className={fieldClass} autoFocus /></label>
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '厂商' : 'Vendor'}</span><select value={createForm.vendor} onChange={(event) => setCreateForm((current) => ({ ...current, vendor: event.target.value, platform: CONFIG_VENDOR_PLATFORM_OPTIONS[event.target.value]?.[0]?.value || 'custom' }))} className={fieldClass}>{CONFIG_VENDOR_OPTIONS.map((value) => <option key={value}>{value}</option>)}</select></label>
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '平台/系统' : 'Platform'}</span><select value={createForm.platform} onChange={(event) => setCreateForm((current) => ({ ...current, platform: event.target.value }))} className={fieldClass}>{(CONFIG_VENDOR_PLATFORM_OPTIONS[createForm.vendor] || CONFIG_VENDOR_PLATFORM_OPTIONS.Custom).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '配置场景' : 'Scenario'}</span><select value={createForm.category} onChange={(event) => setCreateForm((current) => ({ ...current, category: event.target.value }))} className={fieldClass}>{['vlan', 'interface', 'routing', 'ospf', 'bgp', 'acl', 'qos', 'snmp', 'ntp', 'aaa', 'security', 'system', 'other'].map((value) => <option key={value}>{value}</option>)}</select></label>
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '软件版本范围' : 'Software version'}</span><input value={createForm.software_version} onChange={(event) => setCreateForm((current) => ({ ...current, software_version: event.target.value }))} placeholder="例如 V300R019 / 17.x" className={fieldClass} /></label>
                <label className="col-span-2 space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '模板说明' : 'Description'}</span><textarea value={createForm.description} onChange={(event) => setCreateForm((current) => ({ ...current, description: event.target.value }))} rows={2} className={fieldClass} /></label>
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '使用说明' : 'Usage notes'}</span><textarea value={createForm.usage_notes} onChange={(event) => setCreateForm((current) => ({ ...current, usage_notes: event.target.value }))} rows={3} className={fieldClass} placeholder="说明进入模式、前置条件和适用型号" /></label>
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '风险说明' : 'Risk notes'}</span><textarea value={createForm.risk_notes} onChange={(event) => setCreateForm((current) => ({ ...current, risk_notes: event.target.value }))} rows={3} className={fieldClass} placeholder="说明可能影响业务的命令和回滚要求" /></label>
              </div>
              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? 'Jinja2 配置源' : 'Jinja2 source'} *</span><textarea value={createForm.content} onChange={(event) => setCreateForm((current) => ({ ...current, content: event.target.value }))} rows={12} spellCheck={false} className="w-full resize-y rounded-xl border border-slate-200 bg-[#0b1220] px-3 py-2 font-mono text-[11px] leading-5 text-cyan-100 outline-none focus:border-cyan-400" /></label>
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '回滚源（可选）' : 'Rollback source (optional)'}</span><textarea value={createForm.rollback} onChange={(event) => setCreateForm((current) => ({ ...current, rollback: event.target.value }))} rows={12} spellCheck={false} className="w-full resize-y rounded-xl border border-slate-200 bg-[#0b1220] px-3 py-2 font-mono text-[11px] leading-5 text-rose-100 outline-none focus:border-cyan-400" /></label>
              </div>
              <div className="mt-3 rounded-xl border border-cyan-100 bg-cyan-50 p-3 text-[10px] leading-5 text-cyan-800"><p className="font-black">{zh ? '格式要求' : 'Format rules'}</p><p>{zh ? '参数使用小写蛇形命名，例如 ' : 'Use lower snake_case parameter names, for example '}<code className="rounded bg-white px-1">{'{{ vlan_id | default(100) }}'}</code>{zh ? '。字段会从源代码自动识别；示例值必须是 JSON 对象，供预览和校验使用。危险命令请填写回滚源。' : '. Fields are inferred from source; example values must be a JSON object for preview and validation. Add rollback for risky commands.'}</p></div>
              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1.2fr]">
                <label className="space-y-1.5"><span className="text-[10px] font-bold text-slate-500">{zh ? '示例值 JSON' : 'Example values JSON'}</span><textarea value={createForm.example_values} onChange={(event) => setCreateForm((current) => ({ ...current, example_values: event.target.value }))} rows={8} spellCheck={false} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-[11px] leading-5 text-slate-700 outline-none focus:border-cyan-400" placeholder={'{\n  "vlan_id": 100\n}'} /></label>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-center gap-2"><span className="flex-1 text-[10px] font-black text-slate-600">{zh ? '字段定义（可选）' : 'Field definitions (optional)'}</span><button type="button" onClick={() => setCreateForm((current) => ({ ...current, variable_schema: [...current.variable_schema, { name: `variable_${current.variable_schema.length + 1}`, label: '', type: 'string', required: false, description: '', example_value: '' }] }))} className="inline-flex items-center gap-1 rounded-lg border border-cyan-200 bg-white px-2 py-1 text-[9px] font-bold text-cyan-700"><Plus size={11} />{zh ? '添加字段' : 'Add field'}</button></div><p className="mt-1 text-[9px] leading-4 text-slate-400">{zh ? '只保留源代码实际使用的字段；标签、类型、必填和示例会覆盖自动推断。' : 'Only source-used fields are kept; label, type, required, and example override inference.'}</p><div className="mt-2 max-h-72 space-y-2 overflow-y-auto">{createForm.variable_schema.length === 0 ? <p className="rounded-lg border border-dashed border-slate-200 px-3 py-5 text-center text-[10px] text-slate-400">{zh ? '保存时将根据 Jinja2 源码自动生成字段' : 'Fields will be inferred from Jinja2 source when saved'}</p> : createForm.variable_schema.map((item, index) => (<div key={`${item.name}-${index}`} className="rounded-lg border border-slate-200 bg-white p-2"><div className="grid grid-cols-12 gap-1.5"><input value={item.name} onChange={(event) => updateEditorVariable(index, { name: event.target.value })} className="col-span-3 rounded-lg border border-slate-200 px-2 py-1.5 text-[10px]" placeholder="name" /><input value={item.label || ''} onChange={(event) => updateEditorVariable(index, { label: event.target.value })} className="col-span-3 rounded-lg border border-slate-200 px-2 py-1.5 text-[10px]" placeholder={zh ? '显示名称' : 'Label'} /><select value={item.type || 'string'} onChange={(event) => updateEditorVariable(index, { type: event.target.value })} className="col-span-3 rounded-lg border border-slate-200 px-2 py-1.5 text-[10px]"><option value="string">{zh ? '文本' : 'Text'}</option><option value="integer">{zh ? '整数' : 'Integer'}</option><option value="ipv4_address">IPv4</option><option value="ipv4_netmask">{zh ? '子网掩码' : 'Netmask'}</option><option value="vlan_id">VLAN ID</option><option value="interface">{zh ? '接口' : 'Interface'}</option><option value="password">{zh ? '敏感值' : 'Secret'}</option></select><label className="col-span-2 flex items-center justify-center gap-1 rounded-lg border border-slate-200 px-1 text-[9px] text-slate-500"><input type="checkbox" checked={Boolean(item.required)} onChange={(event) => updateEditorVariable(index, { required: event.target.checked })} />{zh ? '必填' : 'Req.'}</label><button type="button" onClick={() => setCreateForm((current) => ({ ...current, variable_schema: current.variable_schema.filter((_, itemIndex) => itemIndex !== index) }))} className="col-span-1 rounded-lg border border-rose-100 text-rose-500 hover:bg-rose-50"><Trash2 size={11} className="mx-auto" /></button><input value={item.example_value === undefined || item.example_value === null ? '' : String(item.example_value)} onChange={(event) => updateEditorVariable(index, { example_value: event.target.value })} className="col-span-4 rounded-lg border border-slate-200 px-2 py-1.5 text-[10px]" placeholder={zh ? '示例值' : 'Example'} /><input value={item.description || ''} onChange={(event) => updateEditorVariable(index, { description: event.target.value })} className="col-span-8 rounded-lg border border-slate-200 px-2 py-1.5 text-[10px]" placeholder={zh ? '字段说明和格式要求' : 'Description and format requirements'} /></div></div>))}</div></div>
              </div>
            </div>
            <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-white p-4"><button type="button" onClick={() => setShowCreate(false)} className="rounded-xl border border-slate-200 px-4 py-2 text-xs font-bold text-slate-600">{zh ? '取消' : 'Cancel'}</button><button type="button" disabled={!createForm.name.trim() || !createForm.content.trim() || creatingTemplate} onClick={() => void saveTemplateEditor()} className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2 text-xs font-black text-white disabled:opacity-40">{creatingTemplate ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}{editingTemplateId ? (zh ? '保存模板' : 'Save template') : (zh ? '创建草稿' : 'Create draft')}</button></div>
          </div>
        </div>
      )}
    </div>
  );
};

const EmptyState: React.FC<{ icon: React.ElementType; title: string }> = ({ icon: Icon, title }) => (
  <div className="flex h-full min-h-64 flex-col items-center justify-center text-center">
    <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/5 text-slate-600"><Icon size={24} /></span>
    <p className="mt-3 text-xs font-bold text-slate-500">{title}</p>
  </div>
);

const ValidationSection: React.FC<{
  title: string;
  items: RenderIssue[];
  tone: 'error' | 'warning';
  empty: string;
}> = ({ title, items, tone, empty }) => (
  <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
    <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
      {tone === 'error' ? <AlertCircle size={14} className="text-rose-600" /> : <AlertTriangle size={14} className="text-amber-600" />}
      <h3 className="flex-1 text-xs font-black text-slate-700">{title}</h3>
      <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${tone === 'error' ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-700'}`}>{items.length}</span>
    </div>
    <div className="space-y-2 p-4">
      {items.length === 0 ? (
        <p className="flex items-center gap-2 text-[10px] text-emerald-700"><CheckCircle2 size={12} />{empty}</p>
      ) : items.map((item, index) => (
        <div key={`${item.code}-${index}`} className={`rounded-lg px-3 py-2 text-[10px] leading-5 ${tone === 'error' ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-800'}`}>
          {item.line ? `L${item.line} · ` : ''}{item.message}
        </div>
      ))}
    </div>
  </section>
);

export default PlatformSettingsTab;
