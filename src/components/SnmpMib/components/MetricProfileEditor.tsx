import React, { useState, useEffect, useMemo } from 'react';
import { Plus, Save, Sparkles, Trash2, X } from 'lucide-react';
import { ALL_VENDOR_NAMES, NETWORK_VENDOR_GROUPS } from '../../../pages/AssetManagement/constants';
import {
  MetricRow,
  MetricDefinition,
  MetricRowItem,
  METRIC_CATALOG,
  createDefinition,
  hasDefinition,
  toPayload,
  metricLabel,
  catalogEntry,
} from './MetricRowItem';
import {
  InterfaceOidConfig,
  InterfaceConfigSection,
  DEFAULT_INTERFACE_CONFIG,
} from './InterfaceConfigSection';
import { LiveWalkInspector, CandidateDevice } from './LiveWalkInspector';
import { ModelPresetItem } from '../PresetProfilesModal';

export interface ProfileForm {
  vendor: string;
  model: string;
  metrics: MetricRow[];
  interfaceConfig: InterfaceOidConfig;
}

export interface InterfaceTestResult {
  passed?: boolean;
  status?: string;
  message?: string;
  counter_mode?: string;
  selected_counter_bits?: number | null;
  interfaces?: number;
  counter_supported?: number;
  checks?: Record<
    string,
    { oid?: string; passed?: boolean; rows?: number; message?: string; counter_bits?: number }
  >;
}

interface MetricProfileEditorProps {
  editingId: string | null;
  form: ProfileForm;
  saving: boolean;
  language: string;
  candidateDevices?: CandidateDevice[];
  autoMatchResult?: { matched_series?: string; confidence?: number; preset?: ModelPresetItem } | null;
  lastTestDetails?: { hardware?: Record<string, any>; interface?: InterfaceTestResult } | null;
  onChangeForm: (updater: (prev: ProfileForm) => ProfileForm) => void;
  onSave: () => void;
  onDelete: () => void;
  onClose: () => void;
  onOpenOidPicker: (metricKey: string, field: string) => void;
  onApplyPreset: (preset: ModelPresetItem) => void;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const KNOWN_VENDOR_SET = new Set<string>(ALL_VENDOR_NAMES as readonly string[]);

export const MetricProfileEditor: React.FC<MetricProfileEditorProps> = ({
  editingId,
  form,
  saving,
  language,
  candidateDevices = [],
  autoMatchResult,
  lastTestDetails,
  onChangeForm,
  onSave,
  onDelete,
  onClose,
  onOpenOidPicker,
  onApplyPreset,
  showToast,
}) => {
  const zh = language === 'zh';
  const [addMetricKey, setAddMetricKey] = useState('');

  const addableMetrics = useMemo(() => {
    return METRIC_CATALOG.filter(item => !form.metrics.some(row => row.key === item.key));
  }, [form.metrics]);

  const addMetric = () => {
    if (!addMetricKey || form.metrics.some(row => row.key === addMetricKey)) return;
    onChangeForm(prev => ({
      ...prev,
      metrics: [...prev.metrics, { key: addMetricKey, definition: createDefinition(addMetricKey) }],
    }));
    const next = addableMetrics.find(item => item.key !== addMetricKey);
    setAddMetricKey(next?.key || '');
  };

  const handleBackfillOid = (metricKey: string, oid: string) => {
    onChangeForm(prev => {
      const exists = prev.metrics.some(m => m.key === metricKey);
      const metrics = exists
        ? prev.metrics
        : [...prev.metrics, { key: metricKey, definition: createDefinition(metricKey) }];
      return {
        ...prev,
        metrics: metrics.map(row => {
          if (row.key !== metricKey) return row;
          return {
            ...row,
            definition: {
              ...row.definition,
              oid,
            },
          };
        }),
      };
    });
    showToast(
      zh ? `已将 ${oid} 设为 ${metricLabel(metricKey, true)} OID` : `Set ${oid} to ${metricKey} OID`,
      'success',
    );
  };

  const fallbackOid = useMemo(() => {
    return (
      form.metrics.map(row => String(toPayload(row.definition).oid || '').trim()).find(Boolean) ||
      (form.interfaceConfig.enabled ? form.interfaceConfig.if_name_oid : '')
    );
  }, [form.metrics, form.interfaceConfig]);

  return (
    <div
      className="fixed inset-0 z-[130] flex items-center justify-center bg-black/50 p-3.5 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[95vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-2xl border border-[#00bceb]/25 bg-[var(--card-bg)] shadow-2xl dark:border-white/10"
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Editor Top Bar */}
        <div className="flex items-center justify-between border-b border-black/6 px-5 py-3.5 dark:border-white/8">
          <div>
            <div className="text-sm font-semibold text-black/80 dark:text-white/85">
              {editingId ? (zh ? '编辑型号指标模板' : 'Edit Model Profile') : zh ? '新增型号指标模板' : 'New Model Profile'}
            </div>
            <div className="mt-0.5 text-[10px] text-black/45 dark:text-white/45">
              {zh
                ? '按厂商与精确型号维护 SNMP 硬件采集规则；支持 MIB 拾取、官方预置套用与实时 WALK 探测。'
                : 'Maintain SNMP hardware metric rules by exact model with MIB Picker and Live WALK support.'}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"
            aria-label={zh ? '关闭' : 'Close'}
          >
            <X size={17} />
          </button>
        </div>

        {/* Scrollable Form Body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {/* Vendor and Model Inputs */}
          <div className="mb-4 grid gap-3 sm:grid-cols-2">
            <label className="block text-[11px] font-medium text-black/60 dark:text-white/60">
              {zh ? '设备厂商（关联资产管理）' : 'Vendor (shared catalog)'}
              <select
                value={form.vendor}
                onChange={e => onChangeForm(prev => ({ ...prev, vendor: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-3 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]"
              >
                <option value="">{zh ? '选择设备厂商...' : 'Select vendor...'}</option>
                {NETWORK_VENDOR_GROUPS.map(group => (
                  <optgroup key={group.key} label={zh ? group.labelZh : group.labelEn}>
                    {group.vendors.map(vendor => (
                      <option key={vendor} value={vendor}>
                        {vendor}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="block text-[11px] font-medium text-black/60 dark:text-white/60">
              {zh ? '精确型号（区分大小写）' : 'Exact model name'}
              <input
                value={form.model}
                onChange={e => onChangeForm(prev => ({ ...prev, model: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-3 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]"
                placeholder="例如：C9300-48P / S6800-54QT"
              />
            </label>
          </div>

          {/* Auto Match Recommendation Banner */}
          {autoMatchResult && autoMatchResult.preset && (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2.5 rounded-xl border border-[#00bceb]/30 bg-[#00bceb]/[0.06] p-3 text-xs dark:bg-[#00bceb]/[0.1]">
              <div className="flex items-center gap-2.5">
                <Sparkles size={18} className="shrink-0 text-[#008aad] dark:text-[#00bceb]" />
                <div>
                  <div className="font-semibold text-[#007391] dark:text-[#00bceb]">
                    {zh
                      ? `✨ 已根据型号智能匹配到【${autoMatchResult.matched_series || autoMatchResult.preset.model}】MIB 规则`
                      : `✨ Inferred MIB profile for [${autoMatchResult.matched_series || autoMatchResult.preset.model}]`}
                  </div>
                  <div className="mt-0.5 text-[10px] text-[#008aad]/80 dark:text-[#00bceb]/80">
                    {zh
                      ? `匹配置信度 ${Math.round((autoMatchResult.confidence || 0.9) * 100)}% · 包含 CPU、内存、温度与 IF-MIB 完整推荐 OID`
                      : `Confidence ${Math.round((autoMatchResult.confidence || 0.9) * 100)}% · contains recommended CPU, Memory, and IF-MIB`}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  const originalVendor = form.vendor.trim();
                  const originalModel = form.model.trim();
                  onApplyPreset({
                    ...autoMatchResult.preset!,
                    vendor: originalVendor || autoMatchResult.preset!.vendor,
                    model: originalModel || autoMatchResult.preset!.model,
                  });
                }}
                className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1]"
              >
                <Sparkles size={13} />
                {zh ? '一键采纳并填充全部推荐 OID' : 'Apply Recommended OIDs'}
              </button>
            </div>
          )}

          {/* Live Inspector SNMP Walk */}
          <LiveWalkInspector
            zh={zh}
            candidateDevices={candidateDevices}
            fallbackOid={fallbackOid}
            saving={saving}
            showToast={showToast}
            onBackfillOid={handleBackfillOid}
          />

          {/* Metrics Section Header */}
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold text-black/75 dark:text-white/80">
                {zh ? '硬件采集指标清单' : 'Hardware Metrics List'}
              </div>
              <div className="mt-0.5 text-[9px] text-black/40 dark:text-white/40">
                {zh
                  ? '默认包含 CPU 与内存指标；可根据设备支持能力按需添加温度、风扇、电源、存储等 OID。'
                  : 'CPU and memory are included by default; add optional metrics as supported.'}
              </div>
            </div>
            <div className="flex min-w-0 items-center gap-1.5">
              <select
                aria-label={zh ? '选择要添加的指标' : 'Metric to add'}
                value={addMetricKey}
                onChange={e => setAddMetricKey(e.target.value)}
                className="max-w-[180px] rounded-lg border border-black/8 bg-transparent px-2.5 py-1.5 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10"
              >
                <option value="">{zh ? '按需添加指标...' : 'Add metric...'}</option>
                {addableMetrics.map(item => (
                  <option key={item.key} value={item.key}>
                    {zh ? item.labelZh : item.labelEn}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={addMetric}
                disabled={!addMetricKey}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[#00a9ce] px-2.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-40"
              >
                <Plus size={13} />
                {zh ? '添加指标' : 'Add Metric'}
              </button>
            </div>
          </div>

          {/* Metrics Table */}
          <div className="overflow-x-auto rounded-xl border border-black/7 bg-white/35 dark:border-white/8 dark:bg-white/[.03]">
            <table className="w-full min-w-[1050px] text-left">
              <thead className="sticky top-0 z-10 bg-[var(--card-bg)] text-[9px] font-medium text-black/45 dark:text-white/45">
                <tr>
                  <th className="px-3 py-2.5">{zh ? '监控指标' : 'Metric'}</th>
                  <th className="px-2 py-2.5">{zh ? '采集方式' : 'Mode'}</th>
                  <th className="px-2 py-2.5">{zh ? 'OID 与源字段' : 'OID / Source'}</th>
                  <th className="px-2 py-2.5">{zh ? '结果类型与单位' : 'Output / Unit'}</th>
                  <th className="px-2 py-2.5">{zh ? '计算与高级参数' : 'Calculation & Parameters'}</th>
                  <th className="px-2 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {form.metrics.map(row => (
                  <MetricRowItem
                    key={row.key}
                    row={row}
                    zh={zh}
                    onPickOid={onOpenOidPicker}
                    onChange={definition =>
                      onChangeForm(prev => ({
                        ...prev,
                        metrics: prev.metrics.map(item => (item.key === row.key ? { ...item, definition } : item)),
                      }))
                    }
                    onRemove={() =>
                      onChangeForm(prev => ({
                        ...prev,
                        metrics: prev.metrics.filter(item => item.key !== row.key),
                      }))
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Interface Config Section */}
          <InterfaceConfigSection
            config={form.interfaceConfig}
            zh={zh}
            onChange={cfg => onChangeForm(prev => ({ ...prev, interfaceConfig: cfg }))}
            onPickOid={onOpenOidPicker}
            showToast={showToast}
          />

          {/* Verification Details Banner */}
          {lastTestDetails && (
            <div className="mt-4 rounded-xl border border-black/8 bg-black/[.02] p-3 text-[10px] dark:border-white/10 dark:bg-white/[.03]">
              <div className="font-semibold text-black/70 dark:text-white/75">
                {zh ? '最近一次验证明细' : 'Latest Verification Details'}
              </div>
              {lastTestDetails.interface && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span
                    className={
                      lastTestDetails.interface.passed
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-red-600 dark:text-red-400'
                    }
                  >
                    {lastTestDetails.interface.passed ? '✓' : '✕'} {zh ? '接口' : 'Interfaces'}
                  </span>
                  <span className="text-black/55 dark:text-white/55">{lastTestDetails.interface.message}</span>
                </div>
              )}
              {lastTestDetails.hardware && (
                <div className="mt-1 text-black/50 dark:text-white/50">
                  {zh ? '硬件指标：' : 'Hardware: '}
                  {Object.entries(lastTestDetails.hardware)
                    .map(([key, detail]) => `${key} ${detail?.passed ? '✓' : '✕'}`)
                    .join(' · ')}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between gap-3 border-t border-black/6 p-4 dark:border-white/8">
          {editingId ? (
            <button
              type="button"
              onClick={onDelete}
              disabled={saving}
              className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-500/10 disabled:opacity-40 dark:text-red-400"
            >
              <Trash2 size={13} />
              {zh ? '删除并回退系统默认' : 'Delete / Use Default'}
            </button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="rounded-lg border border-black/8 px-3.5 py-2 text-xs font-medium text-black/65 hover:bg-black/5 dark:border-white/10 dark:text-white/70 dark:hover:bg-white/8"
            >
              {zh ? '取消' : 'Cancel'}
            </button>
            <button
              type="button"
              onClick={onSave}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-50"
            >
              <Save size={14} />
              {saving ? (zh ? '正在保存…' : 'Saving…') : zh ? '保存型号模板' : 'Save Profile'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
