import React, { useState, useMemo } from 'react';
import { ChevronDown, ChevronUp, Plus, Save, Sparkles, Terminal, Trash2, Wrench, X } from 'lucide-react';
import { NETWORK_VENDOR_GROUPS } from '../../../pages/AssetManagement/constants';
import {
  MetricRow,
  MetricRowItem,
  METRIC_CATALOG,
  createDefinition,
  metricLabel,
} from './MetricRowItem';
import {
  InterfaceOidConfig,
  InterfaceConfigSection,
} from './InterfaceConfigSection';
import { LiveWalkInspector, CandidateDevice } from './LiveWalkInspector';
import type { InspectorTab } from './LiveWalkInspector';
import type { SnmpHardwareTestResult } from './LiveWalkInspector';
import { ModelPresetItem } from '../PresetProfilesModal';
import { ActionButton } from '../../ui/ActionIconButton';

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
  warnings?: Array<{ code?: string; severity?: string; message?: string; [key: string]: unknown }>;
  checks?: Record<
    string,
    { oid?: string; passed?: boolean; rows?: number; message?: string; counter_bits?: number }
  >;
}

interface MetricProfileEditorProps {
  editingId: string | null;
  isOfficialProfile?: boolean;
  form: ProfileForm;
  saving: boolean;
  language: string;
  candidateDevices?: CandidateDevice[];
  initialLiveInspectorOpen?: boolean;
  initialInspectorTab?: InspectorTab;
  autoMatchResult?: { matched_series?: string; confidence?: number; preset?: ModelPresetItem } | null;
  onChangeForm: (updater: (prev: ProfileForm) => ProfileForm) => void;
  onSave: () => void;
  onDelete: () => void;
  onClose: () => void;
  onOpenOidPicker: (metricKey: string, field: string) => void;
  onApplyPreset: (preset: ModelPresetItem) => void;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const MetricProfileEditor: React.FC<MetricProfileEditorProps> = ({
  editingId,
  isOfficialProfile = false,
  form,
  saving,
  language,
  candidateDevices = [],
  initialLiveInspectorOpen = false,
  initialInspectorTab = 'snmpwalk',
  autoMatchResult,
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
  const [liveInspectorOpen, setLiveInspectorOpen] = useState(initialLiveInspectorOpen);
  const [, setLiveTestResult] = useState<SnmpHardwareTestResult | null>(null);

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

  const handleSelectOidFromWalk = (metricKey: string, oid: string) => {
    if (metricKey === '__interface') {
      onChangeForm(prev => ({
        ...prev,
        interfaceConfig: {
          ...prev.interfaceConfig,
          enabled: true,
          if_hc_in_octets_oid: oid,
        },
      }));
      showToast(zh ? `已将 OID 填入接口流量: ${oid}` : `Interface OID updated: ${oid}`, 'success');
      return;
    }

    onChangeForm(prev => {
      const exists = prev.metrics.some(row => row.key === metricKey);
      const targetField = metricKey === 'storage' ? 'used_oid' : 'oid';
      if (exists) {
        return {
          ...prev,
          metrics: prev.metrics.map(row => {
            if (row.key !== metricKey) return row;
            return {
              ...row,
              definition: {
                ...row.definition,
                [targetField]: oid,
              },
            };
          }),
        };
      }
      return {
        ...prev,
        metrics: [
          ...prev.metrics,
          {
            key: metricKey,
            definition: {
              ...createDefinition(metricKey),
              [targetField]: oid,
            },
          },
        ],
      };
    });
    showToast(
      zh
        ? `已将 OID 填入【${metricLabel(metricKey, true)}】: ${oid}`
        : `${metricLabel(metricKey, false)} OID set to: ${oid}`,
      'success',
    );
  };

  return (
    <div
      className="fixed inset-0 z-[130] flex items-center justify-center bg-black/50 p-3.5 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-[1280px] flex-col overflow-hidden rounded-2xl border border-[#00bceb]/25 bg-[var(--card-bg)] shadow-2xl dark:border-white/10"
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Editor Top Bar */}
        <div className="flex items-center justify-between border-b border-black/6 px-5 py-3 dark:border-white/8">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-black/85 dark:text-white/90">
              {editingId ? (zh ? '管理型号 SNMP 模板' : 'Manage SNMP Template') : zh ? '新增自定义 SNMP 模板' : 'New Custom SNMP Template'}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"
            aria-label={zh ? '关闭' : 'Close'}
          >
            <X size={18} />
          </button>
        </div>

        {/* Scrollable Form Body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {/* Vendor and Model Inputs */}
          <div className="mb-3.5 grid gap-3 sm:grid-cols-2">
            <label className="block text-xs font-medium text-black/70 dark:text-white/70">
              {zh ? '设备厂商' : 'Vendor'}
              <select
                aria-label={zh ? '设备厂商' : 'Vendor (shared catalog)'}
                value={form.vendor}
                onChange={e => onChangeForm(prev => ({ ...prev, vendor: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-3 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]"
              >
                <option value="">{zh ? '选择厂商...' : 'Select vendor...'}</option>
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
            <label className="block text-xs font-medium text-black/70 dark:text-white/70">
              {zh ? '精确型号' : 'Exact Model'}
              <input
                value={form.model}
                onChange={e => onChangeForm(prev => ({ ...prev, model: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-3 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]"
                placeholder={zh ? '例如：S5008V6 / S5135S-16T4S / S5590-28SX-EI / C9300-48P' : '例如：C9300-48P / S6800-54QT'}
              />
            </label>
          </div>

          <div className="mb-3.5 rounded-lg border border-[#00bceb]/25 bg-[#00bceb]/[0.05] px-3 py-2 text-[11px] leading-4 text-[#006b83] dark:border-[#00bceb]/25 dark:bg-[#00bceb]/[0.08] dark:text-[#8eeaff]">
            <span className="font-semibold">{zh ? '模板匹配规则：' : 'Template matching: '}</span>
            {zh
              ? 'H3C 不是固定要求，请选择设备的实际厂商。保存后会按“厂商 + 精确型号”作为该型号的 SNMP 采集模板；S6850-1 应选择 H3C / S6800。仅在官方模板未匹配或不适配时使用自定义模板。'
              : 'H3C is not mandatory. Select the device’s actual vendor. Saving activates this profile for the exact vendor + model; S6850-1 should use H3C / S6800. Use a custom profile only when no official template matches or fits.'}
          </div>

          {/* Smart Auto Match Recommendation Capsule */}
          {autoMatchResult && autoMatchResult.preset && (
            <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#00bceb]/30 bg-[#00bceb]/[0.06] px-3 py-2 text-xs dark:bg-[#00bceb]/[0.1]">
              <div className="flex items-center gap-2">
                <Sparkles size={15} className="shrink-0 text-[#008aad] dark:text-[#00bceb]" />
                <span className="font-medium text-[#007391] dark:text-[#00bceb]">
                  {zh
                    ? `智能匹配预置：【${autoMatchResult.matched_series || autoMatchResult.preset.model}】`
                    : `Inferred Preset: [${autoMatchResult.matched_series || autoMatchResult.preset.model}]`}
                </span>
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
                className="inline-flex items-center gap-1 rounded bg-[#00a9ce] px-2.5 py-1 text-xs font-medium text-white hover:bg-[#008fb1]"
              >
                {zh ? '套用推荐 OID' : 'Apply Preset OIDs'}
              </button>
            </div>
          )}

          {/* Section Toolbar: Metrics Header + Add Metric + Toggle Diagnostic Toolkit */}
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2 border-b border-black/6 pb-2.5 dark:border-white/8">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-black/80 dark:text-white/85">
                {zh ? `监控项清单 (${form.metrics.length})` : `Items (${form.metrics.length})`}
              </span>
              <div className="flex items-center gap-1">
                <select
                  aria-label={zh ? '选择要添加的指标' : 'Metric to add'}
                  value={addMetricKey}
                  onChange={e => setAddMetricKey(e.target.value)}
                  className="rounded-md border border-black/8 bg-transparent px-2 py-1 text-xs outline-none dark:border-white/10"
                >
                  <option value="">{zh ? '按需添加指标...' : 'Add item...'}</option>
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
                  aria-label={zh ? '添加指标' : 'Add Metric'}
                  className="inline-flex items-center gap-0.5 rounded-md bg-[#00a9ce] px-2 py-1 text-xs font-semibold text-white hover:bg-[#008fb1] disabled:opacity-40"
                >
                  <Plus size={13} />
                  {zh ? '添加' : 'Add'}
                </button>
              </div>
            </div>

            {/* On-Demand SNMP Walk & Testing Toolkit Button */}
            <button
              type="button"
              onClick={() => setLiveInspectorOpen(prev => !prev)}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-all ${
                liveInspectorOpen
                  ? 'border-[#00a9ce] bg-[#00a9ce]/10 text-[#007391] dark:text-[#00c2e8]'
                  : 'border-black/8 bg-white/50 text-black/65 hover:border-black/20 dark:border-white/10 dark:bg-white/[.04] dark:text-white/70'
              }`}
            >
              <Terminal size={13} />
              <span>{zh ? 'SNMP 实时探测与 Walk 调试工具' : 'Live Walk & Test Toolkit'}</span>
              {liveInspectorOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          </div>

          {/* Collapsible Live Walk Diagnostic Toolkit */}
          {liveInspectorOpen && (
            <div className="mb-3.5">
              <LiveWalkInspector
                zh={zh}
                candidateDevices={candidateDevices}
                metrics={form.metrics}
                interfaceConfig={form.interfaceConfig}
                initialTab={initialInspectorTab}
                saving={saving}
                showToast={showToast}
                onTestResult={setLiveTestResult}
                onSelectOidForMetric={handleSelectOidFromWalk}
              />
            </div>
          )}

          {/* Clean Metrics Table */}
          <div className="overflow-x-auto rounded-xl border border-black/7 bg-white/35 shadow-sm dark:border-white/8 dark:bg-white/[.03]">
            <table className="nx-data-table nx-data-table--compact">
              <thead className="sticky top-0 z-10 bg-[var(--card-bg)] text-[10px] font-medium text-black/45 dark:text-white/45">
                <tr>
                  <th className="px-3.5 py-2">{zh ? '监控项' : 'Item'}</th>
                  <th className="px-2.5 py-2">{zh ? 'SNMP OID 与源字段' : 'SNMP OID'}</th>
                  <th className="px-2.5 py-2">{zh ? '类型/模式' : 'Type / Mode'}</th>
                  <th className="px-3 py-2 text-right">{zh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/5 dark:divide-white/5">
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

          {/* Clean Interface IF-MIB Section */}
          <InterfaceConfigSection
            config={form.interfaceConfig}
            zh={zh}
            onChange={cfg => onChangeForm(prev => ({ ...prev, interfaceConfig: cfg }))}
            onPickOid={onOpenOidPicker}
            showToast={showToast}
          />
        </div>

        {/* Editor Bottom Bar */}
        <div className="flex items-center justify-between border-t border-black/6 bg-black/[.01] px-5 py-3 dark:border-white/8 dark:bg-white/[.01]">
          {editingId ? (
            <ActionButton type="button" icon={Trash2} variant="danger" size="sm" onClick={onDelete}>
              {isOfficialProfile ? (zh ? '解绑官方模板' : 'Unbind official template') : (zh ? '删除自定义模板' : 'Delete custom template')}
            </ActionButton>
          ) : (
            <div />
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-black/8 px-3.5 py-1.5 text-xs font-medium text-black/60 hover:bg-black/5 dark:border-white/10 dark:text-white/60 dark:hover:bg-white/5"
            >
              {zh ? '取消' : 'Cancel'}
            </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving || isOfficialProfile}
            aria-label={zh ? '保存型号模板' : 'Save Profile'}
              className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
            >
              <Save size={13} />
              {isOfficialProfile
                ? (zh ? '官方模板只读' : 'Official template is read-only')
                : saving ? (zh ? '保存中...' : 'Saving...') : zh ? '保存型号模板' : 'Save Template'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MetricProfileEditor;
