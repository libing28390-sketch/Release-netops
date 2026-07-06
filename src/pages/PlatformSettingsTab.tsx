import React, { useState, useMemo, useRef } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Code2,
  Copy,
  Download,
  FileCog,
  FileText,
  FolderOpen,
  Layers,
  Play,
  Plus,
  Rocket,
  Search,
  Send,
  Server,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import type { ConfigTemplate, Device } from '../types';
import PageHero from '../components/PageHero';

type ConfigWorkspaceView = 'source' | 'rendered' | 'checks';
type TemplateType = 'Jinja2' | 'YAML';
type ToastTone = 'success' | 'error' | 'warning' | 'info';

interface GlobalVarItem {
  id?: string;
  key: string;
  value: string;
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

/** Visual brand metadata per vendor. Used to colorize template cards. */
const VENDOR_BRAND: Record<string, { label: string; gradient: string; border: string; chip: string; icon: string }> = {
  Cisco:   { label: 'Cisco',   gradient: 'from-[#049fd9] to-[#00bceb]', border: 'border-[#049fd9]/30', chip: 'bg-[#049fd9]/10 text-[#067db5]',  icon: '🅒' },
  Juniper: { label: 'Juniper', gradient: 'from-[#10b981] to-[#059669]', border: 'border-emerald-500/30', chip: 'bg-emerald-50 text-emerald-700', icon: 'Ⓙ' },
  Huawei:  { label: 'Huawei',  gradient: 'from-[#e60012] to-[#c41428]', border: 'border-rose-500/30',  chip: 'bg-rose-50 text-rose-700',       icon: 'Ⓗ' },
  H3C:     { label: 'H3C',     gradient: 'from-[#d4a017] to-[#b8860b]', border: 'border-amber-500/30', chip: 'bg-amber-50 text-amber-700',     icon: '③' },
  Arista:  { label: 'Arista',  gradient: 'from-[#fb923c] to-[#ea580c]', border: 'border-orange-500/30',chip: 'bg-orange-50 text-orange-700',   icon: 'Ⓐ' },
  Ruijie:  { label: 'Ruijie',  gradient: 'from-[#7c3aed] to-[#6d28d9]', border: 'border-violet-500/30',chip: 'bg-violet-50 text-violet-700',   icon: 'Ⓡ' },
  Other:   { label: 'Other',   gradient: 'from-slate-500 to-slate-700', border: 'border-slate-400/30',  chip: 'bg-slate-100 text-slate-700',    icon: '◯' },
  Custom:  { label: 'Custom',  gradient: 'from-slate-400 to-slate-600', border: 'border-slate-300/40',  chip: 'bg-slate-100 text-slate-600',    icon: '✎' },
};

function vendorBrand(name?: string) {
  if (!name) return VENDOR_BRAND.Custom;
  return VENDOR_BRAND[name] || VENDOR_BRAND.Custom;
}

const PlatformSettingsTab: React.FC<PlatformSettingsTabProps> = ({
  t,
  language,
  sectionHeaderRowClass,
  configTemplates,
  configVariableKeys,
  configMissingVariables,
  configScopedDevices,
  configScopedOnlineCount,
  configReadinessScore,
  configValidationIssues,
  configValidationWarnings,
  configWorkspaceView,
  selectedTemplateId,
  selectedConfigTemplate,
  globalVars,
  editorContent,
  configRenderedPreview,
  configScopePlatform,
  configScopeRole,
  configScopeSite,
  configPlatformOptions,
  configRoleOptions,
  configSiteOptions,
  extractVars,
  getPlatformLabel,
  onImportVars,
  onCreateTemplate,
  onSelectTemplateIdChange,
  onAddVar,
  onDeleteVar,
  onSelectedTemplateNameChange,
  onSelectedTemplateVendorChange,
  onSelectedTemplateTypeChange,
  onDiscardChanges,
  onConfigWorkspaceViewChange,
  onValidate,
  onSaveTemplate,
  onCreateScenarioDraft,
  onSendToAutomation,
  onEditorContentChange,
  onConfigScopePlatformChange,
  onConfigScopeRoleChange,
  onConfigScopeSiteChange,
  showToast,
}) => {
  const zh = language === 'zh';
  const [tplSearch, setTplSearch] = useState('');
  const [tplVendorFilter, setTplVendorFilter] = useState<string>('all');
  const [showSidebar, setShowSidebar] = useState<'scope' | 'vars' | null>(null);
  const lineNumRef = useRef<HTMLDivElement>(null);

  /* ── Derived lists ─────────────────────────────────────── */

  const vendorList = useMemo(() => {
    const vendors = new Set<string>();
    configTemplates.forEach((tpl) => vendors.add(tpl.vendor || 'Custom'));
    return Array.from(vendors).sort();
  }, [configTemplates]);

  // Templates matching the free-text search (used for both vendor-chip counts
  // and the final rendered list, so counts stay consistent with what the user sees).
  const searchedTemplates = useMemo(() => {
    if (!tplSearch.trim()) return configTemplates;
    const q = tplSearch.trim().toLowerCase();
    return configTemplates.filter(
      (tpl) =>
        tpl.name.toLowerCase().includes(q) ||
        (tpl.vendor || 'Custom').toLowerCase().includes(q)
    );
  }, [configTemplates, tplSearch]);

  const filteredTemplates = useMemo(() => {
    if (tplVendorFilter === 'all') return searchedTemplates;
    return searchedTemplates.filter((tpl) => (tpl.vendor || 'Custom') === tplVendorFilter);
  }, [searchedTemplates, tplVendorFilter]);

  const vendorCounts = useMemo(() => {
    const map = new Map<string, number>();
    searchedTemplates.forEach((tpl) => {
      const v = tpl.vendor || 'Custom';
      map.set(v, (map.get(v) || 0) + 1);
    });
    return map;
  }, [searchedTemplates]);

  const templateVarsMap = useMemo(() => {
    const map = new Map<string, string[]>();
    configTemplates.forEach((tpl) => map.set(tpl.id, extractVars(tpl.content)));
    return map;
  }, [configTemplates, extractVars]);

  const officialCount = useMemo(
    () => configTemplates.filter((tpl) => tpl.category === 'official').length,
    [configTemplates]
  );
  const customCount = configTemplates.length - officialCount;

  /* ── Download rendered as .txt ─────────────────────────── */
  const handleDownloadRendered = () => {
    if (!configRenderedPreview) return;
    const blob = new Blob([configRenderedPreview], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const name = (selectedConfigTemplate?.name || 'config')
      .replace(/[^a-zA-Z0-9_-]+/g, '_');
    a.href = url;
    a.download = `${name}_rendered.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 200);
  };

  /* ── Render ────────────────────────────────────────────── */

  const readinessColor =
    configReadinessScore >= 85
      ? 'text-emerald-600'
      : configReadinessScore >= 60
      ? 'text-amber-600'
      : 'text-rose-600';

  return (
    <div className="h-full flex flex-col overflow-hidden bg-gradient-to-br from-slate-50 to-cyan-50/30">
      <PageHero
        icon={FileCog}
        title={t('configManagement')}
        subtitle={zh
          ? '多厂商网络设备配置模板 · 渲染预览 · 发布范围与下发'
          : 'Multi-vendor network config templates · Render · Scope · Deploy'}
        actions={
          <>
            <label className="cursor-pointer px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm font-semibold text-slate-600 hover:border-[#06b6d4] hover:text-[#0891b2] transition-all flex items-center gap-2 shadow-sm">
              <Upload size={15} />
              {t('importVars')}
              <input type="file" className="hidden" accept=".xlsx, .xls, .csv" onChange={(e) => { onImportVars(e); e.target.value = ''; }} />
            </label>
            <button
              onClick={onCreateTemplate}
              className="bg-gradient-to-r from-[#06b6d4] to-[#0891b2] text-white px-5 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 hover:shadow-lg hover:shadow-cyan-500/30 transition-all"
            >
              <Plus size={16} />
              {t('newTemplate')}
            </button>
          </>
        }
      />

      <div className="flex-1 flex flex-col gap-4 overflow-hidden px-6 py-5">
      {/* ═════════ METRICS STRIP ═════════ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 flex-shrink-0">
        <MetricCard
          icon={<FolderOpen size={16} />}
          tone="slate"
          label={zh ? '模板资产' : 'Template Assets'}
          value={String(configTemplates.length)}
          sub={zh ? `官方 ${officialCount} · 自定义 ${customCount}` : `${officialCount} official · ${customCount} custom`}
        />
        <MetricCard
          icon={<Sparkles size={16} />}
          tone={configMissingVariables.length === 0 ? 'emerald' : 'amber'}
          label={zh ? '变量完备度' : 'Variable Coverage'}
          value={`${configVariableKeys.length - configMissingVariables.length}/${configVariableKeys.length || 0}`}
          sub={
            configMissingVariables.length === 0
              ? (zh ? '已全部赋值' : 'All variables set')
              : (zh ? `缺失 ${configMissingVariables.length} 个` : `${configMissingVariables.length} missing`)
          }
        />
        <MetricCard
          icon={<Server size={16} />}
          tone="cyan"
          label={zh ? '匹配设备' : 'Target Devices'}
          value={String(configScopedDevices.length)}
          sub={zh ? `${configScopedOnlineCount} 台在线` : `${configScopedOnlineCount} online`}
        />
        <MetricCard
          icon={<ShieldCheck size={16} />}
          tone={configReadinessScore >= 85 ? 'emerald' : configReadinessScore >= 60 ? 'amber' : 'rose'}
          label={zh ? '发布就绪度' : 'Release Readiness'}
          value={`${configReadinessScore}`}
          sub={
            configValidationIssues.length === 0
              ? (zh ? '基础校验已通过' : 'Checks passed')
              : (zh ? `${configValidationIssues.length} 个阻断项` : `${configValidationIssues.length} blocking`)
          }
        />
      </div>

      {/* ═════════ MAIN WORKSPACE ═════════ */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-4 overflow-hidden">
        {/* ═════ LEFT: Template Library ═════ */}
        <aside className="lg:col-span-3 min-h-0 bg-white rounded-2xl border border-slate-200 shadow-sm flex flex-col overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 bg-gradient-to-br from-slate-50 to-white">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Layers size={15} className="text-[#06b6d4]" />
                <h3 className="text-sm font-bold text-[#0f172a]">{zh ? '模板库' : 'Template Library'}</h3>
              </div>
              <span className="text-[10px] font-bold text-slate-400 px-2 py-0.5 rounded-full bg-slate-100">
                {filteredTemplates.length}
              </span>
            </div>
            <div className="mt-3 relative">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={tplSearch}
                onChange={(e) => setTplSearch(e.target.value)}
                placeholder={zh ? '搜索模板或厂商...' : 'Search templates or vendors...'}
                className="w-full pl-9 pr-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg outline-none focus:border-[#06b6d4] focus:bg-white focus:shadow-[0_0_0_3px_rgba(6,182,212,0.1)] transition-all placeholder:text-slate-400"
              />
            </div>
            {/* Vendor chips */}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button
                onClick={() => setTplVendorFilter('all')}
                className={`text-[10px] font-bold px-2 py-1 rounded-full transition-all ${
                  tplVendorFilter === 'all'
                    ? 'bg-[#0f172a] text-white'
                    : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                }`}
              >
                {zh ? '全部' : 'All'} · {searchedTemplates.length}
              </button>
              {vendorList.map((vendor) => {
                const brand = vendorBrand(vendor);
                const count = vendorCounts.get(vendor) || 0;
                // When the user types a search, hide vendors with zero matches
                // to avoid the "Arista · 5" lie shown during search.
                if (tplSearch.trim() && count === 0) return null;
                const isActive = tplVendorFilter === vendor;
                return (
                  <button
                    key={vendor}
                    onClick={() => setTplVendorFilter(vendor)}
                    className={`text-[10px] font-bold px-2 py-1 rounded-full transition-all ${
                      isActive
                        ? `bg-gradient-to-r ${brand.gradient} text-white shadow-sm`
                        : `${brand.chip} hover:ring-1 hover:ring-slate-300`
                    }`}
                  >
                    {vendor} · {count}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex-1 overflow-auto p-3 space-y-2">
            {filteredTemplates.length === 0 ? (
              <div className="py-10 text-center text-xs text-slate-300 italic">
                {zh ? '没有匹配的模板' : 'No matching templates'}
              </div>
            ) : (
              filteredTemplates.map((tpl) => {
                const brand = vendorBrand(tpl.vendor || 'Custom');
                const templateVars = templateVarsMap.get(tpl.id) || [];
                const isSelected = selectedTemplateId === tpl.id;
                return (
                  <button
                    key={tpl.id}
                    onClick={() => onSelectTemplateIdChange(tpl.id)}
                    className={`w-full text-left rounded-xl border transition-all overflow-hidden group ${
                      isSelected
                        ? `border-transparent shadow-lg ring-2 ring-[#06b6d4]/40`
                        : `${brand.border} bg-white hover:border-slate-300 hover:shadow-sm`
                    }`}
                  >
                    <div
                      className={`h-1 bg-gradient-to-r ${brand.gradient} ${isSelected ? 'opacity-100' : 'opacity-70'}`}
                    />
                    <div className="p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${brand.chip}`}>
                              {tpl.vendor || 'Custom'}
                            </span>
                            {tpl.category === 'official' && (
                              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-bold uppercase bg-blue-50 text-blue-700 border border-blue-100">
                                {t('official')}
                              </span>
                            )}
                          </div>
                          <p className="mt-1.5 text-sm font-bold text-[#0f172a] truncate">{tpl.name}</p>
                          <p className="mt-0.5 text-[10px] text-slate-400">
                            {zh ? `最近使用 ${tpl.lastUsed}` : `Last used ${tpl.lastUsed}`}
                          </p>
                        </div>
                        <span className="text-[9px] font-bold uppercase text-slate-400 tracking-wider">
                          {tpl.type}
                        </span>
                      </div>
                      <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-50 text-slate-500">
                          {templateVars.length} {zh ? '变量' : 'vars'}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* ═════ RIGHT: Editor / Rendered / Checks ═════ */}
        <section className="lg:col-span-9 min-h-0 bg-white rounded-2xl border border-slate-200 shadow-sm flex flex-col overflow-hidden">
          {/* Top bar: template header */}
          <div className="px-5 py-4 border-b border-slate-100 bg-gradient-to-br from-slate-50 to-white flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 flex-1 min-w-[260px]">
              <div
                className={`w-9 h-9 rounded-xl flex items-center justify-center text-white font-bold text-sm bg-gradient-to-br ${vendorBrand(selectedConfigTemplate?.vendor).gradient} shadow-sm`}
              >
                {selectedConfigTemplate?.vendor ? selectedConfigTemplate.vendor.slice(0, 2).toUpperCase() : '✎'}
              </div>
              <input
                type="text"
                value={selectedConfigTemplate?.name || ''}
                title={zh ? '模板名称' : 'Template name'}
                onChange={(event) => onSelectedTemplateNameChange(event.target.value)}
                className="flex-1 min-w-0 bg-transparent px-3 py-2 rounded-xl text-base font-bold text-[#0f172a] border border-transparent hover:border-slate-200 focus:border-[#06b6d4] focus:bg-white outline-none transition-all"
                placeholder={zh ? '模板名称' : 'Template name'}
              />
            </div>
            <div className="flex items-center gap-2">
              <select
                value={selectedConfigTemplate?.vendor || 'Custom'}
                title={zh ? '模板厂商' : 'Template vendor'}
                onChange={(event) => onSelectedTemplateVendorChange(event.target.value)}
                className="text-xs font-bold px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg outline-none cursor-pointer hover:bg-white hover:border-[#06b6d4] transition-all"
              >
                {['Cisco', 'Juniper', 'Huawei', 'H3C', 'Arista', 'Ruijie', 'Other', 'Custom'].map((vendor) => (
                  <option key={vendor} value={vendor}>{vendor}</option>
                ))}
              </select>
              <select
                value={selectedConfigTemplate?.type || 'Jinja2'}
                title={zh ? '模板类型' : 'Template type'}
                onChange={(event) => onSelectedTemplateTypeChange(event.target.value as TemplateType)}
                className="text-xs font-bold px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg outline-none cursor-pointer hover:bg-white hover:border-[#06b6d4] transition-all"
              >
                <option value="Jinja2">Jinja2</option>
                <option value="YAML">YAML</option>
              </select>
              <div className="w-px h-6 bg-slate-200" />
              <button
                onClick={onDiscardChanges}
                className="px-3 py-2 text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-all"
              >
                {t('discard')}
              </button>
              <button
                onClick={onSaveTemplate}
                className="px-3 py-2 text-xs font-bold text-[#0891b2] hover:bg-cyan-50 rounded-lg transition-all"
              >
                {t('saveChanges')}
              </button>
            </div>
          </div>

          {/* View tabs + action row */}
          <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between gap-3 flex-wrap">
            <div className="inline-flex p-1 rounded-xl bg-slate-100">
              {[
                { key: 'source', label: zh ? '源模板' : 'Source', icon: <Code2 size={13} /> },
                { key: 'rendered', label: zh ? '渲染结果' : 'Rendered', icon: <Play size={13} /> },
                { key: 'checks', label: zh ? '发布检查' : 'Preflight', icon: <ShieldCheck size={13} /> },
              ].map((tab) => {
                const active = configWorkspaceView === tab.key;
                return (
                  <button
                    key={tab.key}
                    onClick={() => onConfigWorkspaceViewChange(tab.key as ConfigWorkspaceView)}
                    className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      active
                        ? 'bg-white text-[#0f172a] shadow-sm'
                        : 'text-slate-500 hover:text-[#0f172a]'
                    }`}
                  >
                    {tab.icon}
                    {tab.label}
                  </button>
                );
              })}
            </div>
            <div className="flex items-center gap-2">
              <SidebarToggle
                active={showSidebar === 'scope'}
                onClick={() => setShowSidebar(showSidebar === 'scope' ? null : 'scope')}
                icon={<Server size={13} />}
                label={zh ? '发布范围' : 'Scope'}
                badge={configScopedDevices.length}
              />
              <SidebarToggle
                active={showSidebar === 'vars'}
                onClick={() => setShowSidebar(showSidebar === 'vars' ? null : 'vars')}
                icon={<Sparkles size={13} />}
                label={zh ? '变量' : 'Variables'}
                badge={globalVars.length}
              />
              <div className="w-px h-5 bg-slate-200 mx-1" />
              <button
                onClick={onValidate}
                className="px-3 py-1.5 text-xs font-bold text-[#0891b2] border border-[#06b6d4]/30 bg-cyan-50 rounded-lg hover:bg-cyan-100 transition-all flex items-center gap-1.5"
              >
                <ShieldCheck size={13} />
                {zh ? '检查' : 'Preflight'}
              </button>
              <button
                onClick={onCreateScenarioDraft}
                className="px-3 py-1.5 text-xs font-bold text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-all"
              >
                {zh ? '转草稿' : 'To Draft'}
              </button>
              <button
                onClick={onSendToAutomation}
                className="px-4 py-1.5 bg-gradient-to-r from-[#06b6d4] to-[#0891b2] text-white rounded-lg text-xs font-bold hover:shadow-lg hover:shadow-cyan-500/30 transition-all flex items-center gap-1.5"
              >
                <Rocket size={13} />
                {zh ? '提交下发' : 'Deploy'}
              </button>
            </div>
          </div>

          {/* Missing vars banner */}
          {configMissingVariables.length > 0 && (
            <div className="px-5 py-2.5 bg-amber-50 border-b border-amber-200 flex items-center gap-2 text-[11px] text-amber-900">
              <AlertTriangle size={13} className="flex-shrink-0" />
              <span>
                {zh
                  ? `尚有 ${configMissingVariables.length} 个变量未赋值：${configMissingVariables.slice(0, 5).join('、')}${configMissingVariables.length > 5 ? ' ...' : ''}`
                  : `${configMissingVariables.length} variables missing: ${configMissingVariables.slice(0, 5).join(', ')}${configMissingVariables.length > 5 ? ' ...' : ''}`}
              </span>
            </div>
          )}

          {/* Content area — flex 1, optional sidebar on right */}
          <div className="flex-1 min-h-0 flex overflow-hidden">
            <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
              {configWorkspaceView === 'source' && (
                <div className="flex-1 min-h-0 flex bg-[#1E1E1E] overflow-hidden">
                  <div
                    ref={lineNumRef}
                    className="w-12 py-6 bg-black/30 text-white/30 select-none text-right pr-3 font-mono text-sm leading-6 overflow-hidden"
                  >
                    {editorContent.split('\n').map((_, index) => <div key={index}>{index + 1}</div>)}
                  </div>
                  <textarea
                    value={editorContent}
                    onChange={(event) => onEditorContentChange(event.target.value)}
                    onScroll={(e) => { if (lineNumRef.current) lineNumRef.current.scrollTop = e.currentTarget.scrollTop; }}
                    title={zh ? '模板源码编辑器' : 'Template source editor'}
                    placeholder={zh ? '在这里编辑模板源码' : 'Edit template source here'}
                    className="flex-1 p-6 bg-transparent font-mono text-sm text-[#D4D4D4] outline-none resize-none leading-6"
                    spellCheck={false}
                  />
                </div>
              )}

              {configWorkspaceView === 'rendered' && (
                <div className="flex-1 min-h-0 overflow-auto bg-[#0f172a] text-[#e2e8f0] font-mono text-sm leading-6 p-6">
                  <div className="mb-4 flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <p className="text-xs uppercase tracking-widest text-white/40 font-bold">
                        {zh ? '渲染结果' : 'Rendered Output'}
                      </p>
                      <p className="mt-1 text-[11px] text-white/50">
                        {zh ? '模板应用全局变量后的纯文本结果，不连接设备。' : 'Template output after variable substitution. No device connection.'}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(configRenderedPreview || '');
                          showToast(t('copied'), 'success');
                        }}
                        disabled={!configRenderedPreview}
                        className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold text-white/70 hover:text-white hover:bg-white/5 disabled:opacity-30 flex items-center gap-1.5 transition-all"
                      >
                        <Copy size={12} />
                        {zh ? '复制' : 'Copy'}
                      </button>
                      <button
                        onClick={handleDownloadRendered}
                        disabled={!configRenderedPreview}
                        className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold text-white/70 hover:text-white hover:bg-white/5 disabled:opacity-30 flex items-center gap-1.5 transition-all"
                      >
                        <Download size={12} />
                        {zh ? '下载' : 'Download'}
                      </button>
                    </div>
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-[13px] leading-[1.7]">
                    {configRenderedPreview || (
                      <span className="text-white/30 italic">{zh ? '暂无内容' : 'No content to render'}</span>
                    )}
                  </pre>
                </div>
              )}

              {configWorkspaceView === 'checks' && (
                <div className="flex-1 min-h-0 overflow-auto p-5 bg-slate-50/80 space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Blocking */}
                    <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
                      <div className="flex items-center gap-2 mb-4">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${configValidationIssues.length === 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'}`}>
                          <ShieldCheck size={15} />
                        </div>
                        <div>
                          <h3 className="text-sm font-bold text-[#0f172a]">{zh ? '阻断项' : 'Blocking'}</h3>
                          <p className="text-[11px] text-slate-400">{zh ? '必须解决后才能下发' : 'Must resolve before deploying'}</p>
                        </div>
                        <span className={`ml-auto text-[10px] font-bold px-2 py-0.5 rounded-full ${configValidationIssues.length === 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
                          {configValidationIssues.length}
                        </span>
                      </div>
                      <div className="space-y-2">
                        {configValidationIssues.length === 0 ? (
                          <div className="flex items-start gap-2 text-sm text-emerald-700">
                            <CheckCircle2 size={15} className="mt-0.5 flex-shrink-0" />
                            <span>{zh ? '全部通过，可以执行发布。' : 'All checks passed. Release is ready.'}</span>
                          </div>
                        ) : configValidationIssues.map((issue) => (
                          <div key={issue} className="flex items-start gap-2 text-sm text-rose-700 bg-rose-50/50 rounded-lg px-3 py-2">
                            <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                            <span>{issue}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    {/* Advisories */}
                    <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
                      <div className="flex items-center gap-2 mb-4">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${configValidationWarnings.length === 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                          <AlertCircle size={15} />
                        </div>
                        <div>
                          <h3 className="text-sm font-bold text-[#0f172a]">{zh ? '建议项' : 'Advisories'}</h3>
                          <p className="text-[11px] text-slate-400">{zh ? '可以继续，但建议关注' : 'Not blocking, worth reviewing'}</p>
                        </div>
                        <span className={`ml-auto text-[10px] font-bold px-2 py-0.5 rounded-full ${configValidationWarnings.length === 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                          {configValidationWarnings.length}
                        </span>
                      </div>
                      <div className="space-y-2">
                        {configValidationWarnings.length === 0 ? (
                          <div className="flex items-start gap-2 text-sm text-slate-600">
                            <CheckCircle2 size={15} className="mt-0.5 flex-shrink-0 text-emerald-500" />
                            <span>{zh ? '没有额外建议。' : 'No additional advisories.'}</span>
                          </div>
                        ) : configValidationWarnings.map((warning) => (
                          <div key={warning} className="flex items-start gap-2 text-sm text-amber-700 bg-amber-50/50 rounded-lg px-3 py-2">
                            <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                            <span>{warning}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Release Flow */}
                  <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
                    <div className="flex items-center gap-2 mb-4">
                      <div className="w-8 h-8 rounded-lg bg-cyan-50 text-cyan-600 flex items-center justify-center">
                        <Send size={15} />
                      </div>
                      <div>
                        <h3 className="text-sm font-bold text-[#0f172a]">{zh ? '推荐发布流程' : 'Recommended Release Flow'}</h3>
                        <p className="text-[11px] text-slate-400">
                          {zh ? '先小范围验证 → 再批量下发 → 最后核对结果' : 'Canary first → bulk deploy → verify outcomes'}
                        </p>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                      {[
                        { n: '1', t: zh ? '锁定模板与变量' : 'Freeze template & vars' },
                        { n: '2', t: zh ? '按平台/角色/站点筛目标' : 'Scope by platform/role/site' },
                        { n: '3', t: zh ? '挑 1 台在线设备做 canary' : 'Canary on 1 online device' },
                        { n: '4', t: zh ? '批量下发并核对结果' : 'Bulk deploy & verify' },
                      ].map((s) => (
                        <div key={s.n} className="rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white px-3 py-3">
                          <div className="w-6 h-6 rounded-full bg-[#0f172a] text-white text-[10px] font-black flex items-center justify-center mb-2">
                            {s.n}
                          </div>
                          <p className="text-xs font-semibold text-slate-700 leading-snug">{s.t}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Readiness Summary */}
                  <div className="bg-gradient-to-br from-[#0f172a] to-[#1e293b] rounded-2xl p-6 text-white flex items-center gap-5 shadow-lg">
                    <div className="w-20 h-20 rounded-full bg-white/5 border-4 border-white/10 flex items-center justify-center">
                      <span className={`text-3xl font-black ${readinessColor}`}>{configReadinessScore}</span>
                    </div>
                    <div className="flex-1">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-white/40">
                        {zh ? '发布就绪度' : 'Release Readiness'}
                      </p>
                      <p className="mt-1 text-lg font-bold">
                        {configReadinessScore >= 85
                          ? (zh ? '可以发布' : 'Ready to deploy')
                          : configReadinessScore >= 60
                          ? (zh ? '基本就绪，建议复核' : 'Mostly ready, review first')
                          : (zh ? '暂不建议发布' : 'Not ready for release')}
                      </p>
                      <p className="mt-1 text-[11px] text-white/50">
                        {zh
                          ? `已匹配 ${configScopedDevices.length} 台设备（${configScopedOnlineCount} 在线）`
                          : `${configScopedDevices.length} matched (${configScopedOnlineCount} online)`}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ═════ SIDE DRAWER (scope / vars) ═════ */}
            {showSidebar && (
              <aside className="w-80 border-l border-slate-100 bg-slate-50/60 flex flex-col overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between bg-white">
                  <div className="flex items-center gap-2">
                    {showSidebar === 'scope' ? <Server size={14} className="text-[#06b6d4]" /> : <Sparkles size={14} className="text-[#06b6d4]" />}
                    <h4 className="text-sm font-bold text-[#0f172a]">
                      {showSidebar === 'scope'
                        ? (zh ? '发布范围' : 'Release Scope')
                        : (zh ? '全局变量' : 'Global Variables')}
                    </h4>
                  </div>
                  <button
                    onClick={() => setShowSidebar(null)}
                    className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-all"
                    title={zh ? '关闭' : 'Close'}
                  >
                    <X size={14} />
                  </button>
                </div>

                {showSidebar === 'scope' && (
                  <div className="flex-1 overflow-auto p-4 space-y-3">
                    <ScopeSelect
                      label={zh ? '平台' : 'Platform'}
                      value={configScopePlatform}
                      options={[{ value: 'all', label: zh ? '全部' : 'All' }, ...configPlatformOptions.map(p => ({ value: p, label: getPlatformLabel(p) }))]}
                      onChange={onConfigScopePlatformChange}
                    />
                    <ScopeSelect
                      label={zh ? '角色' : 'Role'}
                      value={configScopeRole}
                      options={[{ value: 'all', label: zh ? '全部' : 'All' }, ...configRoleOptions.map(r => ({ value: r, label: r }))]}
                      onChange={onConfigScopeRoleChange}
                    />
                    <ScopeSelect
                      label={zh ? '站点' : 'Site'}
                      value={configScopeSite}
                      options={[{ value: 'all', label: zh ? '全部' : 'All' }, ...configSiteOptions.map(s => ({ value: s, label: s }))]}
                      onChange={onConfigScopeSiteChange}
                    />

                    <div className="mt-4 rounded-xl bg-white border border-slate-200 p-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                          {zh ? '匹配到' : 'Matched'}
                        </span>
                        <span className="text-xs font-bold text-[#0891b2]">
                          {configScopedOnlineCount}/{configScopedDevices.length} {zh ? '在线' : 'online'}
                        </span>
                      </div>
                      {configScopedDevices.length === 0 ? (
                        <p className="text-[11px] text-slate-400 italic py-2 text-center">
                          {zh ? '无匹配设备，请调整范围' : 'No devices match. Adjust scope.'}
                        </p>
                      ) : (
                        <div className="space-y-1.5 max-h-[280px] overflow-auto">
                          {configScopedDevices.map((device) => (
                            <div key={device.id} className="flex items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5">
                              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${device.status === 'online' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                              <div className="min-w-0 flex-1">
                                <p className="text-xs font-semibold text-slate-700 truncate">{device.hostname}</p>
                                <p className="text-[10px] text-slate-400 font-mono truncate">{device.ip_address}</p>
                              </div>
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-500 flex-shrink-0">
                                {getPlatformLabel(device.platform)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {showSidebar === 'vars' && (
                  <div className="flex-1 overflow-auto p-4">
                    <button
                      onClick={onAddVar}
                      className="w-full mb-3 px-3 py-2 rounded-xl border-2 border-dashed border-[#06b6d4]/40 text-[#0891b2] text-xs font-bold hover:bg-cyan-50 transition-all flex items-center justify-center gap-1.5"
                    >
                      <Plus size={13} />
                      {t('addVar')}
                    </button>
                    <div className="space-y-1.5">
                      {globalVars.length === 0 && (
                        <p className="text-[11px] text-slate-400 italic py-4 text-center">
                          {zh ? '暂无全局变量' : 'No variables defined yet'}
                        </p>
                      )}
                      {globalVars.map((item, index) => (
                        <div key={item.id || index} className="group bg-white rounded-lg border border-slate-200 p-2.5 hover:border-[#06b6d4]/30 transition-all">
                          <div className="flex items-center justify-between gap-2">
                            <code className="text-xs font-bold text-[#0f172a] font-mono truncate flex-1">{item.key}</code>
                            <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-all">
                              <button
                                onClick={() => {
                                  navigator.clipboard.writeText('{{ ' + item.key + ' }}');
                                  showToast(t('copied'), 'success');
                                }}
                                className="p-1 rounded text-slate-400 hover:text-[#0891b2] hover:bg-cyan-50 transition-all"
                                title={zh ? '复制引用' : 'Copy reference'}
                              >
                                <FileText size={11} />
                              </button>
                              <button
                                onClick={() => item.id && onDeleteVar(item.id)}
                                disabled={!item.id}
                                className={`p-1 rounded transition-all ${item.id ? 'text-slate-400 hover:text-rose-500 hover:bg-rose-50' : 'text-slate-200 cursor-not-allowed'}`}
                                title={zh ? '删除' : 'Delete'}
                              >
                                <Trash2 size={11} />
                              </button>
                            </div>
                          </div>
                          <p className="mt-1 text-[10px] text-slate-400 font-mono truncate">{`{{ ${item.key} }} = ${item.value}`}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </aside>
            )}
          </div>
        </section>
      </div>
      </div>
    </div>
  );
};

/* ═════════════════════════════════════════════════════════ */
/*  Small helper components                                  */
/* ═════════════════════════════════════════════════════════ */

const METRIC_TONE: Record<string, { bg: string; text: string; ring: string }> = {
  slate:   { bg: 'bg-slate-100',  text: 'text-slate-700',   ring: 'ring-slate-200' },
  cyan:    { bg: 'bg-cyan-100',   text: 'text-[#0891b2]',   ring: 'ring-cyan-200' },
  emerald: { bg: 'bg-emerald-100',text: 'text-emerald-700', ring: 'ring-emerald-200' },
  amber:   { bg: 'bg-amber-100',  text: 'text-amber-700',   ring: 'ring-amber-200' },
  rose:    { bg: 'bg-rose-100',   text: 'text-rose-700',    ring: 'ring-rose-200' },
};

const MetricCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
  tone: keyof typeof METRIC_TONE;
}> = ({ icon, label, value, sub, tone }) => {
  const t = METRIC_TONE[tone] || METRIC_TONE.slate;
  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm hover:shadow-md transition-all">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{label}</span>
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${t.bg} ${t.text}`}>
          {icon}
        </div>
      </div>
      <p className={`mt-3 text-3xl font-bold ${t.text}`}>{value}</p>
      <p className="mt-1 text-[11px] text-slate-500 truncate">{sub}</p>
    </div>
  );
};

const SidebarToggle: React.FC<{
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  badge?: number;
}> = ({ active, onClick, icon, label, badge }) => (
  <button
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
      active
        ? 'bg-[#0f172a] text-white shadow-sm'
        : 'text-slate-600 border border-slate-200 hover:border-[#06b6d4] hover:text-[#0891b2] bg-white'
    }`}
    title={label}
  >
    {icon}
    {label}
    {typeof badge === 'number' && (
      <span className={`ml-0.5 text-[9px] font-black px-1.5 py-0.5 rounded-full ${active ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-500'}`}>
        {badge}
      </span>
    )}
  </button>
);

const ScopeSelect: React.FC<{
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}> = ({ label, value, options, onChange }) => (
  <div>
    <label className="text-[10px] font-bold uppercase tracking-widest text-slate-400 block mb-1.5">{label}</label>
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-700 outline-none focus:border-[#06b6d4] transition-all"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  </div>
);

export default PlatformSettingsTab;
