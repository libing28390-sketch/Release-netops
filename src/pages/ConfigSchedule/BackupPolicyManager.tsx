import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarClock, Check, ChevronDown, ChevronUp, Clock3, Eye, Loader2,
  Pencil, Play, Plus, RefreshCw, Server, ShieldCheck, Trash2, X,
} from 'lucide-react';
import { apiRequest } from '../../api/http';
import TagConditionPicker, {
  hasTagFilterConditions,
  type TagFilterConfig,
} from '../../components/TagConditionPicker';
import type { Device } from '../../types';

interface BackupScope {
  site_ids: string[];
  roles: string[];
  platforms: string[];
  vendors: string[];
  device_ids: string[];
  exclude_device_ids: string[];
  tag_expression: TagFilterConfig['expression'] | null;
}

interface BackupPolicy {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  cron_expr: string;
  timezone: string;
  priority: number;
  scope: BackupScope;
  config_types: string[];
  change_only: boolean;
  retention_days: number;
  max_versions_per_device: number;
  concurrency: number;
  retry_count: number;
  timeout_seconds: number;
  updated_at: string;
}

interface PolicyDraft extends Omit<BackupPolicy, 'id' | 'updated_at' | 'scope'> {
  id?: string;
  scope: BackupScope;
  tagFilter: TagFilterConfig;
}

interface PreviewDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  vendor: string;
  role: string;
  site: string;
  status: string;
}

interface PolicyPreview {
  items: PreviewDevice[];
  total: number;
  online: number;
  offline: number;
}

interface BackupPolicyManagerProps {
  language: string;
  devices: Device[];
  getVendorFromPlatform: (platform?: string) => string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

interface Choice {
  value: string;
  label: string;
  count: number;
}

const emptyTagFilter = (): TagFilterConfig => ({
  expression: {
    operator: 'and',
    negated: false,
    tag_ids: [],
    groups: [],
  },
  groups: [],
  exclude_tag_ids: [],
});

const emptyScope = (): BackupScope => ({
  site_ids: [],
  roles: [],
  platforms: [],
  vendors: [],
  device_ids: [],
  exclude_device_ids: [],
  tag_expression: null,
});

const newDraft = (): PolicyDraft => ({
  name: '',
  description: '',
  enabled: true,
  cron_expr: '0 2 * * *',
  timezone: 'Asia/Shanghai',
  priority: 100,
  scope: emptyScope(),
  tagFilter: emptyTagFilter(),
  config_types: ['running'],
  change_only: true,
  retention_days: 90,
  max_versions_per_device: 30,
  concurrency: 10,
  retry_count: 1,
  timeout_seconds: 30,
});

const toDraft = (policy: BackupPolicy): PolicyDraft => ({
  ...policy,
  scope: {
    ...emptyScope(),
    ...policy.scope,
  },
  tagFilter: policy.scope.tag_expression
    ? {
        expression: structuredClone(policy.scope.tag_expression),
        groups: [],
        exclude_tag_ids: [],
      }
    : emptyTagFilter(),
});

const buildChoices = (
  devices: Device[],
  valueOf: (device: Device) => string,
  labelOf: (device: Device, value: string) => string = (_device, value) => value,
): Choice[] => {
  const values = new Map<string, Choice>();
  devices.forEach((device) => {
    const value = valueOf(device).trim();
    if (!value) return;
    const current = values.get(value);
    if (current) {
      current.count += 1;
    } else {
      values.set(value, { value, label: labelOf(device, value), count: 1 });
    }
  });
  return Array.from(values.values()).sort((a, b) => a.label.localeCompare(b.label));
};

const ChoicePicker: React.FC<{
  title: string;
  choices: Choice[];
  selected: string[];
  onChange: (values: string[]) => void;
}> = ({ title, choices, selected, onChange }) => {
  const [open, setOpen] = useState(false);
  const toggle = (value: string) => {
    onChange(selected.includes(value)
      ? selected.filter((item) => item !== value)
      : [...selected, value]);
  };
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <span className="text-xs font-semibold text-slate-700">
          {title}
          {selected.length > 0 && <span className="ml-1 text-cyan-600">({selected.length})</span>}
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && (
        <div className="max-h-36 overflow-auto border-t border-slate-100 p-2">
          {choices.length === 0 ? (
            <p className="px-2 py-3 text-center text-[11px] text-slate-400">暂无可选项</p>
          ) : choices.map((choice) => (
            <label key={choice.value} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50">
              <input
                type="checkbox"
                checked={selected.includes(choice.value)}
                onChange={() => toggle(choice.value)}
                className="accent-cyan-600"
              />
              <span className="min-w-0 flex-1 truncate text-xs text-slate-600">{choice.label}</span>
              <span className="text-[10px] text-slate-400">{choice.count}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
};

const BackupPolicyManager: React.FC<BackupPolicyManagerProps> = ({
  language,
  devices,
  getVendorFromPlatform,
  showToast,
}) => {
  const zh = language === 'zh';
  const [policies, setPolicies] = useState<BackupPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [draft, setDraft] = useState<PolicyDraft | null>(null);
  const [preview, setPreview] = useState<PolicyPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [runningId, setRunningId] = useState('');

  const siteChoices = useMemo(() => buildChoices(
    devices,
    (device) => device.site_id || device.site || '',
    (device, value) => device.site_name || device.site || value,
  ), [devices]);
  const roleChoices = useMemo(
    () => buildChoices(devices, (device) => device.role || ''),
    [devices],
  );
  const platformChoices = useMemo(
    () => buildChoices(devices, (device) => device.platform || ''),
    [devices],
  );
  const vendorChoices = useMemo(() => buildChoices(
    devices,
    (device) => device.vendor || getVendorFromPlatform(device.platform),
  ), [devices, getVendorFromPlatform]);

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    try {
      const response = await apiRequest<{
        success: boolean;
        data: { items: BackupPolicy[] };
      }>('/api/configs/backup-policies?page=1&page_size=100');
      setPolicies(response.data.items);
    } catch (error) {
      showToast(error instanceof Error ? error.message : '备份策略加载失败', 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void loadPolicies();
  }, [loadPolicies]);

  const updateDraft = (patch: Partial<PolicyDraft>) => {
    setDraft((current) => current ? { ...current, ...patch } : current);
    setPreview(null);
  };

  const updateScope = (key: keyof BackupScope, values: string[]) => {
    if (!draft) return;
    updateDraft({ scope: { ...draft.scope, [key]: values } });
  };

  const payloadFromDraft = (value: PolicyDraft) => {
    const { id: _id, tagFilter, ...payload } = value;
    return {
      ...payload,
      scope: {
        ...payload.scope,
        tag_expression: hasTagFilterConditions(tagFilter) ? tagFilter.expression : null,
      },
    };
  };

  const handlePreview = async () => {
    if (!draft) return;
    setPreviewing(true);
    try {
      const response = await apiRequest<{ success: boolean; data: PolicyPreview }>(
        '/api/configs/backup-policies/preview?page=1&page_size=12',
        { method: 'POST', body: JSON.stringify(payloadFromDraft(draft)) },
      );
      setPreview(response.data);
    } catch (error) {
      showToast(error instanceof Error ? error.message : '预览失败', 'error');
    } finally {
      setPreviewing(false);
    }
  };

  const handleSave = async () => {
    if (!draft || preview === null) return;
    if (!draft.name.trim()) {
      showToast(zh ? '请填写策略名称' : 'Policy name is required', 'error');
      return;
    }
    setSaving(true);
    try {
      await apiRequest(
        draft.id
          ? `/api/configs/backup-policies/${encodeURIComponent(draft.id)}`
          : '/api/configs/backup-policies',
        {
          method: draft.id ? 'PUT' : 'POST',
          body: JSON.stringify(payloadFromDraft(draft)),
        },
      );
      showToast(zh ? '备份策略已保存并重新调度' : 'Policy saved and rescheduled', 'success');
      setDraft(null);
      setPreview(null);
      await loadPolicies();
    } catch (error) {
      showToast(error instanceof Error ? error.message : '保存失败', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleRun = async (policy: BackupPolicy) => {
    setRunningId(policy.id);
    try {
      await apiRequest(`/api/configs/backup-policies/${encodeURIComponent(policy.id)}/run`, {
        method: 'POST',
      });
      showToast(zh ? `已启动“${policy.name}”` : `Started ${policy.name}`, 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : '启动失败', 'error');
    } finally {
      setRunningId('');
    }
  };

  const handleDelete = async (policy: BackupPolicy) => {
    if (!window.confirm(zh ? `确认删除备份策略“${policy.name}”？` : `Delete policy "${policy.name}"?`)) return;
    try {
      await apiRequest(`/api/configs/backup-policies/${encodeURIComponent(policy.id)}`, {
        method: 'DELETE',
      });
      showToast(zh ? '备份策略已删除' : 'Policy deleted', 'success');
      await loadPolicies();
    } catch (error) {
      showToast(error instanceof Error ? error.message : '删除失败', 'error');
    }
  };

  return (
    <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <button type="button" onClick={() => setExpanded((value) => !value)} className="flex items-center gap-3 text-left">
          <span className="rounded-2xl bg-cyan-50 p-2.5 text-cyan-600"><ShieldCheck size={20} /></span>
          <span>
            <span className="block text-sm font-bold text-slate-800">{zh ? '备份策略中心' : 'Backup policy center'}</span>
            <span className="block text-[11px] text-slate-400">
              {zh ? `${policies.length} 条策略 · 范围预览与实际执行使用同一筛选规则` : `${policies.length} policies · preview and execution share one resolver`}
            </span>
          </span>
          {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
        </button>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void loadPolicies()} className="rounded-xl border border-slate-200 p-2 text-slate-500 hover:bg-slate-50" title={zh ? '刷新' : 'Refresh'}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            type="button"
            onClick={() => { setDraft(newDraft()); setPreview(null); }}
            className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white hover:bg-cyan-700"
          >
            <Plus size={14} />{zh ? '新建策略' : 'New policy'}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 p-4">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-400"><Loader2 size={16} className="animate-spin" />{zh ? '加载策略...' : 'Loading...'}</div>
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">
              {policies.map((policy) => {
                const scopeCount = policy.scope.site_ids.length
                  + policy.scope.roles.length
                  + policy.scope.platforms.length
                  + policy.scope.vendors.length
                  + (policy.scope.tag_expression ? 1 : 0);
                return (
                  <article key={policy.id} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`h-2 w-2 rounded-full ${policy.enabled ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                          <h4 className="truncate text-sm font-bold text-slate-800">{policy.name}</h4>
                        </div>
                        <p className="mt-1 line-clamp-2 text-[11px] text-slate-400">{policy.description || (zh ? '暂无说明' : 'No description')}</p>
                      </div>
                      <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-bold ${policy.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'}`}>
                        {policy.enabled ? (zh ? '已启用' : 'Enabled') : (zh ? '已停用' : 'Disabled')}
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-4 gap-2">
                      <div className="rounded-xl bg-white px-2 py-2"><Clock3 size={12} className="mb-1 text-cyan-500" /><p className="truncate font-mono text-[10px] text-slate-600">{policy.cron_expr}</p></div>
                      <div className="rounded-xl bg-white px-2 py-2"><Server size={12} className="mb-1 text-violet-500" /><p className="text-[10px] text-slate-600">{scopeCount ? `${scopeCount} ${zh ? '项范围' : 'filters'}` : (zh ? '全网' : 'All')}</p></div>
                      <div className="rounded-xl bg-white px-2 py-2"><CalendarClock size={12} className="mb-1 text-amber-500" /><p className="text-[10px] text-slate-600">{policy.retention_days} {zh ? '天' : 'days'}</p></div>
                      <div className="rounded-xl bg-white px-2 py-2"><Check size={12} className="mb-1 text-emerald-500" /><p className="text-[10px] text-slate-600">{policy.change_only ? (zh ? '仅变更' : 'Changed') : (zh ? '每次归档' : 'Every run')}</p></div>
                    </div>
                    <div className="mt-3 flex justify-end gap-1.5">
                      <button type="button" onClick={() => void handleRun(policy)} disabled={runningId === policy.id} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] text-slate-600 hover:border-cyan-200 hover:text-cyan-700 disabled:opacity-50">
                        {runningId === policy.id ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}{zh ? '立即执行' : 'Run'}
                      </button>
                      <button type="button" onClick={() => { setDraft(toDraft(policy)); setPreview(null); }} className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 hover:text-cyan-700" title={zh ? '编辑' : 'Edit'}><Pencil size={13} /></button>
                      {policy.id !== 'backup-policy-default' && (
                        <button type="button" onClick={() => void handleDelete(policy)} className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-400 hover:border-rose-200 hover:text-rose-600" title={zh ? '删除' : 'Delete'}><Trash2 size={13} /></button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      )}

      {draft && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
          <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] bg-white shadow-2xl">
            <header className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
              <div>
                <h3 className="text-base font-bold text-slate-800">{draft.id ? (zh ? '编辑备份策略' : 'Edit policy') : (zh ? '新建备份策略' : 'New policy')}</h3>
                <p className="text-[11px] text-slate-400">{zh ? '保存前必须预览命中设备，确认范围正确' : 'Preview matched devices before saving'}</p>
              </div>
              <button type="button" onClick={() => { setDraft(null); setPreview(null); }} className="rounded-xl p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
            </header>

            <div className="flex-1 overflow-auto p-6">
              <div className="grid gap-6 lg:grid-cols-2">
                <div className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="text-xs font-semibold text-slate-600">
                      {zh ? '策略名称 *' : 'Policy name *'}
                      <input value={draft.name} onChange={(event) => updateDraft({ name: event.target.value })} className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
                    </label>
                    <label className="text-xs font-semibold text-slate-600">
                      Cron
                      <input value={draft.cron_expr} onChange={(event) => updateDraft({ cron_expr: event.target.value })} className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2 font-mono text-sm outline-none focus:border-cyan-400" />
                    </label>
                  </div>
                  <label className="block text-xs font-semibold text-slate-600">
                    {zh ? '说明' : 'Description'}
                    <textarea value={draft.description} onChange={(event) => updateDraft({ description: event.target.value })} rows={2} className="mt-1.5 w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
                  </label>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <ChoicePicker title={zh ? '站点' : 'Sites'} choices={siteChoices} selected={draft.scope.site_ids} onChange={(values) => updateScope('site_ids', values)} />
                    <ChoicePicker title={zh ? '设备角色' : 'Roles'} choices={roleChoices} selected={draft.scope.roles} onChange={(values) => updateScope('roles', values)} />
                    <ChoicePicker title={zh ? '厂商' : 'Vendors'} choices={vendorChoices} selected={draft.scope.vendors} onChange={(values) => updateScope('vendors', values)} />
                    <ChoicePicker title={zh ? '平台型号' : 'Platforms'} choices={platformChoices} selected={draft.scope.platforms} onChange={(values) => updateScope('platforms', values)} />
                  </div>
                  <div className="rounded-2xl border border-slate-200 p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-700">{zh ? '标签条件（支持嵌套与 / 或 / 非）' : 'Nested tag expression'}</span>
                      {hasTagFilterConditions(draft.tagFilter) && (
                        <button type="button" onClick={() => updateDraft({ tagFilter: emptyTagFilter() })} className="text-[11px] text-slate-400 hover:text-rose-500">{zh ? '清空' : 'Clear'}</button>
                      )}
                    </div>
                    <TagConditionPicker
                      value={draft.tagFilter}
                      onChange={(tagFilter) => updateDraft({ tagFilter })}
                      language={language}
                    />
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <h4 className="mb-3 text-xs font-bold text-slate-700">{zh ? '执行与保留' : 'Execution and retention'}</h4>
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        ['retention_days', zh ? '保留天数' : 'Retention days', 1, 3650],
                        ['max_versions_per_device', zh ? '单设备版本数' : 'Versions/device', 1, 5000],
                        ['concurrency', zh ? '并发数' : 'Concurrency', 1, 50],
                        ['retry_count', zh ? '失败重试' : 'Retries', 0, 5],
                        ['timeout_seconds', zh ? '超时（秒）' : 'Timeout (s)', 5, 300],
                        ['priority', zh ? '调度优先级' : 'Priority', 1, 1000],
                      ].map(([key, label, min, max]) => (
                        <label key={String(key)} className="text-[11px] font-semibold text-slate-500">
                          {label}
                          <input
                            type="number"
                            min={Number(min)}
                            max={Number(max)}
                            value={Number(draft[key as keyof PolicyDraft])}
                            onChange={(event) => updateDraft({ [key]: Number(event.target.value) })}
                            className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-cyan-400"
                          />
                        </label>
                      ))}
                    </div>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      <label className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
                        <input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft({ enabled: event.target.checked })} className="accent-cyan-600" />
                        {zh ? '启用自动调度' : 'Enable scheduling'}
                      </label>
                      <label className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
                        <input type="checkbox" checked={draft.change_only} onChange={(event) => updateDraft({ change_only: event.target.checked })} className="accent-cyan-600" />
                        {zh ? '配置未变化时不重复归档' : 'Archive only changes'}
                      </label>
                    </div>
                  </div>

                  <div className={`rounded-2xl border p-4 ${preview ? 'border-cyan-200 bg-cyan-50/50' : 'border-dashed border-slate-300 bg-white'}`}>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <h4 className="text-xs font-bold text-slate-700">{zh ? '命中设备预览' : 'Target preview'}</h4>
                        <p className="mt-0.5 text-[10px] text-slate-400">{zh ? '修改任一条件后需要重新预览' : 'Re-preview after any change'}</p>
                      </div>
                      <button type="button" onClick={() => void handlePreview()} disabled={previewing} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">
                        {previewing ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}{zh ? '预览命中设备' : 'Preview'}
                      </button>
                    </div>
                    {preview && (
                      <>
                        <div className="mt-3 grid grid-cols-3 gap-2">
                          <div className="rounded-xl bg-white p-2 text-center"><strong className="block text-lg text-slate-800">{preview.total}</strong><span className="text-[10px] text-slate-400">{zh ? '命中' : 'Matched'}</span></div>
                          <div className="rounded-xl bg-white p-2 text-center"><strong className="block text-lg text-emerald-600">{preview.online}</strong><span className="text-[10px] text-slate-400">{zh ? '在线' : 'Online'}</span></div>
                          <div className="rounded-xl bg-white p-2 text-center"><strong className="block text-lg text-amber-500">{preview.offline}</strong><span className="text-[10px] text-slate-400">{zh ? '离线' : 'Offline'}</span></div>
                        </div>
                        <div className="mt-3 max-h-52 overflow-auto rounded-xl border border-cyan-100 bg-white">
                          {preview.items.map((device) => (
                            <div key={device.id} className="flex items-center gap-3 border-b border-slate-100 px-3 py-2 last:border-0">
                              <span className={`h-2 w-2 shrink-0 rounded-full ${device.status === 'online' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                              <span className="min-w-0 flex-1"><strong className="block truncate text-xs text-slate-700">{device.hostname}</strong><span className="block truncate text-[10px] text-slate-400">{device.ip_address} · {device.platform}</span></span>
                              <span className="text-[10px] text-slate-400">{device.site || '—'}</span>
                            </div>
                          ))}
                          {preview.items.length === 0 && <p className="py-8 text-center text-xs text-amber-600">{zh ? '当前条件未命中任何设备，请调整后重新预览' : 'No devices matched'}</p>}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <footer className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-6 py-4">
              <p className="text-[11px] text-slate-400">
                {preview === null
                  ? (zh ? '请先预览，确认命中范围后才能保存' : 'Preview is required before saving')
                  : (zh ? `已确认 ${preview.total} 台设备` : `${preview.total} devices confirmed`)}
              </p>
              <div className="flex gap-2">
                <button type="button" onClick={() => { setDraft(null); setPreview(null); }} className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-500">{zh ? '取消' : 'Cancel'}</button>
                <button type="button" onClick={() => void handleSave()} disabled={preview === null || saving} className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-35">
                  {saving ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}{zh ? '确认并保存' : 'Confirm and save'}
                </button>
              </div>
            </footer>
          </div>
        </div>
      )}
    </section>
  );
};

export default BackupPolicyManager;
