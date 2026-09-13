import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle, CircleHelp, Database, LoaderCircle,
  Network, RotateCcw, Search, ShieldAlert, Terminal,
} from 'lucide-react';

interface CollectionTemplate {
  id: string;
  name_zh?: string;
  name_en?: string;
  description_zh?: string;
  description_en?: string;
  collector_keys?: string[];
  condition?: string | null;
  note?: string | null;
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

const profileLabel = (profile: OperationProfile, zh: boolean): string => {
  const localized = (zh ? profile.name_zh : profile.name_en) || profile.name_zh || profile.name_en;
  if (localized) return localized;
  const platform = profile.platform_name || profile.platform_code;
  const release = profile.release_number ? ` · ${zh ? '操作发布号' : 'Registry release'} ${profile.release_number}` : '';
  return `${platform}${release}`;
};

const statusLabel = (status: string, zh: boolean): string => {
  const normalized = status.toLowerCase();
  if (normalized === 'unsupported') return zh ? '不支持' : 'Unsupported';
  if (normalized === 'conditional' || normalized === 'pending_condition') return zh ? '条件采集' : 'Conditional';
  if (normalized === 'parser_missing') return zh ? '缺少解析器' : 'Parser missing';
  if (normalized === 'partial') return zh ? '部分可解析' : 'Partially resolved';
  if (normalized === 'projection') return zh ? '数据库派生' : 'Database projection';
  if (['available', 'supported', 'ok', 'ready', 'resolved'].includes(normalized)) return zh ? '可用' : 'Available';
  return status;
};

const isUnsupported = (operation: CollectionOperation, command?: OperationCommand): boolean =>
  [operation.status, command?.status].some((status) => String(status || '').toLowerCase() === 'unsupported');

const isConditional = (operation: CollectionOperation, command?: OperationCommand): boolean =>
  operation.conditional === true
  || Boolean(operation.condition || command?.condition)
  || [operation.status, command?.status].some((status) => ['conditional', 'pending_condition'].includes(String(status || '').toLowerCase()));

type CommandOrigin = 'registry' | 'textfsm' | 'legacy_textfsm' | 'legacy' | 'mixed' | 'unknown';

const getCommandOrigin = (command: OperationCommand): CommandOrigin => {
  switch (command.command_source) {
    case 'platform_registry': return 'registry';
    case 'textfsm_action_metadata': return 'textfsm';
    case 'legacy_catalog_textfsm': return 'legacy_textfsm';
    case 'legacy_catalog': return 'legacy';
    default: return 'unknown';
  }
};

const getOperationOrigin = (operation: CollectionOperation): CommandOrigin => {
  const commandOrigins = Array.from(new Set(operation.commands.map(getCommandOrigin).filter((origin) => origin !== 'unknown')));
  if (commandOrigins.length > 1) return 'mixed';
  if (commandOrigins.length === 1) return commandOrigins[0];
  return 'unknown';
};

const getOriginLabel = (origin: CommandOrigin, zh: boolean): string => {
  if (origin === 'registry') return zh ? 'Registry action 命令' : 'Registry action command';
  if (origin === 'textfsm') return zh ? 'TextFSM action metadata fallback' : 'TextFSM action metadata fallback';
  if (origin === 'legacy_textfsm') return zh ? '旧模板 TextFSM fallback' : 'Legacy template TextFSM fallback';
  if (origin === 'legacy') return zh ? '旧版平台目录命令' : 'Legacy platform catalog command';
  if (origin === 'mixed') return zh ? '混合来源' : 'Mixed sources';
  return zh ? '命令来源未识别' : 'Command source unknown';
};

const getOriginClass = (origin: CommandOrigin): string => {
  if (origin === 'registry') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
  if (origin === 'textfsm' || origin === 'legacy_textfsm' || origin === 'mixed') return 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
};

interface NSOTCollectionOperationsProps {
  language: string;
}

const NSOTCollectionOperations: React.FC<NSOTCollectionOperationsProps> = ({ language }) => {
  const zh = language === 'zh';
  const [catalog, setCatalog] = useState<OperationCatalog | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<CatalogError | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);

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
      setSelectedTemplateId((current) => parsed.templates.some((template) => template.id === current)
        ? current
        : parsed.templates.find((template) => template.id === 'role_default')?.id || parsed.templates[0]?.id || '');
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

  const selectedTemplate = catalog?.templates.find((template) => template.id === selectedTemplateId) || null;
  const visibleOperations = useMemo(() => {
    if (!catalog || !selectedTemplate) return [];
    const query = searchText.trim().toLowerCase();
    return catalog.operations.filter((operation) => {
      const templateApplies = Array.isArray(selectedTemplate.collector_keys) && selectedTemplate.collector_keys.length > 0
        ? selectedTemplate.collector_keys.includes(operation.collector_key)
        : operation.applicable_templates.includes(selectedTemplate.id);
      if (!templateApplies) return false;
      if (!query) return true;
      const searchable = [
        operation.label,
        operation.label_zh,
        operation.label_en,
        operation.collector_key,
        operation.quick_ops_category,
        operation.action_code,
        ...operation.commands.flatMap((command) => [
          command.command,
          command.command_source,
          command.textfsm_template,
          command.textfsm_source,
        ]),
      ].filter(Boolean).join(' ').toLowerCase();
      return searchable.includes(query);
    });
  }, [catalog, searchText, selectedTemplate]);

  const chooseProfile = (profileId: string) => {
    setSelectedProfileId(profileId);
    setCatalog((current) => current ? { ...current, operations: [], selected_profile: current.profiles.find((profile) => profile.id === profileId) || null } : current);
    void loadCatalog(profileId);
  };

  const retry = () => void loadCatalog(selectedProfileId || undefined);

  return (
    <section className="min-w-0 space-y-4" aria-label={zh ? 'NSOT 采集操作目录' : 'NSOT collection operation catalog'}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 rounded-xl bg-cyan-500/10 p-2 text-cyan-700 dark:text-cyan-300"><Database size={18} /></div>
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-slate-800 dark:text-white">{zh ? 'NSOT 设备采集目录' : 'NSOT device collection catalog'}</h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-500 dark:text-slate-400">
              {zh
                ? '只读查看模板对应的采集事实、Quick Ops action 与当前 profile/release 的命令解析来源。命令维护仍在 Platform Registry / TextFSM 中完成。'
                : 'Read-only view of template facts, Quick Ops actions, and command sources for the selected profile/release. Maintain commands in Platform Registry / TextFSM.'}
            </p>
          </div>
        </div>
        <button type="button" onClick={retry} disabled={loading} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-cyan-300 hover:text-cyan-700 disabled:cursor-wait disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
          {loading ? <LoaderCircle size={14} className="animate-spin" /> : <RotateCcw size={14} />}
          {zh ? '刷新目录' : 'Refresh catalog'}
        </button>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-3 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 dark:border-white/10 dark:bg-slate-900/30 md:grid-cols-2">
        <label className="min-w-0 space-y-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300">
          <span>{zh ? 'NSOT 采集模板' : 'NSOT collection template'}</span>
          <select value={selectedTemplateId} onChange={(event) => setSelectedTemplateId(event.target.value)} disabled={!catalog?.templates.length} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
            {catalog?.templates.length ? catalog.templates.map((template) => <option key={template.id} value={template.id}>{templateLabel(template, zh)}</option>) : <option value="">{zh ? '暂无可用模板' : 'No templates available'}</option>}
          </select>
          {selectedTemplate && (selectedTemplate.description_zh || selectedTemplate.description_en) && <span className="block font-normal leading-relaxed text-slate-500">{zh ? selectedTemplate.description_zh || selectedTemplate.description_en : selectedTemplate.description_en || selectedTemplate.description_zh}</span>}
          {selectedTemplate && (selectedTemplate.condition || selectedTemplate.note) && <span className="block font-normal leading-relaxed text-amber-700 dark:text-amber-300">{selectedTemplate.condition || selectedTemplate.note}</span>}
        </label>

        <label className="min-w-0 space-y-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300">
          <span>{zh ? '软件平台 profile / release' : 'Software platform profile / release'}</span>
          <select value={selectedProfileId} onChange={(event) => chooseProfile(event.target.value)} disabled={!catalog?.profiles.length || loading} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
            {catalog?.profiles.length ? <>
              {!selectedProfileId && <option value="">{zh ? '请选择平台 profile' : 'Select a platform profile'}</option>}
              {catalog.profiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, zh)}</option>)}
            </> : <option value="">{zh ? '暂无可选平台 profile' : 'No platform profiles available'}</option>}
          </select>
          {catalog?.selected_profile && (
            <span className="block break-words font-normal leading-relaxed text-slate-500">
              {catalog.selected_profile.parser_platform && <>{zh ? 'Parser 平台' : 'Parser platform'}: <span className="font-mono">{catalog.selected_profile.parser_platform}</span></>}
              {catalog.selected_profile.release_number && <>{catalog.selected_profile.parser_platform ? ' · ' : ''}{zh ? '操作发布号（Registry）' : 'Registry release'}: <span className="font-mono">{catalog.selected_profile.release_number}</span></>}
            </span>
          )}
        </label>
      </div>

      {error && (
        <div role="alert" className={`flex min-w-0 items-start gap-3 rounded-xl border p-4 ${error.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200' : 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200'}`}>
          {error.permissionDenied ? <ShieldAlert size={17} className="mt-0.5 shrink-0" /> : <AlertCircle size={17} className="mt-0.5 shrink-0" />}
          <div className="min-w-0 flex-1"><p className="font-semibold">{error.permissionDenied ? (zh ? '权限不足' : 'Permission required') : (zh ? '无法加载操作目录' : 'Could not load the operation catalog')}</p><p className="mt-1 break-words text-xs">{error.message}</p></div>
          <button type="button" onClick={retry} disabled={loading} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-current/20 px-2.5 py-1.5 text-xs font-semibold disabled:opacity-40"><RotateCcw size={13} />{zh ? '重试' : 'Retry'}</button>
        </div>
      )}

      {loading && (
        <div role="status" className="flex items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-5 text-sm text-cyan-900 dark:border-cyan-500/20 dark:bg-cyan-500/10 dark:text-cyan-200">
          <LoaderCircle size={16} className="animate-spin" />{zh ? '正在读取模板与当前 profile 的操作目录…' : 'Loading templates and operations for the selected profile…'}
        </div>
      )}

      {!loading && !error && catalog && catalog.templates.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700">
          <Database size={20} className="mx-auto text-slate-400" />
          <p className="mt-2 font-semibold">{zh ? '暂无 NSOT 采集模板' : 'No NSOT collection templates'}</p>
          <p className="mt-1 text-xs">{zh ? '当前没有可展示的设备采集模板。' : 'There are no device collection templates to display.'}</p>
        </div>
      )}

      {!loading && !error && catalog && catalog.templates.length > 0 && catalog.profiles.length === 0 && (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <CircleHelp size={15} className="mt-0.5 shrink-0" />
          <span>{zh ? '当前没有可选的软件平台 profile，因此无法确定 release 对应的 Quick Ops 与 TextFSM 命令。' : 'No software platform profiles are available, so release-specific Quick Ops and TextFSM commands cannot be resolved.'}</span>
        </div>
      )}

      {!loading && !error && catalog && catalog.profiles.length > 0 && !catalog.selected_profile && !selectedProfileId && (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <CircleHelp size={15} className="mt-0.5 shrink-0" />
          <span>{zh ? '请选择软件平台 profile，目录才能按该平台与 release 精确解析命令。' : 'Select a software platform profile to resolve commands for its exact platform and release.'}</span>
        </div>
      )}

      {!loading && !error && catalog && catalog.profiles.length > 0 && (Boolean(catalog.selected_profile) || Boolean(selectedProfileId)) && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {zh ? `当前模板显示 ${visibleOperations.length} 项采集操作` : `${visibleOperations.length} collection operations for this template`}
              {catalog.selected_profile?.parser_platform && <span className="ml-1.5 font-mono text-slate-400">· {catalog.selected_profile.parser_platform}</span>}
            </p>
            <label className="relative block w-full sm:w-64">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={zh ? '搜索采集项或命令来源' : 'Search operations or sources'} className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-xs text-slate-700 outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/10 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200" />
            </label>
          </div>

          {visibleOperations.length > 0 ? (
            <div className="grid min-w-0 gap-3">
              {visibleOperations.map((operation) => {
                const operationConditional = isConditional(operation)
                  || operation.commands.some((command) => isConditional(operation, command));
                const operationUnsupported = isUnsupported(operation)
                  || (operation.commands.length > 0 && operation.commands.every((command) => isUnsupported(operation, command) && !command.command));
                const operationParserMissing = [operation.status, ...operation.commands.map((command) => command.status)]
                  .some((status) => String(status || '').toLowerCase() === 'parser_missing');
                const operationPartial = [operation.status, ...operation.commands.map((command) => command.status)]
                  .some((status) => String(status || '').toLowerCase() === 'partial');
                const operationProjection = String(operation.status || '').toLowerCase() === 'projection';
                const operationOrigin = getOperationOrigin(operation);
                const displayLabel = (zh ? operation.label_zh : operation.label_en) || operation.label;
                return (
                  <article key={operation.collector_key} className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-slate-900/40 sm:p-5">
                    <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex min-w-0 items-start gap-3">
                        <div className="mt-0.5 rounded-lg bg-slate-100 p-2 text-slate-500 dark:bg-slate-800 dark:text-slate-300"><Network size={15} /></div>
                        <div className="min-w-0">
                          <h3 className="break-words text-sm font-bold text-slate-800 dark:text-white">{displayLabel}</h3>
                          <p className="mt-1 break-all font-mono text-[10px] text-slate-400">{operation.collector_key}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-1.5 sm:justify-end">
                        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">{operation.transport}</span>
                        {operationUnsupported ? (
                          <span className="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">{zh ? '不支持' : 'Unsupported'}</span>
                        ) : operationConditional ? (
                          <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">{zh ? '条件采集' : 'Conditional'}</span>
                        ) : operationParserMissing ? (
                          <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">{zh ? '缺少解析器' : 'Parser missing'}</span>
                        ) : operationPartial ? (
                          <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">{zh ? '部分可解析' : 'Partially resolved'}</span>
                        ) : operationProjection ? (
                          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">{zh ? '数据库派生' : 'Database projection'}</span>
                        ) : (
                          <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${getOriginClass(operationOrigin)}`}>
                            {getOriginLabel(operationOrigin, zh)}
                          </span>
                        )}
                      </div>
                    </div>

                    <dl className="mt-4 grid min-w-0 grid-cols-1 gap-3 border-t border-slate-100 pt-3 dark:border-white/5 sm:grid-cols-2 lg:grid-cols-3">
                      <div className="min-w-0"><dt className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Quick Ops category</dt><dd className="mt-1 break-all text-xs font-semibold text-slate-700 dark:text-slate-200">{operation.quick_ops_category || '—'}</dd></div>
                      <div className="min-w-0"><dt className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{zh ? 'Registry action 绑定' : 'Registry action binding'}</dt><dd className="mt-1 break-words text-xs text-slate-700 dark:text-slate-200">{operation.action_bound ? (zh ? '已绑定' : 'Bound') : (zh ? '未绑定' : 'Not bound')}</dd></div>
                      <div className="min-w-0"><dt className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{zh ? '语义 action_code' : 'Semantic action_code'}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-700 dark:text-slate-200">{operation.action_code || (zh ? '无候选' : 'No candidate')}</dd></div>
                      <div className="min-w-0"><dt className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{zh ? '传输方式' : 'Transport'}</dt><dd className="mt-1 break-words text-xs text-slate-700 dark:text-slate-200">{operation.transport}</dd></div>
                    </dl>

                    <div className="mt-4 space-y-2">
                      <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400"><Terminal size={12} />{zh ? '当前 release 命令与解析来源' : 'Commands and parser sources for this release'}</p>
                      {operation.commands.length > 0 ? operation.commands.map((command, commandIndex) => {
                        const unsupported = isUnsupported(operation, command);
                        const conditional = isConditional(operation, command);
                        const commandParserMissing = String(command.status || '').toLowerCase() === 'parser_missing';
                        const detailStatus = command.status || operation.status;
                        return (
                          <div key={`${operation.collector_key}:${commandIndex}`} className="grid min-w-0 gap-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-950/40 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                            <div className="min-w-0">
                              <p className="mb-1 text-[10px] font-semibold text-slate-500">{zh ? '具体命令' : 'Command'}</p>
                              {command.command ? <code className="block max-h-36 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-900 px-3 py-2 font-mono text-[11px] leading-relaxed text-cyan-100">{command.command}</code> : (
                                <p className={`rounded-lg px-3 py-2 text-[11px] leading-relaxed ${unsupported ? 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300' : commandParserMissing ? 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200' : 'bg-white text-slate-500 dark:bg-slate-900 dark:text-slate-400'}`}>
                                  {operationProjection
                                    ? (zh ? '此采集项由数据库派生，无需 CLI 命令。' : 'This fact is derived from the database and does not require a CLI command.')
                                    : commandParserMissing
                                      ? (zh ? '缺少匹配解析器；这不代表命令不受支持。' : 'No matching parser is available; this does not mean the command is unsupported.')
                                      : unsupported
                                    ? (zh ? '此平台/软件版本没有匹配的已发布 action 或 TextFSM command 模板。' : 'No published action or TextFSM command template matches this platform and software release.')
                                    : (zh ? '该采集项没有返回具体命令。' : 'No concrete command was returned for this operation.')}
                                </p>
                              )}
                            </div>
                            <div className="min-w-0 space-y-2 text-[10px] leading-relaxed text-slate-600 dark:text-slate-300">
                              <div className="grid min-w-0 grid-cols-1 gap-x-3 gap-y-1 sm:grid-cols-2">
                                <p className="min-w-0 break-words"><span className="font-semibold text-slate-500">action_code: </span><code className="break-all">{command.action_code || '—'}</code></p>
                                <p className="min-w-0 break-words"><span className="font-semibold text-slate-500">{zh ? '命令绑定来源' : 'Command binding source'}: </span>{getOriginLabel(getCommandOrigin(command), zh)}</p>
                                <p className="min-w-0 break-words"><span className="font-semibold text-slate-500">{zh ? '命令来源' : 'Command source'}: </span>{command.command_source || '—'}</p>
                                <p className="min-w-0 break-words"><span className="font-semibold text-slate-500">TextFSM: </span>{command.textfsm_template || '—'}</p>
                                <p className="min-w-0 break-words sm:col-span-2"><span className="font-semibold text-slate-500">{zh ? 'TextFSM 来源' : 'TextFSM source'}: </span>{command.textfsm_source || '—'}</p>
                              </div>
                              {(detailStatus || conditional) && (
                                <div className="flex flex-wrap items-center gap-1.5">
                                  {detailStatus && <span className={`rounded-full px-2 py-0.5 font-semibold ${unsupported ? 'bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-200' : conditional || commandParserMissing ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200'}`}>{statusLabel(detailStatus, zh)}</span>}
                                  {conditional && <span className="rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">{zh ? '条件采集' : 'Conditional'}</span>}
                                </div>
                              )}
                              {command.condition && <p className="break-words text-amber-800 dark:text-amber-200">{command.condition}</p>}
                            </div>
                          </div>
                        );
                      }) : (
                        <div className={`rounded-xl px-3 py-2.5 text-[11px] leading-relaxed ${operationUnsupported ? 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300' : 'bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-400'}`}>
                          {operationProjection
                            ? (zh ? '此采集项由数据库派生，无需 CLI 命令。' : 'This fact is derived from the database and does not require a CLI command.')
                            : operationParserMissing
                              ? (zh ? '缺少匹配解析器；这不代表命令不受支持。' : 'No matching parser is available; this does not mean the command is unsupported.')
                              : operationUnsupported
                                ? (zh ? '当前平台/软件版本没有匹配的已发布 action 或 TextFSM command 模板。' : 'No published action or TextFSM command template matches this platform and software release.')
                                : (zh ? '该采集项没有返回具体命令。' : 'No concrete command was returned for this operation.')}
                        </div>
                      )}
                      {operation.condition && <p className="break-words text-[10px] leading-relaxed text-amber-800 dark:text-amber-200">{operation.condition}</p>}
                  </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center dark:border-slate-700">
              <CircleHelp size={20} className="mx-auto text-slate-400" />
              <p className="mt-2 text-sm font-semibold text-slate-700 dark:text-slate-200">{searchText.trim() ? (zh ? '没有匹配的采集项' : 'No matching operations') : (zh ? '此模板没有可展示的采集操作' : 'No collection operations are available for this template')}</p>
              <p className="mt-1 text-xs text-slate-500">{searchText.trim() ? (zh ? '尝试其他采集项、命令或来源关键词。' : 'Try another operation, command, or source keyword.') : (zh ? '目录不会跨平台或软件版本补入命令。' : 'The catalog does not substitute commands from another platform or software release.')}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
};

export default NSOTCollectionOperations;
