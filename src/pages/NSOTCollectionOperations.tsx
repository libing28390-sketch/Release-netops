import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle, CircleHelp, Copy, Database, LoaderCircle,
  Pencil, Plus, RotateCcw, Save, ShieldAlert, Terminal, Trash2, X,
} from 'lucide-react';
import {
  TEXTFSM_VERSION_LABELS,
  TEXTFSM_VENDOR_OPTIONS,
  getEditorSelection,
  getPlatformFamilyOption,
  getVendorOption,
} from './textfsmPlatformCatalog';
import Pagination from '../components/Pagination';

interface CollectionTemplate {
  id: string;
  name_zh?: string;
  name_en?: string;
  description_zh?: string;
  description_en?: string;
  collector_keys?: string[];
  condition?: string | null;
  note?: string | null;
  builtin?: boolean;
  editable?: boolean;
  deletable?: boolean;
}

interface OperationProfile {
  id: string;
  platform_code: string;
  platform_name?: string | null;
  platform_family?: string | null;
  parser_platform?: string | null;
  current_release_id?: string | null;
  release_number?: string | null;
  name_zh?: string | null;
  name_en?: string | null;
  vendor?: string | null;
  catalog_vendor?: string | null;
  version?: string | null;
  status?: string | null;
  source?: string | null;
}

interface OperationCommand {
  action_code?: string | null;
  command?: string | null;
  command_source?: string | null;
  textfsm_template?: string | null;
  textfsm_source?: string | null;
  status?: string | null;
  condition?: string | null;
}

interface CollectionOperation {
  collector_key: string;
  quick_ops_category: string | null;
  label: string;
  label_zh?: string;
  label_en?: string;
  transport: string;
  applicable_templates: string[];
  action_code: string | null;
  action_bound: boolean;
  commands: OperationCommand[];
  status?: string | null;
  condition?: string | null;
  conditional?: boolean;
}

interface OperationCatalog {
  templates: CollectionTemplate[];
  profiles: OperationProfile[];
  selected_profile: OperationProfile | null;
  operations: CollectionOperation[];
}

type CatalogError = Error & { status?: number; permissionDenied?: boolean };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const optionalText = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim() ? value.trim() : undefined;

const parseTemplate = (value: unknown): CollectionTemplate | null => {
  if (!isRecord(value)) return null;
  const id = optionalText(value.id);
  if (!id) return null;
  const collectorKeys = Array.isArray(value.collector_keys)
    ? value.collector_keys.filter((item): item is string => typeof item === 'string')
    : undefined;
  return {
    id,
    name_zh: optionalText(value.name_zh),
    name_en: optionalText(value.name_en),
    description_zh: optionalText(value.description_zh),
    description_en: optionalText(value.description_en),
    collector_keys: collectorKeys,
    condition: optionalText(value.condition),
    note: optionalText(value.note),
    builtin: value.builtin === true,
    editable: value.editable !== false,
    deletable: value.deletable !== false,
  };
};

const parseProfile = (value: unknown): OperationProfile | null => {
  if (!isRecord(value)) return null;
  const id = optionalText(value.id);
  const platformCode = optionalText(value.platform_code);
  if (!id || !platformCode) return null;
  return {
    id,
    platform_code: platformCode,
    platform_name: optionalText(value.platform_name),
    platform_family: optionalText(value.platform_family),
    parser_platform: optionalText(value.parser_platform),
    current_release_id: optionalText(value.current_release_id),
    release_number: optionalText(String(value.registry_release_number ?? value.release_number ?? '')),
    name_zh: optionalText(value.name_zh),
    name_en: optionalText(value.name_en),
    vendor: optionalText(value.vendor),
    catalog_vendor: optionalText(value.catalog_vendor),
    version: optionalText(value.version),
    status: optionalText(value.status),
    source: optionalText(value.source),
  };
};

const parseCommand = (value: unknown): OperationCommand | null => {
  if (!isRecord(value)) return null;
  return {
    action_code: optionalText(value.action_code) ?? null,
    command: optionalText(value.command) ?? null,
    command_source: optionalText(value.command_source) ?? null,
    textfsm_template: optionalText(value.textfsm_template) ?? null,
    textfsm_source: optionalText(value.textfsm_source) ?? null,
    status: optionalText(value.status) ?? null,
    condition: optionalText(value.condition) ?? null,
  };
};

const parseOperation = (value: unknown): CollectionOperation | null => {
  if (!isRecord(value)) return null;
  const collectorKey = optionalText(value.collector_key);
  const label = optionalText(value.label) || optionalText(value.label_zh) || collectorKey;
  if (!collectorKey || !label) return null;
  const applicableTemplates = Array.isArray(value.applicable_templates)
    ? value.applicable_templates.filter((item): item is string => typeof item === 'string')
    : [];
  const commands = Array.isArray(value.commands)
    ? value.commands.flatMap((item): OperationCommand[] => {
      const parsed = parseCommand(item);
      return parsed ? [parsed] : [];
    })
    : [];
  return {
    collector_key: collectorKey,
    quick_ops_category: optionalText(value.quick_ops_category) ?? null,
    label,
    label_zh: optionalText(value.label_zh),
    label_en: optionalText(value.label_en),
    transport: optionalText(value.transport) || '—',
    applicable_templates: applicableTemplates,
    action_code: optionalText(value.action_code) ?? null,
    action_bound: value.action_bound === true,
    commands,
    status: optionalText(value.status) ?? null,
    condition: optionalText(value.condition) ?? null,
    conditional: value.conditional === true,
  };
};

const parseCatalog = (payload: unknown): OperationCatalog | null => {
  if (!isRecord(payload)) return null;
  const body = payload;
  const data = isRecord(body.data) ? body.data : body;
  if (body.success === false || !Array.isArray(data.templates) || !Array.isArray(data.profiles) || !Array.isArray(data.operations)) return null;
  const templates = data.templates.flatMap((item): CollectionTemplate[] => {
    const parsed = parseTemplate(item);
    return parsed ? [parsed] : [];
  });
  const profiles = data.profiles.flatMap((item): OperationProfile[] => {
    const parsed = parseProfile(item);
    return parsed && String(parsed.status || 'ACTIVE').toUpperCase() !== 'ARCHIVED' ? [parsed] : [];
  });
  const operations = data.operations.flatMap((item): CollectionOperation[] => {
    const parsed = parseOperation(item);
    return parsed ? [parsed] : [];
  });
  const selectedProfile = data.selected_profile === null ? null : parseProfile(data.selected_profile);
  return { templates, profiles, selected_profile: selectedProfile, operations };
};

const safeBackendDetail = (payload: unknown): string | undefined => {
  if (!isRecord(payload)) return undefined;
  const detail = typeof payload.detail === 'string' ? payload.detail : payload.message;
  if (typeof detail !== 'string') return undefined;
  const normalized = detail.replace(/[\r\n\t]+/g, ' ').trim();
  return normalized && normalized.length <= 240 ? normalized : undefined;
};

const makeCatalogError = (status: number, payload: unknown, zh: boolean): CatalogError => {
  const permissionDenied = status === 401 || status === 403;
  const message = permissionDenied
    ? (zh ? '当前账号无权查看 NSOT 采集目录，或登录状态已失效。' : 'You are not authorized to view the NSOT collection catalog, or your session has expired.')
    : status >= 500
      ? (zh ? `服务暂时不可用（HTTP ${status}），请稍后重试。` : `The service is temporarily unavailable (HTTP ${status}). Please try again later.`)
      : safeBackendDetail(payload) || (zh ? `目录请求失败（HTTP ${status}）。` : `Catalog request failed (HTTP ${status}).`);
  const error = new Error(message) as CatalogError;
  error.status = status;
  error.permissionDenied = permissionDenied;
  return error;
};

const authHeaders = (): HeadersInit => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const templateLabel = (template: CollectionTemplate, zh: boolean): string =>
  (zh ? template.name_zh : template.name_en) || template.name_zh || template.name_en || template.id;

const profileDetails = (profile: OperationProfile, zh: boolean) => {
  const selection = getEditorSelection(profile.platform_code, profile.version || undefined);
  const family = getPlatformFamilyOption(profile.platform_family || selection.platformFamily);
  const vendorKey = family?.vendor || selection.vendor || profile.vendor || profile.catalog_vendor || '';
  const vendor = vendorKey ? getVendorOption(vendorKey) : undefined;
  const version = String(selection.version || 'common').toLowerCase();
  const versionMeta = TEXTFSM_VERSION_LABELS[version];
  const vendorLabel = vendor ? (zh ? vendor.label : vendor.labelEn) : profile.vendor || profile.catalog_vendor || selection.vendor;
  const familyLabel = family ? (zh ? family.label : family.labelEn) : (zh ? profile.name_zh : profile.name_en) || profile.platform_name || profile.platform_code;
  const versionLabel = version !== 'common' && versionMeta ? (zh ? versionMeta.label : versionMeta.labelEn) : '';
  return { vendor: vendorLabel, platform: [familyLabel, versionLabel].filter(Boolean).join(' ') };
};

const normalizeVendorKey = (value: string | null | undefined): string => {
  const normalized = String(value || '').trim().toLocaleLowerCase();
  if (!normalized) return '';
  const knownVendor = TEXTFSM_VENDOR_OPTIONS.find((vendor) => (
    [vendor.value, vendor.label, vendor.labelEn].some((label) => label.toLocaleLowerCase() === normalized)
  ));
  return knownVendor?.value || normalized;
};

const profileVendorKey = (profile: OperationProfile): string => {
  const selection = getEditorSelection(profile.platform_code, profile.version || undefined);
  const family = getPlatformFamilyOption(profile.platform_family || selection.platformFamily);
  return normalizeVendorKey(family?.vendor || selection.vendor || profile.vendor || profile.catalog_vendor);
};

const profileLabel = (profile: OperationProfile, zh: boolean): string => {
  const details = profileDetails(profile, zh);
  const localized = (zh ? profile.name_zh : profile.name_en) || profile.name_zh || profile.name_en;
  if (localized && !getPlatformFamilyOption(profile.platform_family || getEditorSelection(profile.platform_code, profile.version || undefined).platformFamily)) return localized;
  return `${details.vendor} ${details.platform}`;
};

const isUnsupported = (operation: CollectionOperation, command?: OperationCommand): boolean =>
  [operation.status, command?.status].some((status) => String(status || '').toLowerCase() === 'unsupported');

const isConditional = (operation: CollectionOperation, command?: OperationCommand): boolean =>
  operation.conditional === true
  || Boolean(operation.condition || command?.condition)
  || [operation.status, command?.status].some((status) => ['conditional', 'pending_condition'].includes(String(status || '').toLowerCase()));

// These are database-derived facts, not user-facing CLI collection operations.
// They remain available to the collection engine and IPAM/CMDB views, but do
// not belong in this compact command directory.
const HIDDEN_DERIVED_COLLECTORS = new Set(['endpoint_location', 'prefix_projection']);

const templateOperationsFor = (template: CollectionTemplate, operations: CollectionOperation[]) =>
  operations.filter((operation) => {
    if (HIDDEN_DERIVED_COLLECTORS.has(operation.collector_key)) return false;
    return template.collector_keys?.length
      ? template.collector_keys.includes(operation.collector_key)
      : operation.applicable_templates.includes(template.id);
  });

interface NSOTCollectionOperationsProps {
  language: string;
  searchText: string;
  platformFilter?: string;
}

interface CollectionTemplateForm {
  name_zh: string;
  name_en: string;
  description_zh: string;
  description_en: string;
  collector_keys: string[];
}

const NSOTCollectionOperations: React.FC<NSOTCollectionOperationsProps> = ({ language, searchText, platformFilter = 'All' }) => {
  const zh = language === 'zh';
  const [catalog, setCatalog] = useState<OperationCatalog | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [detailTemplateId, setDetailTemplateId] = useState('');
  const [detailVendorKey, setDetailVendorKey] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<CatalogError | null>(null);
  const [templateActionError, setTemplateActionError] = useState('');
  const [templateEditorOpen, setTemplateEditorOpen] = useState(false);
  const [templateEditorMode, setTemplateEditorMode] = useState<'create' | 'edit'>('create');
  const [templateEditorId, setTemplateEditorId] = useState('');
  const [templateForm, setTemplateForm] = useState<CollectionTemplateForm>({
    name_zh: '',
    name_en: '',
    description_zh: '',
    description_en: '',
    collector_keys: [],
  });
  const [templateSaving, setTemplateSaving] = useState(false);
  const [templateDeleting, setTemplateDeleting] = useState(false);
  const [templateEditorError, setTemplateEditorError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);

  useEffect(() => {
    if (!detailTemplateId) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDetailTemplateId('');
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [detailTemplateId]);

  const loadCatalog = useCallback(async (profileId?: string) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestSequence = ++requestSequenceRef.current;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (profileId) params.set('platform_profile_id', profileId);
      const query = params.toString();
      const response = await fetch(`/api/collection-plans/operation-catalog${query ? `?${query}` : ''}`, {
        headers: authHeaders(),
        signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) throw makeCatalogError(response.status, payload, zh);
      const parsed = parseCatalog(payload);
      if (!parsed) throw new Error(zh ? '服务器返回了无法识别的操作目录数据。' : 'The server returned an invalid operation catalog.');
      if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;

      setCatalog(parsed);
      const resolvedProfileId = parsed.selected_profile?.id || profileId || '';
      setSelectedProfileId(resolvedProfileId);
    } catch (caught) {
      if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;
      setError(caught instanceof Error
        ? caught as CatalogError
        : new Error(zh ? '加载操作目录失败。' : 'Failed to load the operation catalog.'));
    } finally {
      if (!controller.signal.aborted && requestSequence === requestSequenceRef.current) setLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    void loadCatalog();
    return () => controllerRef.current?.abort();
  }, [loadCatalog]);

  const profileOptions = useMemo(() => {
    if (!catalog || platformFilter === 'Linux') return [];
    const candidates = platformFilter === 'All'
      ? catalog.profiles
      : catalog.profiles.filter((profile) => {
        const selectionVendor = getEditorSelection(profile.platform_code, profile.version || undefined).vendor.toLowerCase();
        const normalizedFilter = platformFilter.toLowerCase();
        const filterOption = getVendorOption(platformFilter);
        const profileVendorNames = [profile.vendor, profile.catalog_vendor].filter(Boolean).map((vendor) => String(vendor).trim().toLowerCase());
        const filterNames = [normalizedFilter, filterOption?.label, filterOption?.labelEn]
          .filter(Boolean)
          .map((vendor) => String(vendor).trim().toLowerCase());
        return selectionVendor === normalizedFilter || profileVendorNames.some((vendor) => filterNames.includes(vendor));
      });
    return [...candidates].sort((left, right) => {
      const leftDetails = profileDetails(left, zh);
      const rightDetails = profileDetails(right, zh);
      const locale = zh ? 'zh-CN' : 'en';
      return (leftDetails.vendor || '').localeCompare(rightDetails.vendor || '', locale)
        || leftDetails.platform.localeCompare(rightDetails.platform, locale, { numeric: true })
        || left.platform_code.localeCompare(right.platform_code, undefined, { numeric: true })
        || (left.release_number || '').localeCompare(right.release_number || '', undefined, { numeric: true })
        || left.id.localeCompare(right.id);
    });
  }, [catalog, platformFilter, zh]);

  const selectedProfile = profileOptions.find((profile) => profile.id === selectedProfileId) || null;
  const selectedProfileDetails = selectedProfile ? profileDetails(selectedProfile, zh) : null;
  const filteredVendor = platformFilter !== 'All' ? getVendorOption(platformFilter) : undefined;
  const commandVendorLabel = selectedProfileDetails?.vendor
    || (filteredVendor ? (zh ? filteredVendor.label : filteredVendor.labelEn) : (zh ? '多厂商' : 'Multiple vendors'));
  const commandPlatformLabel = selectedProfileDetails?.platform || (zh ? '未选择平台' : 'No platform selected');
  const profileVendorCount = new Set(profileOptions.map((profile) => profileDetails(profile, zh).vendor).filter(Boolean)).size;

  useEffect(() => {
    if (!catalog || !selectedProfileId || profileOptions.some((profile) => profile.id === selectedProfileId)) return;
    setSelectedProfileId('');
    setCatalog((current) => current ? { ...current, operations: [], selected_profile: null } : current);
    void loadCatalog();
  }, [catalog, loadCatalog, profileOptions, selectedProfileId]);

  const templateCollectorOptions = useMemo(() => {
    if (!catalog) return [];
    const seen = new Set<string>();
    return catalog.operations
      .filter((operation) => !HIDDEN_DERIVED_COLLECTORS.has(operation.collector_key))
      .filter((operation) => {
        if (seen.has(operation.collector_key)) return false;
        seen.add(operation.collector_key);
        return true;
      })
      .map((operation) => ({
        key: operation.collector_key,
        label: (zh ? operation.label_zh : operation.label_en) || operation.label,
      }));
  }, [catalog, zh]);

  const openTemplateEditor = (mode: 'create' | 'edit', target?: CollectionTemplate, clone = false) => {
    setTemplateActionError('');
    setTemplateEditorMode(mode);
    setTemplateEditorId(target?.id || '');
    const cloneName = (value: string, suffix: string) => `${value.slice(0, 128 - suffix.length)}${suffix}`;
    const sourceNameZh = target?.name_zh || target?.name_en || target?.id || '';
    const sourceNameEn = target?.name_en || target?.name_zh || target?.id || '';
    setTemplateForm({
      name_zh: clone && target ? cloneName(sourceNameZh, '（副本）') : target?.name_zh || '',
      name_en: clone && target ? cloneName(sourceNameEn, ' (Copy)') : target?.name_en || '',
      description_zh: target?.description_zh || '',
      description_en: target?.description_en || '',
      collector_keys: target?.collector_keys?.filter((key) => !HIDDEN_DERIVED_COLLECTORS.has(key)) || [],
    });
    setTemplateEditorError('');
    setTemplateEditorOpen(true);
  };

  const saveTemplate = async () => {
    if (!templateForm.name_zh.trim() || !templateForm.name_en.trim()) {
      setTemplateEditorError(zh ? '请填写中英文模板名称。' : 'Chinese and English template names are required.');
      return;
    }
    setTemplateSaving(true);
    setTemplateEditorError('');
    try {
      const endpoint = templateEditorMode === 'create'
        ? '/api/collection-plans/templates'
        : `/api/collection-plans/templates/${encodeURIComponent(templateEditorId)}`;
      const response = await fetch(endpoint, {
        method: templateEditorMode === 'create' ? 'POST' : 'PUT',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(templateForm),
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) throw makeCatalogError(response.status, payload, zh);
      setTemplateEditorOpen(false);
      setTemplateActionError('');
      await loadCatalog(selectedProfileId || undefined);
    } catch (caught) {
      setTemplateEditorError(caught instanceof Error ? caught.message : (zh ? '保存模板失败。' : 'Failed to save the template.'));
    } finally {
      setTemplateSaving(false);
    }
  };

  const deleteTemplate = async (template: CollectionTemplate) => {
    if (!template.id || template.deletable === false) return;
    if (!window.confirm(zh
      ? `确定从 NSOT 模板目录删除“${templateLabel(template, true)}”吗？此操作不会更改已应用到设备的采集策略。`
      : `Remove “${templateLabel(template, false)}” from the NSOT template catalog? This will not change collection policies already applied to devices.`)) return;
    setTemplateDeleting(true);
    setTemplateActionError('');
    try {
      const response = await fetch(`/api/collection-plans/templates/${encodeURIComponent(template.id)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) throw makeCatalogError(response.status, payload, zh);
      await loadCatalog(selectedProfileId || undefined);
    } catch (caught) {
      setTemplateActionError(caught instanceof Error ? caught.message : (zh ? '删除模板失败。' : 'Failed to delete the template.'));
    } finally {
      setTemplateDeleting(false);
    }
  };

  const visibleTemplates = useMemo(() => {
    if (!catalog) return [];
    const query = searchText.trim().toLowerCase();
    return catalog.templates.flatMap((template) => {
      const templateOperations = templateOperationsFor(template, catalog.operations);
      const templateSearchable = [
        template.id,
        template.name_zh,
        template.name_en,
        template.description_zh,
        template.description_en,
        template.note,
        template.condition,
      ].filter(Boolean).join(' ').toLowerCase();
      const templateMatches = !query || templateSearchable.includes(query);
      const operations = templateMatches || !query ? templateOperations : templateOperations.filter((operation) => {
        const searchable = [
          operation.label,
          operation.label_zh,
          operation.label_en,
          operation.collector_key,
          operation.quick_ops_category,
          ...operation.commands.map((command) => command.command),
        ].filter(Boolean).join(' ').toLowerCase();
        return searchable.includes(query);
      });
      return templateMatches || operations.length > 0 ? [{ template, operations }] : [];
    });
  }, [catalog, searchText]);

  const visiblePlatformRows = useMemo(() => visibleTemplates.flatMap(({ template, operations }) => {
    const platformRows: Array<OperationProfile | null> = profileOptions.length ? profileOptions : [null];
    return platformRows.map((profile) => ({ template, operations, profile }));
  }), [visibleTemplates, profileOptions]);
  const visiblePlatformRowCount = visiblePlatformRows.length;
  const totalPages = Math.max(1, Math.ceil(visiblePlatformRowCount / pageSize));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const paginatedPlatformRows = visiblePlatformRows.slice(
    (safeCurrentPage - 1) * pageSize,
    safeCurrentPage * pageSize,
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [searchText, platformFilter]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages));
  }, [totalPages]);

  const detailTemplate = catalog?.templates.find((template) => template.id === detailTemplateId) || null;
  const detailProfileOptions = detailVendorKey
    ? profileOptions.filter((profile) => profileVendorKey(profile) === detailVendorKey)
    : profileOptions;
  const detailOperations = detailTemplate && catalog
    ? templateOperationsFor(detailTemplate, catalog.operations)
    : [];
  const detailDescription = detailTemplate
    ? ((zh ? detailTemplate.description_zh : detailTemplate.description_en) || detailTemplate.description_zh || detailTemplate.description_en)
    : '';
  const detailOtherInfo = detailTemplate
    ? [detailTemplate.condition, detailTemplate.note].filter((value): value is string => Boolean(value) && value !== detailDescription).join(' · ')
    : '';

  const chooseProfile = (profileId: string) => {
    setSelectedProfileId(profileId);
    setCatalog((current) => current ? { ...current, operations: [], selected_profile: current.profiles.find((profile) => profile.id === profileId) || null } : current);
    void loadCatalog(profileId);
  };

  const openTemplateCommands = (templateId: string, profileId: string) => {
    const profile = catalog?.profiles.find((candidate) => candidate.id === profileId);
    setDetailTemplateId(templateId);
    setDetailVendorKey(profile ? profileVendorKey(profile) : '');
    if (profileId !== selectedProfileId) chooseProfile(profileId);
  };

  const retry = () => void loadCatalog(selectedProfileId || undefined);

  return (
    <>
      <section className="min-w-0 space-y-3" aria-label={zh ? 'NSOT 采集命令' : 'NSOT collection commands'}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-slate-100 pb-2 dark:border-white/5">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{zh ? 'NSOT 采集命令' : 'NSOT collection commands'}</h2>
          {catalog && (
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              {zh
                ? `${catalog.templates.length} 个模板 · ${profileVendorCount} 个厂商 · ${profileOptions.length} 个平台版本`
                : `${catalog.templates.length} templates · ${profileVendorCount} vendors · ${profileOptions.length} platform versions`}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={retry} disabled={loading} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 transition hover:border-[#00a9ce]/40 hover:text-[#00a9ce] disabled:cursor-wait disabled:opacity-50 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-300">
            {loading ? <LoaderCircle size={14} className="animate-spin" /> : <RotateCcw size={14} />}
            {zh ? '刷新目录' : 'Refresh catalog'}
          </button>
          <button
            type="button"
            onClick={() => openTemplateEditor('create')}
            className="inline-flex items-center gap-2 rounded-xl px-6 py-2.5 text-[13px] font-bold text-white shadow-lg shadow-[#00a9ce]/15 transition-all active:scale-[0.98]"
            style={{ backgroundColor: '#00a9ce' }}
          >
            <Plus size={16} />{zh ? '新建' : 'New'}
          </button>
        </div>
      </div>

      {templateActionError && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">{templateActionError}</p>}

      {error && (
        <div role="alert" className={`flex min-w-0 items-start gap-3 rounded-xl border p-4 ${error.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200' : 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200'}`}>
          {error.permissionDenied ? <ShieldAlert size={17} className="mt-0.5 shrink-0" /> : <AlertCircle size={17} className="mt-0.5 shrink-0" />}
          <div className="min-w-0 flex-1"><p className="font-semibold">{error.permissionDenied ? (zh ? '权限不足' : 'Permission required') : (zh ? '无法加载操作目录' : 'Could not load the operation catalog')}</p><p className="mt-1 break-words text-xs">{error.message}</p></div>
          <button type="button" onClick={retry} disabled={loading} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-current/20 px-2.5 py-1.5 text-xs font-semibold disabled:opacity-40"><RotateCcw size={13} />{zh ? '重试' : 'Retry'}</button>
        </div>
      )}

      {loading && !catalog && (
        <div role="status" className="flex items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-5 text-sm text-cyan-900 dark:border-cyan-500/20 dark:bg-cyan-500/10 dark:text-cyan-200">
          <LoaderCircle size={16} className="animate-spin" />{zh ? '正在读取采集模板与平台目录…' : 'Loading collection templates and platform catalog…'}
        </div>
      )}

      {!loading && !error && catalog && catalog.templates.length > 0 && profileOptions.length === 0 && (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <CircleHelp size={15} className="mt-0.5 shrink-0" />
          <span>{zh ? '当前筛选下没有可显示的平台 profile；模板仍会显示，可到 TextFSM 平台目录检查已发布的平台版本。' : 'No platform profiles match this filter. Templates remain visible; check the published versions in the TextFSM platform catalog.'}</span>
        </div>
      )}

      {!loading && !error && catalog && catalog.templates.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700">
          <Database size={20} className="mx-auto text-slate-400" />
          <p className="mt-2 font-semibold">{zh ? '暂无 NSOT 采集模板' : 'No NSOT collection templates'}</p>
          <p className="mt-1 text-xs">{zh ? '当前没有可展示的设备采集模板。' : 'There are no device collection templates to display.'}</p>
        </div>
      )}

      {catalog && catalog.templates.length > 0 && (
        <div className="min-w-0">

          {visibleTemplates.length > 0 ? (
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-white/10 dark:bg-slate-900/30">
              <div className="max-h-[min(70vh,820px)] overflow-auto">
              <table className="nx-data-table min-w-[1280px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/95 dark:border-white/5 dark:bg-slate-950/95">
                    <th className="sticky top-0 z-10 w-52 bg-slate-50/95 px-5 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:bg-slate-950/95 dark:text-slate-500">{zh ? '模板名称' : 'Template'}</th>
                    <th className="sticky top-0 z-10 w-36 bg-slate-50/95 px-5 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:bg-slate-950/95 dark:text-slate-500">{zh ? '厂商' : 'Vendor'}</th>
                    <th className="sticky top-0 z-10 min-w-[260px] bg-slate-50/95 px-5 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:bg-slate-950/95 dark:text-slate-500">{zh ? '平台 / 版本' : 'Platform / version'}</th>
                    <th className="sticky top-0 z-10 min-w-64 bg-slate-50/95 px-5 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:bg-slate-950/95 dark:text-slate-500">{zh ? '模板信息' : 'Template details'}</th>
                    <th className="sticky top-0 z-10 w-36 bg-slate-50/95 px-5 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:bg-slate-950/95 dark:text-slate-500"><span className="flex items-center gap-1.5"><Terminal size={12} />{zh ? 'CLI 命令' : 'CLI commands'}</span></th>
                    <th className="sticky top-0 z-10 w-36 bg-slate-50/95 px-5 py-3 text-right text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:bg-slate-950/95 dark:text-slate-500">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                  {paginatedPlatformRows.map(({ template, operations, profile }, index) => {
                    const description = (zh ? template.description_zh : template.description_en)
                      || template.description_zh || template.description_en;
                    const otherInfo = [template.condition, template.note].filter((value): value is string => Boolean(value) && value !== description).join(' · ');
                    const details = profile ? profileDetails(profile, zh) : null;
                    const profileName = profile
                      ? ((zh ? profile.name_zh : profile.name_en) || profile.platform_name || profile.platform_code)
                      : (zh ? '暂无可用平台' : 'No platform profiles');
                    const startsTemplateGroup = index === 0 || paginatedPlatformRows[index - 1]?.template.id !== template.id;
                    return (
                        <tr key={`${template.id}:${profile?.id || 'no-platform'}`} className={`align-middle transition-colors hover:bg-slate-50/60 dark:hover:bg-white/[0.02] ${startsTemplateGroup ? 'border-t-2 border-t-slate-200 dark:border-t-slate-700' : ''}`}>
                          <td className="px-5 py-3">
                            <p className="font-semibold text-slate-800 dark:text-slate-100">{templateLabel(template, zh)}</p>
                            <p className="mt-1 font-mono text-[10px] text-slate-400 dark:text-slate-500">{template.id}</p>
                          </td>
                          <td className="px-5 py-3">
                            <span className="font-medium text-slate-700 dark:text-slate-200">{details?.vendor || '—'}</span>
                          </td>
                          <td className="px-5 py-3">
                            {profile ? <>
                              <p className="font-medium text-slate-700 dark:text-slate-200">{details?.platform || profileName}</p>
                              <p className="mt-1 break-all font-mono text-[10px] text-slate-400 dark:text-slate-500">{profile.platform_code}{profile.release_number ? ` · ${zh ? '目录发布' : 'Registry'} ${profile.release_number}` : ''}</p>
                            </> : <span className="text-xs text-slate-400">{profileName}</span>}
                          </td>
                          <td className="px-5 py-3">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${template.builtin ? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300' : 'bg-cyan-50 text-cyan-700 dark:bg-cyan-500/10 dark:text-cyan-300'}`}>{template.builtin ? (zh ? '系统模板' : 'Built-in') : (zh ? '自定义' : 'Custom')}</span>
                              <span className="rounded-full bg-slate-50 px-2 py-0.5 text-[10px] text-slate-500 dark:bg-slate-950/50 dark:text-slate-400">{zh ? `${template.collector_keys?.length ?? operations.length} 项指标` : `${template.collector_keys?.length ?? operations.length} metrics`}</span>
                            </div>
                            <p className="mt-1.5 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">{description || otherInfo || '—'}</p>
                            {description && otherInfo && <p className="mt-1 text-[10px] leading-relaxed text-slate-400 dark:text-slate-500">{otherInfo}</p>}
                          </td>
                          <td className="px-5 py-3">
                            {profile ? (
                              <button
                                type="button"
                                onClick={() => openTemplateCommands(template.id, profile.id)}
                                disabled={loading}
                                aria-label={zh ? `查看${templateLabel(template, true)}在${details?.vendor} ${details?.platform}上的命令` : `View ${templateLabel(template, false)} commands for ${details?.vendor} ${details?.platform}`}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-semibold text-slate-600 transition hover:border-cyan-300 hover:bg-cyan-50 hover:text-cyan-700 disabled:cursor-wait disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-cyan-500/10 dark:hover:text-cyan-300"
                              >
                                <Terminal size={13} />{zh ? '查看命令' : 'View commands'}
                              </button>
                            ) : <span className="text-[11px] text-slate-400">{zh ? '无平台命令' : 'No platform commands'}</span>}
                          </td>
                          <td className="px-5 py-3 text-right">
                            <span className="inline-flex items-center justify-end gap-1.5" aria-label={zh ? '模板操作' : 'Template actions'}>
                              <button type="button" title={zh ? '克隆为自定义模板' : 'Clone as a custom template'} aria-label={zh ? `克隆${templateLabel(template, true)}` : `Clone ${templateLabel(template, false)}`} onClick={() => openTemplateEditor('create', template, true)} className="rounded-md border border-slate-200 bg-white p-1.5 text-cyan-700 transition hover:border-cyan-300 dark:border-slate-700 dark:bg-slate-900 dark:text-cyan-300"><Copy size={13} /></button>
                              <button type="button" title={zh ? '编辑模板' : 'Edit template'} aria-label={zh ? `编辑${templateLabel(template, true)}` : `Edit ${templateLabel(template, false)}`} onClick={() => openTemplateEditor('edit', template)} disabled={template.editable === false} className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-500 transition hover:border-cyan-300 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-35 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"><Pencil size={13} /></button>
                              <button type="button" title={zh ? '删除模板' : 'Delete template'} aria-label={zh ? `删除${templateLabel(template, true)}` : `Delete ${templateLabel(template, false)}`} onClick={() => void deleteTemplate(template)} disabled={templateDeleting || template.deletable === false} className="rounded-md border border-rose-200 bg-white p-1.5 text-rose-600 transition hover:border-rose-400 disabled:cursor-not-allowed disabled:opacity-35 dark:border-rose-500/30 dark:bg-slate-900 dark:text-rose-300"><Trash2 size={13} /></button>
                            </span>
                          </td>
                        </tr>
                      );
                  })}
                </tbody>
              </table>
              </div>
              <Pagination
                currentPage={safeCurrentPage}
                totalItems={visiblePlatformRowCount}
                itemsPerPage={pageSize}
                onPageChange={setCurrentPage}
                onItemsPerPageChange={(size) => { setPageSize(size); setCurrentPage(1); }}
                language={language}
                itemLabel={zh ? '行' : 'rows'}
                pageUnitLabel={zh ? '行/页' : 'rows/page'}
              />
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center dark:border-slate-700">
              <CircleHelp size={20} className="mx-auto text-slate-400" />
              <p className="mt-2 text-sm font-semibold text-slate-700 dark:text-slate-200">{zh ? '没有匹配的 NSOT 模板' : 'No matching NSOT templates'}</p>
              <p className="mt-1 text-xs text-slate-500">{zh ? '尝试其他模板名称、采集指标或命令关键词。' : 'Try another template, metric, or command keyword.'}</p>
            </div>
          )}
        </div>
      )}
      </section>

      {detailTemplate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-3 backdrop-blur-[3px] sm:p-6"
          role="presentation"
          onMouseDown={(event) => { if (event.target === event.currentTarget) setDetailTemplateId(''); }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="nsot-template-detail-title"
            className="flex max-h-[92vh] min-h-[420px] w-full max-w-6xl flex-col overflow-hidden rounded-[26px] border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
          >
            <header className="flex shrink-0 items-center justify-between gap-4 border-b border-slate-100 px-5 py-4 dark:border-white/10 sm:px-7">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex shrink-0 items-center gap-1.5" aria-hidden="true">
                  <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                </div>
                <span className="h-6 w-px bg-slate-200 dark:bg-slate-700" />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 id="nsot-template-detail-title" className="text-sm font-semibold text-slate-800 dark:text-slate-100">{zh ? 'NSOT 模板详情' : 'NSOT template details'}</h2>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${detailTemplate.builtin ? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300' : 'bg-cyan-50 text-cyan-700 dark:bg-cyan-500/10 dark:text-cyan-300'}`}>
                      {detailTemplate.builtin ? (zh ? '系统模板' : 'Built-in') : (zh ? '自定义模板' : 'Custom template')}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-slate-400 dark:text-slate-500">{templateLabel(detailTemplate, zh)}</p>
                </div>
              </div>
              <button type="button" aria-label={zh ? '关闭模板详情' : 'Close template details'} onClick={() => setDetailTemplateId('')} className="shrink-0 rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/10 dark:hover:text-slate-200"><X size={17} /></button>
            </header>

            <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[270px_minmax(0,1fr)]">
              <aside className="max-h-[30vh] overflow-y-auto border-b border-slate-100 bg-slate-50/70 px-5 py-5 dark:border-white/10 dark:bg-slate-950/20 md:max-h-none md:border-b-0 md:border-r md:px-6">
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">{zh ? '模板信息' : 'Template information'}</p>
                <h3 className="mt-2 break-words text-lg font-semibold leading-snug text-slate-800 dark:text-slate-100">{templateLabel(detailTemplate, zh)}</h3>
                <p className="mt-1 break-all font-mono text-[10px] text-slate-400 dark:text-slate-500">{detailTemplate.id}</p>

                <dl className="mt-5 space-y-4">
                  {[
                    [zh ? '命令厂商' : 'Command vendor', commandVendorLabel],
                    [zh ? '平台 / 版本' : 'Platform / version', commandPlatformLabel],
                    ...(selectedProfile?.release_number ? [[zh ? '目录发布' : 'Registry release', selectedProfile.release_number]] : []),
                    [zh ? '采集指标' : 'Collection metrics', loading ? (zh ? '读取中…' : 'Loading…') : (zh ? `${detailOperations.length} 项` : `${detailOperations.length} metrics`)],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-[10px] font-semibold text-slate-400 dark:text-slate-500">{label}</dt>
                      <dd className="mt-1 break-words text-xs font-medium text-slate-700 dark:text-slate-200">{value}</dd>
                    </div>
                  ))}
                </dl>

                {(detailDescription || detailOtherInfo) && (
                  <div className="mt-5 border-t border-slate-200 pt-4 dark:border-white/10">
                    <p className="text-[10px] font-semibold text-slate-400 dark:text-slate-500">{zh ? '说明' : 'Description'}</p>
                    {detailDescription && <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-slate-600 dark:text-slate-300">{detailDescription}</p>}
                    {detailOtherInfo && <p className="mt-2 whitespace-pre-wrap text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">{detailOtherInfo}</p>}
                  </div>
                )}
              </aside>

              <main className="min-h-0 overflow-y-auto px-4 py-5 sm:px-6">
                <div className="mb-4 flex flex-wrap items-end justify-between gap-3 border-b border-slate-100 pb-3 dark:border-white/10">
                  <div className="min-w-0">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100"><Terminal size={15} className="text-cyan-600 dark:text-cyan-300" />{zh ? '采集指标与 CLI 命令' : 'Collection metrics and CLI commands'}</h3>
                    <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">{selectedProfile ? `${commandVendorLabel} · ${commandPlatformLabel}` : (zh ? '在此选择平台，查看该平台对应命令' : 'Select a platform here to view its commands')}</p>
                  </div>
                  <div className="flex min-w-0 flex-wrap items-end gap-2">
                    <label className="w-full space-y-1 sm:w-64">
                      <span className="block text-[10px] font-semibold text-slate-500 dark:text-slate-400">{zh ? 'TextFSM 平台 / 版本' : 'TextFSM platform / version'}</span>
                      <select value={detailProfileOptions.some((profile) => profile.id === selectedProfileId) ? selectedProfileId : ''} onChange={(event) => chooseProfile(event.target.value)} disabled={!detailProfileOptions.length || loading} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-normal text-slate-700 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
                        {detailProfileOptions.length ? <>
                          {!detailProfileOptions.some((profile) => profile.id === selectedProfileId) && <option value="">{zh ? '请选择平台 profile' : 'Select a platform profile'}</option>}
                          {detailProfileOptions.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, zh)} · {profile.platform_code}{profile.release_number ? ` (${profile.release_number})` : ''}</option>)}
                        </> : <option value="">{zh ? '暂无可选平台 profile' : 'No platform profiles available'}</option>}
                      </select>
                    </label>
                    <span className="mb-0.5 rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500 dark:bg-slate-800 dark:text-slate-300">{zh ? `${detailOperations.length} 项指标` : `${detailOperations.length} metrics`}</span>
                  </div>
                </div>

                {loading ? (
                  <div role="status" className="flex items-center justify-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-10 text-sm text-cyan-800 dark:border-cyan-500/20 dark:bg-cyan-500/10 dark:text-cyan-200">
                    <LoaderCircle size={16} className="animate-spin" />{zh ? '正在读取该平台的采集命令…' : 'Loading commands for this platform…'}
                  </div>
                ) : error ? (
                  <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-5 text-center dark:border-rose-500/30 dark:bg-rose-500/10">
                    <p className="text-sm font-semibold text-rose-800 dark:text-rose-200">{zh ? '平台命令加载失败' : 'Could not load platform commands'}</p>
                    <p className="mt-1 text-xs text-rose-700 dark:text-rose-300">{error.message}</p>
                    <button type="button" onClick={retry} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-800 dark:border-rose-500/40 dark:text-rose-200"><RotateCcw size={13} />{zh ? '重试' : 'Retry'}</button>
                  </div>
                ) : detailOperations.length > 0 ? (
                  <div className="space-y-3">
                    {detailOperations.map((operation) => {
                      const metricName = (zh ? operation.label_zh : operation.label_en) || operation.label;
                      const isMetricConditional = isConditional(operation) || operation.commands.some((command) => isConditional(operation, command));
                      const isMetricUnsupported = isUnsupported(operation)
                        || (operation.commands.length > 0 && operation.commands.every((command) => isUnsupported(operation, command) && !command.command));
                      const isMetricParserMissing = [operation.status, ...operation.commands.map((command) => command.status)]
                        .some((status) => String(status || '').toLowerCase() === 'parser_missing');
                      const commandLines = operation.commands.filter((command) => command.command).map((command) => command.command);
                      return (
                        <section key={operation.collector_key} className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-white/10 dark:bg-slate-900/50">
                          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/70 px-4 py-2.5 dark:border-white/5 dark:bg-slate-950/30">
                            <div className="min-w-0">
                              <h4 className="truncate text-xs font-semibold text-slate-700 dark:text-slate-200">{metricName}</h4>
                              <p className="mt-0.5 font-mono text-[10px] text-slate-400 dark:text-slate-500">{operation.collector_key}</p>
                            </div>
                            {(isMetricConditional || isMetricUnsupported || isMetricParserMissing) && (
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${isMetricUnsupported ? 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300' : 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200'}`}>
                                {isMetricUnsupported ? (zh ? '暂不支持' : 'Unavailable') : isMetricParserMissing ? (zh ? '命令待配置' : 'Command pending') : (zh ? '按条件采集' : 'Conditional')}
                              </span>
                            )}
                          </div>
                          <div className="p-3.5">
                            {!selectedProfile ? (
                              <p className="rounded-lg bg-slate-50 px-3 py-2.5 text-[11px] text-slate-500 dark:bg-slate-950/50 dark:text-slate-400">{zh ? '请先选择 TextFSM 平台和版本。' : 'Select a TextFSM platform and version first.'}</p>
                            ) : commandLines.length > 0 ? (
                              <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 px-4 py-3 font-mono text-[11px] leading-relaxed text-cyan-100"><code>{commandLines.join('\n')}</code></pre>
                            ) : (
                              <p className={`rounded-lg px-3 py-2.5 text-[11px] leading-relaxed ${isMetricUnsupported ? 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300' : isMetricParserMissing ? 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200' : 'bg-slate-50 text-slate-500 dark:bg-slate-950/50 dark:text-slate-400'}`}>
                                {isMetricUnsupported ? (zh ? '当前平台暂无可用命令。' : 'No command is available for this platform.') : isMetricParserMissing ? (zh ? '当前平台暂未配置命令。' : 'No command is configured for this platform.') : (zh ? '暂无对应命令。' : 'No command available.')}
                              </p>
                            )}
                          </div>
                        </section>
                      );
                    })}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-300 px-4 py-10 text-center dark:border-slate-700">
                    <CircleHelp size={20} className="mx-auto text-slate-400" />
                    <p className="mt-2 text-sm font-semibold text-slate-700 dark:text-slate-200">{zh ? '此模板暂未配置采集指标' : 'No collection metrics configured'}</p>
                  </div>
                )}
              </main>
            </div>

            <footer className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-white px-5 py-3 dark:border-white/10 dark:bg-slate-900 sm:px-7">
              {detailTemplate.editable !== false && !detailTemplate.builtin && (
                <button type="button" onClick={() => { setDetailTemplateId(''); openTemplateEditor('edit', detailTemplate); }} className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-600 transition hover:border-cyan-300 hover:text-cyan-700 dark:border-slate-700 dark:text-slate-300 dark:hover:text-cyan-300">{zh ? '编辑模板' : 'Edit template'}</button>
              )}
              <button type="button" onClick={() => setDetailTemplateId('')} className="rounded-lg bg-cyan-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-cyan-700">{zh ? '关闭' : 'Close'}</button>
            </footer>
          </div>
        </div>
      )}

      {templateEditorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setTemplateEditorOpen(false); }}>
          <div role="dialog" aria-modal="true" aria-labelledby="nsot-template-editor-title" className="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="nsot-template-editor-title" className="text-base font-semibold text-slate-900 dark:text-white">{templateEditorMode === 'create' ? (zh ? '新建 NSOT 采集模板' : 'New NSOT collection template') : (zh ? '编辑 NSOT 采集模板' : 'Edit NSOT collection template')}</h2>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{zh ? '只配置采集指标，平台命令仍从平台 Registry / TextFSM 目录解析。' : 'Configure collection metrics only; platform commands still come from the Registry / TextFSM catalog.'}</p>
              </div>
              <button type="button" onClick={() => setTemplateEditorOpen(false)} className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/10 dark:hover:text-slate-200"><X size={17} /></button>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <span>{zh ? '中文名称' : 'Chinese name'}</span>
                <input value={templateForm.name_zh} onChange={(event) => setTemplateForm((current) => ({ ...current, name_zh: event.target.value }))} maxLength={128} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
              </label>
              <label className="space-y-1 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <span>{zh ? '英文名称' : 'English name'}</span>
                <input value={templateForm.name_en} onChange={(event) => setTemplateForm((current) => ({ ...current, name_en: event.target.value }))} maxLength={128} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
              </label>
              <label className="space-y-1 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <span>{zh ? '中文说明' : 'Chinese description'}</span>
                <textarea value={templateForm.description_zh} onChange={(event) => setTemplateForm((current) => ({ ...current, description_zh: event.target.value }))} maxLength={500} rows={2} className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
              </label>
              <label className="space-y-1 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <span>{zh ? '英文说明' : 'English description'}</span>
                <textarea value={templateForm.description_en} onChange={(event) => setTemplateForm((current) => ({ ...current, description_en: event.target.value }))} maxLength={500} rows={2} className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
              </label>
            </div>

            <div className="mt-4">
              <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">{zh ? '采集指标' : 'Collection metrics'}</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {templateCollectorOptions.map((option) => {
                  const checked = templateForm.collector_keys.includes(option.key);
                  return (
                    <label key={option.key} className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700 transition hover:border-cyan-300 dark:border-slate-700 dark:text-slate-300">
                      <input type="checkbox" checked={checked} onChange={(event) => setTemplateForm((current) => ({
                        ...current,
                        collector_keys: event.target.checked
                          ? [...current.collector_keys, option.key]
                          : current.collector_keys.filter((key) => key !== option.key),
                      }))} className="accent-cyan-600" />
                      <span>{option.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            {templateEditorError && <p role="alert" className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">{templateEditorError}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setTemplateEditorOpen(false)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-slate-300 dark:border-slate-700 dark:text-slate-300">{zh ? '取消' : 'Cancel'}</button>
              <button type="button" onClick={() => void saveTemplate()} disabled={templateSaving} className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-wait disabled:opacity-60"><Save size={13} />{templateSaving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存模板' : 'Save template')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default NSOTCollectionOperations;
