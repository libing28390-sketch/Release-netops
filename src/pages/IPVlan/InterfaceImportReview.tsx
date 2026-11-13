import React, { useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, Search, X } from 'lucide-react';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { useFocusTrap } from '../../hooks/useFocusTrap';

export interface InterfaceImportRequest {
  candidate_ids: string[];
  address_space_overrides?: Record<string, string>;
}
export interface InterfaceImportGroup {
  group_id: string;
  candidate_ids: string[];
  prefix: string;
  address_space_id: string | null;
  status: 'to_create' | 'existing' | 'scope_pending';
  source_count: number;
  interface_count: number;
  ip_count: number;
  interfaces: Array<{ device_name: string; interface_name: string; address: string }>;
}
export interface InterfaceImportPreview {
  selected_candidate_count: number;
  prefix_count: number;
  new_prefix_count: number;
  existing_prefix_count: number;
  pending_candidate_count: number;
  interface_count: number;
  ip_count: number;
  new_address_count: number;
  existing_address_count: number;
  can_generate: boolean;
  blockers: string[];
  groups: InterfaceImportGroup[];
}

export default function InterfaceImportReview({ request, spaceLabels, zh, submitting, generationError, onBack, onConfirm }: {
  request: InterfaceImportRequest;
  spaceLabels: Record<string, string>;
  zh: boolean;
  submitting: boolean;
  generationError: string;
  onBack: () => void;
  onConfirm: (request: InterfaceImportRequest) => void;
}) {
  const [preview, setPreview] = useState<InterfaceImportPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [groupSearch, setGroupSearch] = useState('');
  const [groupPage, setGroupPage] = useState(1);
  const dialogRef = useRef<HTMLElement>(null);
  const requestKey = JSON.stringify(request);
  const groupPageSize = 8;
  useFocusTrap(dialogRef, true);
  useEscapeClose(!submitting, onBack);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setPreview(null);
    setError('');
    setGroupSearch('');
    setGroupPage(1);
    const token = localStorage.getItem('netops_token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    fetch('/api/ipam/prefixes/interface-import-preview', {
      method: 'POST', headers, body: requestKey, signal: controller.signal,
    }).then(async response => {
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(response.status === 401
        ? (zh ? '登录已失效，请重新登录。' : 'Your session expired. Sign in again.')
        : response.status === 403
          ? (zh ? '当前账号没有导入这些网段的权限。' : 'You do not have permission to import these prefixes.')
          : response.status === 404
            ? (zh ? '来源已变化或不可访问，请返回刷新后重新选择。' : 'Sources changed or are inaccessible. Go back, refresh, and select again.')
            : typeof payload.detail === 'string' ? payload.detail
              : (zh ? '核对失败，请稍后重试。' : 'Could not verify the import. Retry shortly.'));
      if (!Array.isArray(payload.groups) || typeof payload.can_generate !== 'boolean'
        || !Array.isArray(payload.blockers)
        || !['prefix_count', 'new_prefix_count', 'existing_prefix_count', 'new_address_count', 'existing_address_count', 'pending_candidate_count', 'ip_count']
          .every(key => Number.isInteger(payload[key]) && payload[key] >= 0)
        || !payload.groups.every((group: unknown) => {
          if (!group || typeof group !== 'object') return false;
          const row = group as Record<string, unknown>;
          return typeof row.group_id === 'string' && typeof row.prefix === 'string'
            && ['to_create', 'existing', 'scope_pending'].includes(String(row.status))
            && Array.isArray(row.interfaces) && row.interfaces.every(source => source && typeof source === 'object')
            && Number.isInteger(row.interface_count) && Number(row.interface_count) >= 0
            && Number.isInteger(row.ip_count) && Number(row.ip_count) >= 0;
        })) {
        throw new Error(zh ? '预览数据不完整，请刷新后重试。' : 'The preview is incomplete. Refresh and retry.');
      }
      if (!controller.signal.aborted) setPreview(payload);
    }).catch(error => {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : String(error));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [requestKey, retry, zh]);

  const filteredGroups = useMemo(() => {
    const groups = preview?.groups || [];
    const query = groupSearch.trim().toLocaleLowerCase();
    if (!query) return groups;
    return groups.filter(group => {
      const status = group.status === 'existing'
        ? (zh ? '已存在 复用' : 'existing reuse')
        : group.status === 'scope_pending'
          ? (zh ? '网络归属未确认' : 'address space unconfirmed')
          : (zh ? '将新建 待创建' : 'new prefix to create');
      const text = [
        group.prefix,
        group.address_space_id,
        group.address_space_id ? spaceLabels[group.address_space_id] : '',
        status,
        ...group.interfaces.flatMap(source => [source.device_name, source.interface_name, source.address]),
      ].join(' ').toLocaleLowerCase();
      return text.includes(query);
    });
  }, [preview, groupSearch, spaceLabels, zh]);
  const groupTotalPages = Math.max(1, Math.ceil(filteredGroups.length / groupPageSize));
  const visibleGroupPage = Math.min(groupPage, groupTotalPages);
  const visibleGroups = filteredGroups.slice((visibleGroupPage - 1) * groupPageSize, visibleGroupPage * groupPageSize);

  const nothingToImport = Boolean(preview && preview.new_prefix_count === 0 && preview.new_address_count === 0 && preview.pending_candidate_count === 0);
  const canConfirm = Boolean(preview?.can_generate && !nothingToImport && !loading && !submitting && !error);
  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-3 sm:p-5">
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="interface-import-review-title" className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl">
      <header className="flex items-start justify-between gap-3 border-b border-[var(--ui-border)] px-5 py-4">
        <div><h2 id="interface-import-review-title" className="font-bold">{zh ? '核对导入结果' : 'Review interface import'}</h2><p className="mt-1 text-xs text-[var(--ui-fg-muted)]">{zh ? '同一网络归属、同一 CIDR 合为一个网段，保留各设备接口 IP。已有记录会复用。' : 'The same address space and CIDR form one prefix with its device interface IPs. Existing records are reused.'}</p></div>
        <button type="button" disabled={submitting} onClick={onBack} aria-label={zh ? '返回选择' : 'Back to selection'} className="rounded-lg p-1"><X size={16} /></button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-5">
        {loading && <div role="status" className="flex items-center gap-2 py-6 text-sm"><RefreshCw size={16} className="animate-spin" />{zh ? '正在核对当前台账…' : 'Checking the current ledger…'}</div>}
        {error && <div role="alert" className="rounded-xl bg-rose-50 p-3 text-xs text-rose-700">{error}<button type="button" onClick={() => setRetry(value => value + 1)} className="ml-3 underline">{zh ? '重试' : 'Retry'}</button></div>}
        {generationError && <div role="alert" className="rounded-xl bg-rose-50 p-3 text-xs text-rose-700">{generationError}</div>}
        {preview && <>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4" aria-label={zh ? '本次导入统计' : 'Import summary'}>
            {[
              [zh ? '实际网段' : 'Prefixes', preview.prefix_count],
              [zh ? '新建网段' : 'New prefixes', preview.new_prefix_count],
              [zh ? '复用已有网段' : 'Existing prefixes', preview.existing_prefix_count],
              [zh ? '补充接口 IP' : 'New interface IPs', preview.new_address_count],
            ].map(([label, count]) => <div key={label} className="rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3"><div className="text-[var(--ui-fg-muted)]">{label}</div><strong className="mt-1 block text-base tabular-nums">{count}</strong></div>)}
          </div>
          <p className="text-xs text-[var(--ui-fg-muted)]">{zh ? `所选 ${preview.selected_candidate_count} 项来源，涉及 ${preview.ip_count} 个接口 IP，其中 ${preview.existing_address_count} 个已登记。` : `${preview.selected_candidate_count} selected sources contain ${preview.ip_count} IPs; ${preview.existing_address_count} are already registered.`}</p>
          {nothingToImport && <div role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{zh ? '这些网段和接口 IP 已全部登记，无需重复导入。' : 'These prefixes and interface IPs are already registered. No import is needed.'}</div>}
          {preview.blockers.length > 0 && <div role="alert" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900"><div className="font-semibold">{zh ? '请先处理以下问题' : 'Resolve these issues first'}</div><ul className="mt-2 list-inside list-disc space-y-1">{preview.blockers.map((message, index) => <li key={index}>{message}</li>)}</ul></div>}
          {preview.groups.length > groupPageSize && <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="relative min-w-0 flex-1">
              <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ui-fg-muted)]" />
              <input
                type="search"
                aria-label={zh ? '搜索待导入网段' : 'Search prefixes to import'}
                value={groupSearch}
                maxLength={120}
                onChange={event => { setGroupSearch(event.target.value); setGroupPage(1); }}
                placeholder={zh ? '按 CIDR、设备、接口或 IP 搜索' : 'Search by CIDR, device, interface, or IP'}
                disabled={loading || submitting}
                className="h-9 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] pl-9 pr-3 text-xs outline-none focus:border-[var(--ui-accent)] disabled:opacity-60"
              />
            </label>
            <div className="flex items-center justify-between gap-3 text-xs text-[var(--ui-fg-muted)] sm:justify-end">
              <span>{zh ? `匹配 ${filteredGroups.length} / ${preview.groups.length} 个网段` : `${filteredGroups.length} of ${preview.groups.length} prefixes`}</span>
              {groupSearch && <button type="button" onClick={() => { setGroupSearch(''); setGroupPage(1); }} disabled={loading || submitting} className="rounded-lg border border-[var(--ui-border)] px-2.5 py-1.5 font-semibold hover:bg-[var(--ui-surface-muted)] disabled:opacity-50">{zh ? '清除' : 'Clear'}</button>}
            </div>
          </div>}
          <div className="overflow-hidden rounded-xl border border-[var(--ui-border)]">
            {visibleGroups.map(group => <div key={group.group_id} className="border-b border-[var(--ui-border)] p-3 last:border-0">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs"><strong className="font-mono">{group.prefix}</strong><span>{group.status === 'existing' ? (zh ? '已存在 · 复用' : 'Existing · reuse') : group.status === 'scope_pending' ? (zh ? '网络归属未确认' : 'Address space unconfirmed') : (zh ? '将新建' : 'New prefix')}</span></div>
              <div className="mt-1 text-xs text-[var(--ui-fg-muted)]">{zh ? '网络归属：' : 'Address space: '}{group.address_space_id ? spaceLabels[group.address_space_id] || (zh ? '已确认网络（名称未加载）' : 'Confirmed space (name unavailable)') : (zh ? '未确认' : 'Unconfirmed')}</div>
              <div className="mt-1 text-xs text-[var(--ui-fg-muted)]">{zh ? `${group.interface_count} 个接口 · ${group.ip_count} 个 IP` : `${group.interface_count} interfaces · ${group.ip_count} IPs`}</div>
              {group.interfaces.map((source, index) => <div key={index} className="mt-1 break-words text-xs text-[var(--ui-fg-muted)]">{source.device_name} · {source.interface_name} · <span className="font-mono">{source.address}</span></div>)}
              {group.interface_count > group.interfaces.length && <div className="mt-1 text-xs text-[var(--ui-fg-muted)]">{zh ? '还有其他接口来源' : 'Additional interface sources'}</div>}
            </div>)}
            {visibleGroups.length === 0 && <div role="status" className="p-8 text-center text-xs text-[var(--ui-fg-muted)]">{zh ? '没有匹配的网段。' : 'No matching prefixes.'}</div>}
          </div>
          {preview.groups.length > groupPageSize && <div className="flex items-center justify-between gap-3 text-xs text-[var(--ui-fg-muted)]">
            <span>{zh ? `第 ${visibleGroupPage} / ${groupTotalPages} 页` : `Page ${visibleGroupPage} of ${groupTotalPages}`}</span>
            <div className="flex gap-2">
              <button type="button" onClick={() => setGroupPage(Math.max(1, visibleGroupPage - 1))} disabled={visibleGroupPage <= 1 || loading || submitting} className="rounded-lg border border-[var(--ui-border)] px-3 py-1.5 font-semibold disabled:opacity-40">{zh ? '上一页' : 'Previous'}</button>
              <button type="button" onClick={() => setGroupPage(Math.min(groupTotalPages, visibleGroupPage + 1))} disabled={visibleGroupPage >= groupTotalPages || loading || submitting} className="rounded-lg border border-[var(--ui-border)] px-3 py-1.5 font-semibold disabled:opacity-40">{zh ? '下一页' : 'Next'}</button>
            </div>
          </div>}
        </>}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t border-[var(--ui-border)] px-5 py-3">
        <button type="button" disabled={submitting} onClick={onBack} className="rounded-lg border border-[var(--ui-border)] px-3 py-2 text-xs">{zh ? '返回选择' : 'Back to selection'}</button>
        <button type="button" disabled={!canConfirm} onClick={() => onConfirm(request)} className="rounded-lg bg-[var(--ui-accent)] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{submitting ? (zh ? '导入中…' : 'Importing…') : nothingToImport ? (zh ? '已全部登记' : 'Already registered') : (zh ? '确认导入' : 'Confirm import')}</button>
      </footer>
    </section>
  </div>;
}
