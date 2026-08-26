import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FileCode, Plus, Search, RefreshCw, Pencil, Trash2, X, Save,
  CheckCircle2, AlertCircle, Loader2, PlayCircle,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import PageHero from '../components/PageHero';
import Pagination from '../components/Pagination';
import { alertPanelClass } from '../components/shared';
import { useAlertOverlayDismiss } from './alertManagementShared';
import {
  TEXTFSM_PLATFORM_FAMILIES as PLATFORM_FAMILIES,
  TEXTFSM_VENDOR_OPTIONS as VENDOR_OPTIONS,
  TEXTFSM_VERSION_LABELS as VERSION_LABELS,
  TEXTFSM_VERSION_ORDER,
  getConcreteEditorPlatform,
  getEditorSelection,
  getPlatformFamilyOption,
  getVendorOption,
} from './textfsmPlatformCatalog';

interface Props {
  t: (key: string) => string;
  language: string;
}

interface Template {
  filename: string;
  platform: string;
  command: string;
  source: 'builtin' | 'custom';
  stem?: string;
  vendor?: string;
  platform_family?: string;
  version?: string;
  template_variant?: string;
  action_code?: string;
}

interface ActionOption {
  action_code: string;
  name_zh: string;
  name_en: string;
  purpose?: string;
  command?: string | null;
  group_zh?: string;
  group_en?: string;
  available?: boolean;
}

interface TestResult {
  records: Array<Record<string, any>>;
  count: number;
  fields: string[];
}

const TEXTFSM_EXCLUDED_ACTION_CODES = new Set(['get_running_config', 'get_startup_config']);

const getTemplateDisplayMeta = (template: Template) => {
  const platform = String(template.platform || '').toLowerCase();
  const selection = getEditorSelection(platform, template.version || template.template_variant);
  const familyValue = template.platform_family || selection.platformFamily;
  const vendorValue = template.vendor || selection.vendor;
  const versionValue = String(template.version || template.template_variant || selection.version || 'common').toLowerCase();
  const vendor = getVendorOption(vendorValue);
  const family = getPlatformFamilyOption(familyValue);
  const version = VERSION_LABELS[versionValue] || { label: versionValue.toUpperCase(), labelEn: versionValue.toUpperCase() };
  return {
    vendor: vendor ? { label: vendor.label, labelEn: vendor.labelEn } : { label: vendorValue, labelEn: vendorValue },
    family: family ? { label: family.label, labelEn: family.labelEn } : { label: familyValue, labelEn: familyValue },
    version,
  };
};

const DEFAULT_TEMPLATE_CONTENT = `Value EXAMPLE_FIELD (\\S+)

Start
  # 示例：匹配 "CPU: 23%"
  ^CPU:\\s+\${EXAMPLE_FIELD}% -> Record
`;

const TextFSMTemplatesTab: React.FC<Props> = ({ language }) => {
  const isZh = language === 'zh';

  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [vendorFilter, setVendorFilter] = useState('');
  const [platformFamilyFilter, setPlatformFamilyFilter] = useState('');
  const [versionFilter, setVersionFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'' | 'builtin' | 'custom'>('');

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null);
  const [editorVendor, setEditorVendor] = useState('cisco');
  const [editorPlatformFamily, setEditorPlatformFamily] = useState('cisco_ios');
  const [editorVersion, setEditorVersion] = useState('common');
  const [editorCommand, setEditorCommand] = useState('');
  const [editorActionCode, setEditorActionCode] = useState('');
  const [actionOptions, setActionOptions] = useState<ActionOption[]>([]);
  const [actionOptionsLoading, setActionOptionsLoading] = useState(false);
  const [editorContent, setEditorContent] = useState(DEFAULT_TEMPLATE_CONTENT);
  const [saving, setSaving] = useState(false);

  const [sampleOutput, setSampleOutput] = useState('');
  const [defaultSample, setDefaultSample] = useState('');
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [testError, setTestError] = useState('');
  const [testing, setTesting] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState<Template | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const showToast = (type: 'success' | 'error', text: string) => {
    setToast({ type, text });
    setTimeout(() => setToast(null), 3500);
  };

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (vendorFilter) params.set('vendor', vendorFilter);
      if (platformFamilyFilter) params.set('platform_family', platformFamilyFilter);
      if (versionFilter) params.set('version', versionFilter);
      if (search) params.set('search', search);
      if (sourceFilter) params.set('source', sourceFilter);
      params.set('page', String(page));
      params.set('page_size', String(pageSize));
      
      const res = await fetch(`/api/textfsm/templates?${params.toString()}`, { headers: authHeaders });
      if (res.ok) {
        const json = await res.json();
        setTemplates(json?.data?.items || []);
        setTotal(json?.data?.total || 0);
      }
    } catch (e) { /* noop */ }
    setLoading(false);
  }, [vendorFilter, platformFamilyFilter, versionFilter, search, sourceFilter, page, pageSize, authHeaders]);

  useEffect(() => { fetchTemplates(); }, [fetchTemplates]);

  // Reset page on filter change
  useEffect(() => {
    setPage(1);
  }, [search, vendorFilter, platformFamilyFilter, versionFilter, sourceFilter]);

  const availablePlatformFamilies = useMemo(
    () => PLATFORM_FAMILIES.filter((item) => !vendorFilter || item.vendor === vendorFilter),
    [vendorFilter],
  );

  const availableVersions = useMemo(() => {
    const families = platformFamilyFilter
      ? PLATFORM_FAMILIES.filter((item) => item.value === platformFamilyFilter)
      : availablePlatformFamilies;
    return Array.from(new Set(families.flatMap((item) => item.versions)))
      .sort((left, right) => {
        return TEXTFSM_VERSION_ORDER.indexOf(left) - TEXTFSM_VERSION_ORDER.indexOf(right);
      });
  }, [availablePlatformFamilies, platformFamilyFilter]);

  const editorPlatform = useMemo(
    () => getConcreteEditorPlatform(editorPlatformFamily, editorVersion),
    [editorPlatformFamily, editorVersion],
  );
  const editorPlatformFamilies = useMemo(
    () => PLATFORM_FAMILIES.filter((item) => item.vendor === editorVendor),
    [editorVendor],
  );
  const editorVersionOptions = useMemo(
    () => getPlatformFamilyOption(editorPlatformFamily)?.versions || [],
    [editorPlatformFamily],
  );
  const actionOptionGroups = useMemo(() => {
    const groups = new Map<string, ActionOption[]>();
    actionOptions
      .filter((option) => !TEXTFSM_EXCLUDED_ACTION_CODES.has(option.action_code))
      .filter((option) => option.available || option.action_code === editorActionCode)
      .forEach((option) => {
        const group = isZh ? (option.group_zh || '其他查询') : (option.group_en || 'Other queries');
        groups.set(group, [...(groups.get(group) || []), option]);
      });
    return Array.from(groups.entries());
  }, [actionOptions, editorActionCode, isZh]);

  useEffect(() => {
    if (!editorOpen || !editorPlatform) {
      setActionOptions([]);
      setActionOptionsLoading(false);
      return undefined;
    }
    let active = true;
    setActionOptionsLoading(true);
    const params = new URLSearchParams({ platform: editorPlatform });
    fetch(`/api/textfsm/action-options?${params.toString()}`, { headers: authHeaders })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (active) setActionOptions(payload?.data || []);
      })
      .catch(() => {
        if (active) setActionOptions([]);
      })
      .finally(() => {
        if (active) setActionOptionsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [authHeaders, editorOpen, editorPlatform]);

  useAlertOverlayDismiss(editorOpen, () => setEditorOpen(false));
  useAlertOverlayDismiss(!!confirmDelete, () => setConfirmDelete(null));

  const openNewEditor = () => {
    setEditingTemplate(null);
    setEditorVendor('cisco');
    setEditorPlatformFamily('');
    setEditorVersion('');
    setEditorCommand('');
    setEditorActionCode('');
    setEditorContent(DEFAULT_TEMPLATE_CONTENT);
    setSampleOutput('');
    setDefaultSample('');
    setTestResult(null);
    setTestError('');
    setEditorOpen(true);
  };

  const openEditor = async (tpl: Template) => {
    try {
      const res = await fetch(`/api/textfsm/templates/${tpl.filename}`, { headers: authHeaders });
      if (!res.ok) throw new Error('Fetch failed');
      const json = await res.json();
      const selection = getEditorSelection(tpl.platform, tpl.version || tpl.template_variant);
      setEditingTemplate(tpl);
      setEditorVendor(selection.vendor);
      setEditorPlatformFamily(selection.platformFamily);
      setEditorVersion(selection.version);
      setEditorCommand(tpl.command);
      setEditorActionCode(json?.data?.action_code || tpl.action_code || '');
      setEditorContent(json?.data?.content || '');
      setSampleOutput('');
      setDefaultSample(json?.data?.default_sample || '');
      setTestResult(null);
      setTestError('');
      setEditorOpen(true);
    } catch {
      showToast('error', isZh ? '加载模板失败' : 'Failed to load template');
    }
  };

  const generateFilename = () => {
    if (!editorPlatform || !editorCommand) return '';
    const cmd = editorCommand.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    return `${editorPlatform}_${cmd}.textfsm`;
  };

  const handleSave = async () => {
    if (!editorContent.trim()) {
      showToast('error', isZh ? '模板内容不能为空' : 'Content cannot be empty');
      return;
    }
    setSaving(true);
    try {
      const filename = editingTemplate?.filename || generateFilename();
      if (!filename) {
        showToast('error', isZh ? '请填写厂商、平台、版本和命令' : 'Vendor, platform, version and command required');
        setSaving(false);
        return;
      }

      const method = editingTemplate ? 'PUT' : 'POST';
      const url = editingTemplate
        ? `/api/textfsm/templates/${editingTemplate.filename}`
        : '/api/textfsm/templates';
      const body = editingTemplate
        ? { content: editorContent, action_code: editorActionCode || null }
        : {
            platform: editorPlatform,
            platform_family: editorPlatformFamily,
            version: editorVersion,
            command: editorCommand,
            action_code: editorActionCode || null,
            content: editorContent,
          };

      const res = await fetch(url, {
        method,
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (res.ok && json.success) {
        showToast('success', isZh ? '模板已保存' : 'Template saved');
        setEditorOpen(false);
        await fetchTemplates();
      } else {
        showToast('error', json.detail || json.message || (isZh ? '保存失败' : 'Save failed'));
      }
    } catch (e) {
      showToast('error', isZh ? '网络错误' : 'Network error');
    }
    setSaving(false);
  };

  const handleTest = async () => {
    if (!editorContent.trim() || !sampleOutput.trim()) {
      setTestError(isZh ? '请提供模板内容和样本输出' : 'Template and sample required');
      return;
    }
    setTesting(true);
    setTestError('');
    setTestResult(null);
    try {
      const res = await fetch('/api/textfsm/test', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editorContent, sample_output: sampleOutput }),
      });
      const json = await res.json();
      if (res.ok && json.success) {
        setTestResult(json.data);
        if (json.data.count === 0) {
          setTestError(json.message || (isZh ? '模板未匹配到任何记录' : 'No records matched'));
        }
      } else {
        setTestError(json.message || (isZh ? '测试失败' : 'Test failed'));
      }
    } catch (e) {
      setTestError(isZh ? '网络错误' : 'Network error');
    }
    setTesting(false);
  };

  const handleDelete = async (tpl: Template) => {
    try {
      const res = await fetch(`/api/textfsm/templates/${tpl.filename}`, {
        method: 'DELETE',
        headers: authHeaders,
      });
      const json = await res.json();
      if (res.ok && json.success) {
        showToast('success', isZh ? '模板已删除' : 'Template deleted');
        setConfirmDelete(null);
        await fetchTemplates();
      } else {
        showToast('error', json.detail || (isZh ? '删除失败' : 'Delete failed'));
      }
    } catch {
      showToast('error', isZh ? '网络错误' : 'Network error');
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      <PageHero
        icon={FileCode}
        title={isZh ? 'TextFSM 解析模板' : 'TextFSM Parse Templates'}
        subtitle={isZh ? '管理设备 CLI 输出解析模板；内置模板可保存为自定义覆盖' : 'Manage CLI output parsing templates; built-ins can be saved as custom overrides'}
        actions={
          <>
            <ActionIconButton
              icon={RefreshCw}
              label={isZh ? '刷新' : 'Refresh'}
              iconClassName={loading ? 'animate-spin' : undefined}
              size="md"
              variant="accent"
              onClick={fetchTemplates}
            />
            <ActionButton icon={Plus} variant="primary" size="sm" onClick={openNewEditor}>
              {isZh ? '新建模板' : 'New Template'}
            </ActionButton>
          </>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 space-y-3 min-h-0">
      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}
            className={`fixed top-20 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl shadow-lg border ${
              toast.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-red-50 border-red-200 text-red-800'
            }`}
          >
            {toast.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span className="text-sm font-medium">{toast.text}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={isZh ? '搜索模板名称或命令...' : 'Search filename or command...'}
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
          />
        </div>
        <select
          value={vendorFilter}
          onChange={(e) => {
            setVendorFilter(e.target.value);
            setPlatformFamilyFilter('');
            setVersionFilter('');
          }}
          aria-label={isZh ? '厂商' : 'Vendor'}
          className="px-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
        >
          <option value="">{isZh ? '全部厂商' : 'All Vendors'}</option>
          {VENDOR_OPTIONS.map((vendor) => (
            <option key={vendor.value} value={vendor.value}>{isZh ? vendor.label : vendor.labelEn}</option>
          ))}
        </select>
        <select
          value={platformFamilyFilter}
          onChange={(e) => {
            setPlatformFamilyFilter(e.target.value);
            setVersionFilter('');
          }}
          aria-label={isZh ? '平台' : 'Platform'}
          className="px-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
        >
          <option value="">{isZh ? '全部平台' : 'All Platforms'}</option>
          {availablePlatformFamilies.map((platform) => (
            <option key={platform.value} value={platform.value}>
              {isZh ? platform.label : platform.labelEn}
            </option>
          ))}
        </select>
        <select
          value={versionFilter}
          onChange={(e) => setVersionFilter(e.target.value)}
          aria-label={isZh ? '版本' : 'Version'}
          className="px-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
        >
          <option value="">{isZh ? '全部版本' : 'All Versions'}</option>
          {availableVersions.map((version) => (
            <option key={version} value={version}>
              {isZh ? (VERSION_LABELS[version]?.label || version) : (VERSION_LABELS[version]?.labelEn || version)}
            </option>
          ))}
        </select>
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as any)}
          className="px-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
        >
          <option value="">{isZh ? '全部来源' : 'All Sources'}</option>
          <option value="builtin">{isZh ? '内置' : 'Built-in'}</option>
          <option value="custom">{isZh ? '自定义' : 'Custom'}</option>
        </select>
      </div>

      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        {/* Templates Table */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          <table className="nx-data-table min-w-[960px] table-fixed">
            <colgroup>
              <col className="w-[30%]" />
              <col className="w-[23%]" />
              <col className="w-[27%]" />
              <col className="w-[12%]" />
              <col className="w-28" />
            </colgroup>
            <thead className="sticky top-0 z-10 border-b border-black/5">
              <tr>
                <th className="text-left px-4 py-2.5">{isZh ? '文件名' : 'Filename'}</th>
                <th className="text-left px-4 py-2.5">{isZh ? '厂商 / 平台 / 版本' : 'Vendor / Platform / Version'}</th>
                <th className="text-left px-4 py-2.5">{isZh ? '命令' : 'Command'}</th>
                <th className="text-left px-4 py-2.5">{isZh ? '来源' : 'Source'}</th>
                <th className="w-28 px-4 py-2.5 text-right" style={{ textAlign: 'right' }}>{isZh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={5} className="text-center py-10 text-black/30"><Loader2 size={20} className="animate-spin inline-block" /></td></tr>
              )}
              {!loading && templates.length === 0 && (
                <tr><td colSpan={5} className="text-center py-10 text-black/30">{isZh ? '没有匹配的模板' : 'No templates found'}</td></tr>
              )}
                {!loading && templates.map((tpl) => (
                <tr key={tpl.filename} className="border-t border-black/[0.03] hover:bg-slate-50/50 transition-colors">
                  <td className="px-4 py-2.5 nx-code-text text-black/70 break-all">{tpl.filename}</td>
                  <td className="px-4 py-2.5">
                    {(() => {
                      const meta = getTemplateDisplayMeta(tpl);
                      return (
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center gap-1 nx-micro-text font-semibold">
                            <span className="rounded bg-cyan-50 px-1.5 py-0.5 text-cyan-700">
                              {isZh ? meta.vendor.label : meta.vendor.labelEn}
                            </span>
                            <span className="text-black/25">/</span>
                            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-black/65">
                              {isZh ? meta.family.label : meta.family.labelEn}
                            </span>
                            <span className="text-black/25">/</span>
                            <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-indigo-700">
                              {isZh ? meta.version.label : meta.version.labelEn}
                            </span>
                          </div>
                          <span className="nx-code-text text-black/35">{tpl.platform}</span>
                        </div>
                      );
                    })()}
                  </td>
                  <td className="px-4 py-2.5 text-black/60">
                    <div>{tpl.command || '—'}</div>
                    {tpl.action_code && <span className="mt-1 inline-flex rounded bg-violet-50 px-1.5 py-0.5 nx-code-text text-violet-700">{tpl.action_code}</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    {tpl.source === 'custom' ? (
                      <span className="nx-micro-text px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-bold">{isZh ? '自定义' : 'Custom'}</span>
                    ) : (
                      <span className="nx-micro-text px-2 py-0.5 rounded-full bg-cyan-100 text-cyan-700 font-bold">{isZh ? '内置' : 'Built-in'}</span>
                    )}
                  </td>
                  <td className="w-28 whitespace-nowrap px-4 py-2.5 text-right">
                    <ActionIconGroup label={isZh ? '模板操作' : 'Template actions'} className="w-full">
                      <ActionIconButton
                        icon={Pencil}
                        label={tpl.source === 'builtin'
                          ? (isZh ? '编辑并创建自定义覆盖' : 'Edit and create a custom override')
                          : (isZh ? '编辑' : 'Edit')}
                        onClick={() => openEditor(tpl)}
                      />
                      {tpl.source === 'custom' && (
                        <ActionIconButton
                          icon={Trash2}
                          label={isZh ? '删除' : 'Delete'}
                          variant="danger"
                          onClick={() => setConfirmDelete(tpl)}
                        />
                      )}
                    </ActionIconGroup>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex-shrink-0">
          <Pagination
            currentPage={page}
            totalItems={total}
            itemsPerPage={pageSize}
            onPageChange={setPage}
            onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
            language={language}
            alwaysVisible
          />
        </div>
      </div>

      {/* Editor Modal */}
      <AnimatePresence>
        {editorOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.97 }}
              className="bg-white rounded-2xl shadow-xl w-full max-w-6xl max-h-[92vh] overflow-hidden flex flex-col"
            >
              <div className="px-5 py-3 border-b border-black/5 flex items-center justify-between bg-slate-50/50">
                <h3 className="text-sm font-bold flex items-center gap-2">
                  <FileCode size={16} className="text-cyan-500" />
                  {editingTemplate
                    ? (isZh ? '编辑模板' : 'Edit Template')
                    : (isZh ? '新建模板' : 'New Template')}
                  {editingTemplate && (
                    <span className="font-mono text-[11px] text-black/40 ml-2">{editingTemplate.filename}</span>
                  )}
                </h3>
                <button onClick={() => setEditorOpen(false)} className="p-1 rounded hover:bg-black/5"><X size={16} /></button>
              </div>

              <div className="flex-1 overflow-y-auto p-5 grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Left: Editor */}
                <div className="flex flex-col gap-3 min-h-0">
                  {editingTemplate?.source === 'builtin' && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50/70 px-3.5 py-2.5 text-[11px] leading-relaxed text-amber-800">
                      {isZh
                        ? '这是内置模板。保存后会在持久化数据目录创建同名的自定义覆盖，不会修改镜像中的内置版本。'
                        : 'This is a built-in template. Saving creates a same-name custom override in persistent data and does not modify the image copy.'}
                    </div>
                  )}
                  {!editingTemplate && (
                    <div className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200/80 bg-slate-50/40 p-3 sm:grid-cols-2 lg:grid-cols-12">
                      <div className="lg:col-span-4">
                        <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider">{isZh ? '厂商' : 'Vendor'}</label>
                        <select
                          value={editorVendor}
                          onChange={(e) => {
                            const nextVendor = e.target.value;
                            setEditorVendor(nextVendor);
                            setEditorPlatformFamily('');
                            setEditorVersion('');
                          }}
                          className="mt-1 h-9 w-full rounded-lg border border-black/10 bg-white px-2.5 text-xs outline-none focus:border-[#00bceb]"
                        >
                          {VENDOR_OPTIONS.map((vendor) => (
                            <option key={vendor.value} value={vendor.value}>{isZh ? vendor.label : vendor.labelEn}</option>
                          ))}
                        </select>
                      </div>
                      <div className="lg:col-span-4">
                        <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider">{isZh ? '平台' : 'Platform'}</label>
                        <select
                          value={editorPlatformFamily}
                          onChange={(e) => {
                            const nextFamily = getPlatformFamilyOption(e.target.value);
                            setEditorPlatformFamily(e.target.value);
                            setEditorVersion(nextFamily?.versions[0] || '');
                          }}
                          className="mt-1 h-9 w-full rounded-lg border border-black/10 bg-white px-2.5 text-xs outline-none focus:border-[#00bceb]"
                        >
                          <option value="" disabled>{isZh ? '请选择平台' : 'Select platform'}</option>
                          {editorPlatformFamilies.map((platform) => (
                            <option key={platform.value} value={platform.value}>{isZh ? platform.label : platform.labelEn}</option>
                          ))}
                        </select>
                      </div>
                      {editorPlatformFamily && (
                        <div className="lg:col-span-4">
                          <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider">{isZh ? '版本' : 'Version'}</label>
                          <select
                            value={editorVersion}
                            onChange={(e) => setEditorVersion(e.target.value)}
                            className="mt-1 h-9 w-full rounded-lg border border-black/10 bg-white px-2.5 text-xs outline-none focus:border-[#00bceb]"
                          >
                            {editorVersionOptions.map((version) => (
                              <option key={version} value={version}>
                                {isZh ? (VERSION_LABELS[version]?.label || version) : (VERSION_LABELS[version]?.labelEn || version)}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                      <div className="lg:col-span-7">
                        <label className="flex items-center gap-1.5 text-[11px] font-semibold text-black/50 uppercase tracking-wider">
                          <span>{isZh ? '关联 Action' : 'Action'}</span>
                          <span className="rounded-full bg-slate-200/70 px-1.5 py-0.5 text-[9px] font-medium normal-case tracking-normal text-black/40">
                            {isZh ? '可选' : 'Optional'}
                          </span>
                        </label>
                        <select
                          value={editorActionCode}
                          disabled={actionOptionsLoading}
                          onChange={(event) => {
                            const nextActionCode = event.target.value;
                            const selectedAction = actionOptions.find((option) => option.action_code === nextActionCode);
                            setEditorActionCode(nextActionCode);
                            if (selectedAction?.command) setEditorCommand(selectedAction.command);
                          }}
                          className="mt-1.5 h-9 w-full rounded-lg border border-black/10 bg-white px-2.5 text-xs outline-none focus:border-[#00bceb] disabled:bg-slate-50"
                        >
                          <option value="">{actionOptionsLoading ? (isZh ? '加载动作中…' : 'Loading actions…') : (isZh ? '不关联 Action' : 'No action')}</option>
                          {actionOptionGroups.map(([group, options]) => (
                            <optgroup key={group} label={group}>
                              {options.map((option) => (
                                <option key={option.action_code} value={option.action_code}>
                                  {isZh ? option.name_zh : option.name_en} · {option.action_code}
                                </option>
                              ))}
                            </optgroup>
                          ))}
                        </select>
                        {editorActionCode && (
                          <div className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[10px] text-cyan-700/70">
                            <span className="shrink-0 text-black/35">{isZh ? '命令' : 'Command'}</span>
                            <code className="truncate rounded bg-cyan-50 px-1.5 py-0.5 font-mono text-[10px] text-cyan-800/80">
                              {actionOptions.find((option) => option.action_code === editorActionCode)?.command || (isZh ? '未配置平台命令' : 'No platform command configured')}
                            </code>
                          </div>
                        )}
                      </div>
                      <div className="lg:col-span-5">
                        <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider">{isZh ? '命令' : 'Command'}</label>
                        <input
                          value={editorCommand}
                          onChange={(e) => setEditorCommand(e.target.value)}
                          placeholder="show processes cpu"
                          className="mt-1 h-9 w-full rounded-lg border border-black/10 bg-white px-2.5 text-xs outline-none focus:border-[#00bceb]"
                        />
                      </div>
                    </div>
                  )}

                  {!editingTemplate && generateFilename() && (
                    <div className="space-y-1 text-[11px] text-black/40">
                      <div>
                        {isZh ? '文件名:' : 'Filename:'} <span className="font-mono text-black/60">{generateFilename()}</span>
                      </div>
                      <div className="text-[10px] text-cyan-700/70">
                        {isZh
                          ? '保存后直接加入模板列表；Action 关联是可选元数据，测试解析仅用于预览，不是保存前置条件。'
                          : 'The template is saved directly; Action association is optional metadata, and parse testing is a preview, not a save prerequisite.'}
                      </div>
                    </div>
                  )}

                  <div className="flex-1 flex flex-col min-h-0">
                    <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider mb-1">
                      {isZh ? '模板内容' : 'Template Content'}
                    </label>
                    <textarea
                      value={editorContent}
                      onChange={(e) => setEditorContent(e.target.value)}
                      className="flex-1 min-h-[280px] font-mono text-[12px] leading-5 p-3 rounded-lg border border-black/10 bg-white focus:outline-none focus:border-[#00bceb]"
                      spellCheck={false}
                    />
                  </div>
                </div>

                {/* Right: Test */}
                <div className="flex flex-col gap-3 min-h-0">
                  {defaultSample && (
                    <div className="rounded-xl border border-cyan-500/15 bg-[#f0f9ff]/70 p-3.5 shadow-sm">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-700">
                          {isZh ? '系统内置参考回显样本' : 'Builtin Reference Example Output'}
                        </span>
                        <button
                          onClick={() => setSampleOutput(defaultSample)}
                          className="rounded bg-cyan-600 px-2 py-0.5 text-[9px] font-bold text-white hover:bg-cyan-700 transition-all"
                        >
                          {isZh ? '一键填充到测试框' : 'Use Reference'}
                        </button>
                      </div>
                      <pre className="font-mono text-[10px] text-slate-600 bg-white/70 p-2.5 rounded-lg border border-cyan-200 overflow-x-auto max-h-[85px] leading-relaxed">
                        {defaultSample}
                      </pre>
                    </div>
                  )}

                  <div className="flex-1 flex flex-col min-h-0">
                    <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider mb-1">
                      {isZh ? '样本输出 (我实际输入的测试样本)' : 'Sample Output (My actual test output)'}
                    </label>
                    <textarea
                      value={sampleOutput}
                      onChange={(e) => setSampleOutput(e.target.value)}
                      placeholder={isZh ? '粘贴设备真实 CLI 输出...' : 'Paste real CLI output from device...'}
                      className="flex-1 min-h-[140px] font-mono text-[11px] leading-5 p-3 rounded-lg border border-black/10 bg-white focus:outline-none focus:border-[#00bceb]"
                      spellCheck={false}
                    />
                  </div>

                  <button
                    onClick={handleTest}
                    disabled={testing}
                    className="flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-xs font-semibold disabled:opacity-50"
                  >
                    {testing ? <Loader2 size={13} className="animate-spin" /> : <PlayCircle size={13} />}
                    {isZh ? '测试解析' : 'Test Parse'}
                  </button>

                  <div className="flex-1 flex flex-col min-h-0">
                    <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider mb-1">
                      {isZh ? '解析结果' : 'Parse Result'}
                    </label>
                    <div className="flex-1 min-h-[140px] rounded-lg border border-black/10 bg-slate-50 p-3 overflow-auto">
                      {testError && (
                        <div className="text-xs text-red-600 flex items-start gap-2">
                          <AlertCircle size={14} className="shrink-0 mt-0.5" />
                          <span>{testError}</span>
                        </div>
                      )}
                      {testResult && testResult.count > 0 && (
                        <>
                          <div className="text-[11px] text-emerald-600 font-semibold mb-2">
                            ✓ {isZh ? `解析出 ${testResult.count} 条记录，字段: ${testResult.fields.join(', ')}` : `Parsed ${testResult.count} record(s), fields: ${testResult.fields.join(', ')}`}
                          </div>
                          <pre className="font-mono text-[11px] text-black/70 whitespace-pre-wrap">
                            {JSON.stringify(testResult.records, null, 2)}
                          </pre>
                        </>
                      )}
                      {!testResult && !testError && (
                        <div className="text-xs text-black/30 text-center py-6">
                          {isZh ? '粘贴样本输出后点击"测试解析"' : 'Paste sample output and click "Test Parse"'}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="px-5 py-3 border-t border-black/5 bg-slate-50/50 flex justify-end gap-2">
                <button
                  onClick={() => setEditorOpen(false)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold text-black/60 hover:bg-black/5"
                >
                  {isZh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#00bceb] text-white text-xs font-semibold hover:bg-[#00a5d0] disabled:opacity-50"
                >
                  {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                  {isZh ? '保存模板' : 'Save Template'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Delete Confirm */}
      <AnimatePresence>
        {confirmDelete && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden"
            >
              <div className="p-5">
                <div className="flex items-center gap-3 mb-3 text-red-600">
                  <AlertCircle size={22} />
                  <h3 className="text-base font-bold">{isZh ? '确认删除' : 'Confirm Delete'}</h3>
                </div>
                <p className="text-sm text-black/60 mb-2">
                  {isZh ? '确定删除以下自定义模板？此操作不可恢复。' : 'Delete this custom template? This cannot be undone.'}
                </p>
                <p className="font-mono text-xs bg-slate-50 px-3 py-2 rounded mb-4">{confirmDelete.filename}</p>
              </div>
              <div className="px-5 py-3 bg-slate-50/50 border-t border-black/5 flex justify-end gap-2">
                <button
                  onClick={() => setConfirmDelete(null)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold text-black/60 hover:bg-black/5"
                >
                  {isZh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={() => handleDelete(confirmDelete)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold bg-red-500 text-white hover:bg-red-600 shadow-sm"
                >
                  {isZh ? '确认删除' : 'Delete'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      </div>
    </div>
  );
};

export default TextFSMTemplatesTab;
