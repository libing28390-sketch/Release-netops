import React, { useState, useMemo, useRef } from 'react';
import { Activity, AlertCircle, AlertTriangle, Copy, Database, FileText, Filter, FolderOpen, Globe, Plus, Search, Server, Settings, ShieldCheck, CheckCircle2, X } from 'lucide-react';
import type { ConfigTemplate, Device } from '../types';

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
  const [tplSearch, setTplSearch] = useState('');
  const [tplVendorFilter, setTplVendorFilter] = useState<string>('all');
  const [devicePreviewExpanded, setDevicePreviewExpanded] = useState(false);
  const lineNumRef = useRef<HTMLDivElement>(null);

  const vendorList = useMemo(() => {
    const vendors = new Set<string>();
    configTemplates.forEach((tpl) => vendors.add(tpl.vendor || 'Custom'));
    return Array.from(vendors).sort();
  }, [configTemplates]);

  const filteredTemplates = useMemo(() => {
    let list = configTemplates;
    if (tplVendorFilter !== 'all') {
      list = list.filter((tpl) => (tpl.vendor || 'Custom') === tplVendorFilter);
    }
    if (tplSearch.trim()) {
      const q = tplSearch.trim().toLowerCase();
      list = list.filter(
        (tpl) =>
          tpl.name.toLowerCase().includes(q) ||
          (tpl.vendor || 'Custom').toLowerCase().includes(q)
      );
    }
    return list;
  }, [configTemplates, tplVendorFilter, tplSearch]);

  const groupedTemplates = useMemo<[string, ConfigTemplate[]][]>(() => Object.entries(
    filteredTemplates.reduce<Record<string, ConfigTemplate[]>>((acc, tpl) => {
      const vendor = tpl.vendor || 'Custom';
      if (!acc[vendor]) acc[vendor] = [];
      acc[vendor].push(tpl);
      return acc;
    }, {})
  ), [filteredTemplates]);

  const officialCount = useMemo(() => configTemplates.filter((tpl) => tpl.category === 'official').length, [configTemplates]);
  const customCount = configTemplates.length - officialCount;

  const templateVarsMap = useMemo(() => {
    const map = new Map<string, string[]>();
    filteredTemplates.forEach((tpl) => map.set(tpl.id, extractVars(tpl.content)));
    return map;
  }, [filteredTemplates, extractVars]);

  return (
    <div className="h-full flex flex-col gap-5 overflow-hidden">
      <div className={sectionHeaderRowClass}>
        <div>
          <h2 className="text-2xl font-medium tracking-tight">{t('configManagement')}</h2>
          <p className="text-sm text-black/40">
            {language === 'zh'
              ? '把模板资产、渲染预览、发布范围和发布检查放到同一个工作台里。'
              : 'Bring template assets, rendered preview, release scope, and preflight checks into one workspace.'}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <label className="cursor-pointer px-4 py-2 border border-black/10 rounded-xl text-sm font-medium hover:bg-black/5 transition-all">
            {t('importVars')}
            <input type="file" className="hidden" accept=".xlsx, .xls, .csv" onChange={(e) => { onImportVars(e); e.target.value = ''; }} />
          </label>
          <button
            onClick={onCreateTemplate}
            className="bg-[#00bceb] text-white px-4 py-2 rounded-xl text-sm font-medium flex items-center gap-2 hover:bg-[#0096bd] transition-all shadow-lg shadow-[#00bceb]/20"
          >
            <Plus size={18} />
            {t('newTemplate')}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 flex-shrink-0">
        <div className="bg-white rounded-2xl border border-black/5 p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.24em] text-black/35 font-bold">
              {language === 'zh' ? '模板资产' : 'Template Assets'}
            </span>
            <FolderOpen size={14} className="text-black/25" />
          </div>
          <p className="mt-3 text-3xl font-semibold text-black">{configTemplates.length}</p>
          <p className="mt-1 text-xs text-black/45">
            {language === 'zh'
              ? `${officialCount} 个官方模板，${customCount} 个自定义模板`
              : `${officialCount} official, ${customCount} custom`}
          </p>
        </div>
        <div className="bg-white rounded-2xl border border-black/5 p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.24em] text-black/35 font-bold">
              {language === 'zh' ? '变量完备度' : 'Variable Coverage'}
            </span>
            <Database size={14} className="text-black/25" />
          </div>
          <p className={`mt-3 text-3xl font-semibold ${configMissingVariables.length === 0 ? 'text-emerald-600' : 'text-amber-600'}`}>{configVariableKeys.length - configMissingVariables.length}/{configVariableKeys.length || 0}</p>
          <p className="mt-1 text-xs text-black/45">
            {configMissingVariables.length === 0
              ? (language === 'zh' ? '当前模板变量已全部赋值' : 'All variables are populated for the selected template')
              : (language === 'zh' ? `缺失 ${configMissingVariables.length} 个变量` : `${configMissingVariables.length} variables missing`)}
          </p>
        </div>
        <div className="bg-white rounded-2xl border border-black/5 p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.24em] text-black/35 font-bold">
              {language === 'zh' ? '匹配设备' : 'Matched Targets'}
            </span>
            <Server size={14} className="text-black/25" />
          </div>
          <p className="mt-3 text-3xl font-semibold text-[#0891b2]">{configScopedDevices.length}</p>
          <p className="mt-1 text-xs text-black/45">
            {language === 'zh'
              ? `${configScopedOnlineCount} 台在线，可用于当前发布范围`
              : `${configScopedOnlineCount} online devices in current release scope`}
          </p>
        </div>
        <div className="bg-white rounded-2xl border border-black/5 p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.24em] text-black/35 font-bold">
              {language === 'zh' ? '发布就绪度' : 'Release Readiness'}
            </span>
            <ShieldCheck size={14} className="text-black/25" />
          </div>
          <p className={`mt-3 text-3xl font-semibold ${configReadinessScore >= 80 ? 'text-emerald-600' : configReadinessScore >= 50 ? 'text-amber-600' : 'text-red-500'}`}>{configReadinessScore}</p>
          <p className="mt-1 text-xs text-black/45">
            {configValidationIssues.length === 0
              ? (language === 'zh' ? '通过基础校验，可进入发布动作' : 'Base checks passed. Ready for release actions')
              : (language === 'zh' ? `${configValidationIssues.length} 个阻断项待处理` : `${configValidationIssues.length} blocking issues to resolve`)}
          </p>
        </div>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-12 gap-4 overflow-hidden">
        <div className="xl:col-span-3 flex flex-col gap-4 min-h-0 overflow-auto pr-1">
          <div className="bg-[#ecfeff] rounded-xl border border-[#06b6d4]/15 px-4 py-2.5 shadow-sm">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-[#06b6d4]/10 text-[#0891b2]">
                <Activity size={14} />
              </div>
              <p className="text-xs text-[#164e63]">
                {language === 'zh'
                  ? '先选模板 → 完成变量渲染和范围确认 → 发布前检查后再下发'
                  : 'Select template → Complete variables & scope → Preflight check → Deploy'}
              </p>
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-black/5 p-5 shadow-sm min-h-0 flex flex-col">
            <div className="mb-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-black/40">{t('templates')}</h3>
            </div>
            <div className="flex gap-2 mb-3">
              <div className="relative flex-1 min-w-0">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/25" />
                <input
                  type="text"
                  value={tplSearch}
                  onChange={(e) => setTplSearch(e.target.value)}
                  placeholder={language === 'zh' ? '搜索模板...' : 'Search...'}
                  className="w-full pl-9 pr-3 py-2 text-xs bg-black/[0.03] border border-black/5 rounded-xl outline-none focus:border-[#06b6d4] focus:shadow-[0_0_0_3px_rgba(6,182,212,0.08)] transition-all placeholder:text-black/25"
                />
              </div>
              <select
                value={tplVendorFilter}
                onChange={(e) => setTplVendorFilter(e.target.value)}
                title={language === 'zh' ? '按厂商筛选' : 'Filter by vendor'}
                className="px-2.5 py-2 text-xs bg-black/[0.03] border border-black/5 rounded-xl outline-none focus:border-[#06b6d4] transition-all text-black/60 cursor-pointer flex-shrink-0"
              >
                <option value="all">{language === 'zh' ? '全部厂商' : 'All vendors'} ({configTemplates.length})</option>
                {vendorList.map((vendor) => {
                  const count = configTemplates.filter((tpl) => (tpl.vendor || 'Custom') === vendor).length;
                  return (
                    <option key={vendor} value={vendor}>{vendor} ({count})</option>
                  );
                })}
              </select>
            </div>
            {filteredTemplates.length === 0 && (
              <div className="py-6 text-center text-xs text-black/30">
                {language === 'zh' ? '没有匹配的模板' : 'No matching templates'}
              </div>
            )}
            <div className="space-y-5 overflow-auto pr-1">
              {groupedTemplates.map(([vendor, templates]) => (
                <div key={vendor} className="space-y-2">
                  <div className="flex items-center justify-between px-1">
                    <h4 className="text-[10px] font-bold uppercase tracking-[0.22em] text-black/30">{vendor}</h4>
                    <span className="text-[10px] text-black/25">{templates.length}</span>
                  </div>
                  <div className="space-y-2">
                    {templates.map((tpl) => {
                      const templateVars = templateVarsMap.get(tpl.id) || [];
                      const isSelected = selectedTemplateId === tpl.id;
                      return (
                        <button
                          key={tpl.id}
                          onClick={() => onSelectTemplateIdChange(tpl.id)}
                          className={`w-full rounded-xl border p-3 text-left transition-all ${isSelected
                            ? 'border-[#06b6d4] bg-[#06b6d4] text-white shadow-md shadow-[#06b6d4]/20'
                            : 'border-black/5 bg-white hover:border-[#06b6d4]/25 hover:bg-[#ecfeff]/50 text-black/75'}`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-semibold">{tpl.name}</span>
                                {tpl.category === 'official' && (
                                  <span className={`text-[8px] px-1.5 py-0.5 rounded-full font-bold uppercase ${isSelected ? 'bg-white/10 text-white/70' : 'bg-blue-100 text-blue-700'}`}>
                                    {t('official')}
                                  </span>
                                )}
                              </div>
                              <p className={`mt-1 text-[10px] ${isSelected ? 'text-white/45' : 'text-black/35'}`}>
                                {language === 'zh' ? `最近使用 ${tpl.lastUsed}` : `Last used ${tpl.lastUsed}`}
                              </p>
                            </div>
                            <span className={`text-[10px] font-bold uppercase ${isSelected ? 'text-white/45' : 'text-black/30'}`}>{tpl.type}</span>
                          </div>
                          <div className="mt-3 flex items-center gap-2 flex-wrap text-[10px]">
                            <span className={`px-2 py-1 rounded-full ${isSelected ? 'bg-white/10 text-white/60' : 'bg-black/[0.04] text-black/45'}`}>
                              {templateVars.length} {language === 'zh' ? '变量' : 'vars'}
                            </span>
                            <span className={`px-2 py-1 rounded-full ${isSelected ? 'bg-white/10 text-white/60' : 'bg-black/[0.04] text-black/45'}`}>
                              {tpl.vendor || 'Custom'}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="xl:col-span-6 min-h-0 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden flex flex-col">
          <div className="px-5 py-3.5 border-b border-black/5 bg-black/[0.015]">
            <div className="flex flex-wrap items-center gap-2">
              <div className="p-1.5 bg-black/5 rounded-lg text-black/60">
                <Settings size={16} />
              </div>
              <input
                type="text"
                value={selectedConfigTemplate?.name || ''}
                title={language === 'zh' ? '模板名称' : 'Template name'}
                onChange={(event) => onSelectedTemplateNameChange(event.target.value)}
                className="bg-black/5 px-3 py-1.5 rounded-xl font-medium border border-black/5 focus:border-black/20 outline-none transition-all min-w-[180px] max-w-[240px]"
                placeholder="Template Name"
              />
              <select
                value={selectedConfigTemplate?.vendor || 'Custom'}
                title={language === 'zh' ? '模板厂商' : 'Template vendor'}
                onChange={(event) => onSelectedTemplateVendorChange(event.target.value)}
                className="bg-black/5 text-xs px-2.5 py-1.5 rounded-xl outline-none"
              >
                {['Cisco', 'Juniper', 'Huawei', 'H3C', 'Arista', 'Other', 'Custom'].map((vendor) => (
                  <option key={vendor} value={vendor}>{vendor}</option>
                ))}
              </select>
              <select
                value={selectedConfigTemplate?.type || 'Jinja2'}
                title={language === 'zh' ? '模板类型' : 'Template type'}
                onChange={(event) => onSelectedTemplateTypeChange(event.target.value as TemplateType)}
                className="bg-black/5 text-xs font-bold uppercase px-2.5 py-1.5 rounded-xl outline-none"
              >
                <option value="Jinja2">Jinja2</option>
                <option value="YAML">YAML</option>
              </select>
              <span className="text-black/15 mx-0.5">|</span>
              <button
                onClick={onDiscardChanges}
                className="px-2 py-1 text-xs text-black/40 hover:text-black/70 transition-all"
              >
                {t('discard')}
              </button>
              <button
                onClick={onSaveTemplate}
                className="px-2 py-1 text-xs font-medium text-[#0891b2] hover:underline transition-all"
              >
                {t('saveChanges')}
              </button>
            </div>
            <div className="mt-2.5 flex items-center justify-between flex-wrap gap-2">
              <div className="flex gap-1.5">
                {[
                  { key: 'source', label: language === 'zh' ? '源模板' : 'Source' },
                  { key: 'rendered', label: language === 'zh' ? '渲染结果' : 'Rendered' },
                  { key: 'checks', label: language === 'zh' ? '发布检查' : 'Checks' },
                ].map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => onConfigWorkspaceViewChange(tab.key as ConfigWorkspaceView)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${configWorkspaceView === tab.key
                      ? 'bg-[#06b6d4] text-white shadow-sm shadow-[#06b6d4]/20'
                      : 'bg-black/[0.04] text-black/55 hover:bg-[#06b6d4]/10 hover:text-[#0891b2]'}`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={onValidate}
                  className="px-3 py-1.5 text-xs font-medium text-[#0891b2] border border-[#06b6d4]/25 rounded-xl hover:bg-[#ecfeff] transition-all flex items-center gap-1.5"
                >
                  <ShieldCheck size={13} />
                  {language === 'zh' ? '检查' : 'Preflight'}
                </button>
                <button
                  onClick={onCreateScenarioDraft}
                  className="px-3 py-1.5 text-xs font-medium text-black/50 border border-black/10 rounded-xl hover:bg-black/[0.03] transition-all"
                >
                  {language === 'zh' ? '转草稿' : 'To Draft'}
                </button>
                <button
                  onClick={onSendToAutomation}
                  className="px-3 py-1.5 bg-[#06b6d4] text-white rounded-xl text-xs font-medium hover:bg-[#0891b2] transition-all shadow-sm shadow-[#06b6d4]/20"
                >
                  {language === 'zh' ? '提交下发' : 'Deploy'}
                </button>
              </div>
            </div>
          </div>

          <div className="px-5 py-3 border-b border-black/5 bg-amber-50/70 text-[11px] text-amber-900/80">
            {configMissingVariables.length > 0
              ? (language === 'zh'
                ? `当前仍有未赋值变量: ${configMissingVariables.join('、')}。渲染预览会保留占位符。`
                : `Variables still missing: ${configMissingVariables.join(', ')}. Rendered preview will keep placeholders.`)
              : (language === 'zh'
                ? '渲染预览仅基于全局变量替换，不会连接设备拉取运行态配置。'
                : 'Rendered preview uses global variables only and does not connect to devices for runtime config.')}
          </div>

          {configWorkspaceView === 'source' && (
            <div className="flex-1 flex bg-[#1E1E1E] overflow-hidden min-h-0">
              <div
                ref={lineNumRef}
                className="w-12 py-6 bg-black/30 text-white/35 select-none text-right pr-3 font-mono text-sm leading-6 overflow-hidden"
              >
                {editorContent.split('\n').map((_, index) => <div key={index}>{index + 1}</div>)}
              </div>
              <textarea
                value={editorContent}
                onChange={(event) => onEditorContentChange(event.target.value)}
                onScroll={(e) => { if (lineNumRef.current) lineNumRef.current.scrollTop = e.currentTarget.scrollTop; }}
                title={language === 'zh' ? '模板源码编辑器' : 'Template source editor'}
                placeholder={language === 'zh' ? '在这里编辑模板源码' : 'Edit template source here'}
                className="flex-1 p-6 bg-transparent font-mono text-sm text-[#D4D4D4] outline-none resize-none leading-6"
                spellCheck={false}
              />
            </div>
          )}

          {configWorkspaceView === 'rendered' && (
            <div className="flex-1 min-h-0 overflow-auto bg-[#101820] text-[#d6e2ea] font-mono text-sm leading-6 p-6">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-white/35">
                    {language === 'zh' ? '渲染结果' : 'Rendered Result'}
                  </p>
                  <p className="mt-1 text-[11px] text-white/45">
                    {language === 'zh' ? '用于人工预览、Review 和发布前核对。' : 'Use this for operator preview, review, and pre-release verification.'}
                  </p>
                </div>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(configRenderedPreview);
                    showToast(t('copied'), 'success');
                  }}
                  className="px-3 py-1.5 rounded-xl border border-white/10 text-xs text-white/70 hover:text-white hover:border-white/20 flex items-center gap-1.5"
                >
                  <Copy size={13} />
                  {language === 'zh' ? '复制渲染结果' : 'Copy rendered output'}
                </button>
              </div>
              <pre className="whitespace-pre-wrap break-words">{configRenderedPreview || (language === 'zh' ? '暂无内容' : 'No content')}</pre>
            </div>
          )}

          {configWorkspaceView === 'checks' && (
            <div className="flex-1 min-h-0 overflow-auto p-5 bg-[#fafafa]">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={16} className="text-emerald-600" />
                    <h3 className="text-sm font-semibold text-black">
                      {language === 'zh' ? '阻断项' : 'Blocking Checks'}
                    </h3>
                  </div>
                  <div className="mt-4 space-y-2">
                    {configValidationIssues.length === 0 ? (
                      <div className="flex items-start gap-2 text-sm text-emerald-700">
                        <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0" />
                        <span>{language === 'zh' ? '基础检查全部通过，可以执行发布。' : 'All base checks passed. Release can proceed.'}</span>
                      </div>
                    ) : configValidationIssues.map((issue) => (
                      <div key={issue} className="flex items-start gap-2 text-sm text-red-600">
                        <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
                        <span>{issue}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
                  <div className="flex items-center gap-2">
                    <AlertCircle size={16} className="text-amber-600" />
                    <h3 className="text-sm font-semibold text-black">
                      {language === 'zh' ? '发布提醒' : 'Release Advisories'}
                    </h3>
                  </div>
                  <div className="mt-4 space-y-2">
                    {configValidationWarnings.length === 0 ? (
                      <div className="flex items-start gap-2 text-sm text-slate-600">
                        <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0 text-emerald-600" />
                        <span>{language === 'zh' ? '没有额外风险提醒。' : 'No additional advisories.'}</span>
                      </div>
                    ) : configValidationWarnings.map((warning) => (
                      <div key={warning} className="flex items-start gap-2 text-sm text-amber-700">
                        <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
                        <span>{warning}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-white rounded-2xl border border-black/5 p-5 shadow-sm md:col-span-2">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <h3 className="text-sm font-semibold text-black">
                        {language === 'zh' ? '推荐的内网发布顺序' : 'Recommended Internal Release Flow'}
                      </h3>
                      <p className="mt-1 text-xs text-black/45">
                        {language === 'zh'
                          ? '适合当前内网使用场景，不强依赖审批系统或外部工单平台。'
                          : 'Optimized for internal-only use without depending on approval portals or external ticketing systems.'}
                      </p>
                    </div>
                  </div>
                  <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
                    {[
                      language === 'zh' ? '1. 锁定模板与变量版本' : '1. Freeze template and variables',
                      language === 'zh' ? '2. 按平台/角色/站点筛目标' : '2. Narrow targets by platform/role/site',
                      language === 'zh' ? '3. 先挑在线设备做小范围验证' : '3. Start with a small online canary set',
                      language === 'zh' ? '4. 再执行批量下发和回溯核查' : '4. Then deploy broadly and review outcomes',
                    ].map((item) => (
                      <div key={item} className="rounded-xl border border-black/5 bg-black/[0.02] px-3 py-3 text-black/70">{item}</div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="xl:col-span-3 flex flex-col gap-4 min-h-0 overflow-auto pl-1">
          <div className="bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
            <div className="flex items-center gap-2 mb-4">
              <Filter size={15} className="text-black/40" />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-black/40">
                {language === 'zh' ? '发布范围' : 'Release Scope'}
              </h3>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 block mb-1.5">
                  {language === 'zh' ? '平台' : 'Platform'}
                </label>
                <select
                  value={configScopePlatform}
                  title={language === 'zh' ? '发布范围平台' : 'Release scope platform'}
                  onChange={(event) => onConfigScopePlatformChange(event.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-black/10 bg-white text-sm outline-none focus:border-[#06b6d4] focus:shadow-[0_0_0_3px_rgba(6,182,212,0.1)] transition-all"
                >
                  <option value="all">{language === 'zh' ? '全部平台' : 'All platforms'}</option>
                  {configPlatformOptions.map((platform) => (
                    <option key={platform} value={platform}>{getPlatformLabel(platform)}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 block mb-1.5">
                  {language === 'zh' ? '设备角色' : 'Device Role'}
                </label>
                <select
                  value={configScopeRole}
                  title={language === 'zh' ? '发布范围设备角色' : 'Release scope device role'}
                  onChange={(event) => onConfigScopeRoleChange(event.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-black/10 bg-white text-sm outline-none focus:border-[#06b6d4] focus:shadow-[0_0_0_3px_rgba(6,182,212,0.1)] transition-all"
                >
                  <option value="all">{language === 'zh' ? '全部角色' : 'All roles'}</option>
                  {configRoleOptions.map((role) => (
                    <option key={role} value={role}>{role}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 block mb-1.5">
                  {language === 'zh' ? '站点' : 'Site'}
                </label>
                <select
                  value={configScopeSite}
                  title={language === 'zh' ? '发布范围站点' : 'Release scope site'}
                  onChange={(event) => onConfigScopeSiteChange(event.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-black/10 bg-white text-sm outline-none focus:border-[#06b6d4] focus:shadow-[0_0_0_3px_rgba(6,182,212,0.1)] transition-all"
                >
                  <option value="all">{language === 'zh' ? '全部站点' : 'All sites'}</option>
                  {configSiteOptions.map((site) => (
                    <option key={site} value={site}>{site}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-4 rounded-xl bg-black/[0.03] px-3 py-3 text-xs text-black/55">
              {language === 'zh'
                ? `当前模板厂商范围：${selectedConfigTemplate?.vendor || 'Custom'}。发布范围内共 ${configScopedDevices.length} 台设备。`
                : `Current template vendor scope: ${selectedConfigTemplate?.vendor || 'Custom'}. ${configScopedDevices.length} devices are in release scope.`}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-black/5 p-5 shadow-sm min-h-0 flex flex-col">
            <div className="flex items-center justify-between gap-2 mb-4">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-black/40">
                  {language === 'zh' ? '目标设备预览' : 'Target Preview'}
                </h3>
                <p className="mt-1 text-[11px] text-black/35">
                  {language === 'zh' ? '按当前过滤条件匹配到的设备' : 'Devices matched by the current release filters'}
                </p>
              </div>
              <span className="text-[10px] px-2 py-1 rounded-full bg-black/[0.05] text-black/50">
                {configScopedOnlineCount}/{configScopedDevices.length} {language === 'zh' ? '在线' : 'online'}
              </span>
            </div>
            <div className="space-y-2 overflow-auto pr-1">
              {(devicePreviewExpanded ? configScopedDevices : configScopedDevices.slice(0, 8)).map((device) => (
                <div key={device.id} className="rounded-xl border border-black/5 px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-black truncate">{device.hostname}</p>
                      <p className="mt-1 text-[11px] text-black/40 font-mono truncate">{device.ip_address}</p>
                    </div>
                    <span className={`text-[10px] px-2 py-1 rounded-full ${device.status === 'online' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                      {device.status}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-black/45">
                    <span className="px-2 py-1 rounded-full bg-black/[0.04]">{getPlatformLabel(device.platform)}</span>
                    {device.role && <span className="px-2 py-1 rounded-full bg-black/[0.04]">{device.role}</span>}
                    {device.site && <span className="px-2 py-1 rounded-full bg-black/[0.04]">{device.site}</span>}
                  </div>
                </div>
              ))}
              {configScopedDevices.length === 0 && (
                <div className="rounded-xl border border-dashed border-black/10 px-4 py-8 text-center text-sm text-black/35">
                  {language === 'zh' ? '当前没有匹配设备，请调整发布范围。' : 'No devices match the current filters. Adjust the release scope.'}
                </div>
              )}
              {configScopedDevices.length > 8 && (
                <button
                  onClick={() => setDevicePreviewExpanded(!devicePreviewExpanded)}
                  className="text-[11px] text-[#0891b2] hover:underline px-1 py-1"
                >
                  {devicePreviewExpanded
                    ? (language === 'zh' ? '收起' : 'Collapse')
                    : (language === 'zh' ? `展开全部 ${configScopedDevices.length} 台设备` : `Show all ${configScopedDevices.length} devices`)}
                </button>
              )}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-black/5 p-4 shadow-sm min-h-0 flex flex-col">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-black/40">{t('globalVars')}</h3>
              <button
                onClick={onAddVar}
                className="text-[10px] text-[#0891b2] font-bold hover:underline uppercase"
              >
                {t('addVar')}
              </button>
            </div>
            <div className="space-y-2 overflow-auto pr-1">
              {globalVars.map((item, index) => (
                <div key={item.id || index} className="group relative flex justify-between items-center py-1.5 border-b border-black/5">
                  <div className="flex flex-col min-w-0">
                    <span className="text-xs font-mono text-black/60 truncate">{item.key}</span>
                    <span className="text-[10px] text-black/30 font-mono">{'{{ ' + item.key + ' }}'}</span>
                  </div>
                  <div className="flex items-center gap-2 ml-2">
                    <span className="text-xs font-medium max-w-[100px] truncate">{item.value}</span>
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-all">
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText('{{ ' + item.key + ' }}');
                          showToast(t('copied'), 'success');
                        }}
                        className="bg-white shadow-sm border border-black/5 p-1 rounded text-black/40 hover:text-black"
                        title="Copy reference"
                      >
                        <FileText size={11} />
                      </button>
                      <button
                        onClick={() => item.id && onDeleteVar(item.id)}
                        disabled={!item.id}
                        className={`bg-white shadow-sm border border-black/5 p-1 rounded ${item.id ? 'text-red-400 hover:text-red-600 cursor-pointer' : 'text-black/15 cursor-not-allowed'}`}
                        title="Delete variable"
                      >
                        <X size={11} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
            <div className="flex items-center gap-2 mb-4">
              <Globe size={15} className="text-black/40" />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-black/40">
                {language === 'zh' ? '治理提示' : 'Governance Notes'}
              </h3>
            </div>
            <div className="space-y-3 text-sm text-black/65">
              <div className="rounded-xl bg-black/[0.03] px-3 py-3">
                <p className="font-medium text-black">
                  {language === 'zh' ? '建议动作' : 'Recommended Action'}
                </p>
                <p className="mt-1 text-xs text-black/50">
                  {configReadinessScore >= 85
                    ? (language === 'zh' ? '先挑一台在线设备验证，再逐步扩大范围。' : 'Validate on one online device first, then expand gradually.')
                    : (language === 'zh' ? '先补全变量或缩小发布范围，再执行下发。' : 'Complete variables or narrow the scope before deployment.')}
                </p>
              </div>
              <div className="rounded-xl bg-black/[0.03] px-3 py-3">
                <p className="font-medium text-black">
                  {language === 'zh' ? '当前能力边界' : 'Current Capability Boundary'}
                </p>
                <p className="mt-1 text-xs text-black/50">
                  {language === 'zh'
                    ? '当前页面提供模板渲染预览、范围筛选和单设备下发入口；如要做审批、版本签发和回滚编排，建议后续单独补后台流程。'
                    : 'This workspace currently provides rendered preview, release scoping, and single-device deployment. Approval, signed releases, and rollback orchestration should be added as separate backend workflows later.'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PlatformSettingsTab;