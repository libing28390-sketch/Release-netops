import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, Check, Loader2, Search, X } from 'lucide-react';
import { apiRequest } from '../../api/http';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import type { CandidateDevice } from './components/LiveWalkInspector';

export type CmdbDeviceCandidate = CandidateDevice & {
  site?: string;
  site_name?: string;
};

export interface CmdbDevicePickerProps {
  open: boolean;
  onClose: () => void;
  language?: 'zh' | 'en';
  onSelect: (device: CmdbDeviceCandidate) => void;
  selectedDeviceId?: string;
  initialQuery?: string;
}

interface NetworkDeviceItem {
  id?: string | number;
  device_id?: string | number;
  hostname?: string | null;
  ip_address?: string | null;
  status?: string | null;
  platform?: string | null;
  vendor?: string | null;
  model?: string | null;
  version?: string | null;
}

interface NetworkDeviceSearchResponse {
  items?: NetworkDeviceItem[];
  has_more?: boolean;
}

const normalizeCandidate = (item: NetworkDeviceItem): CmdbDeviceCandidate | null => {
  const deviceId = String(item.device_id ?? item.id ?? '').trim();
  if (!deviceId) return null;
  const ipAddress = String(item.ip_address ?? '').trim();
  return {
    device_id: deviceId,
    hostname: String(item.hostname || ipAddress || deviceId).trim(),
    ip_address: ipAddress,
    status: String(item.status ?? '').trim(),
    vendor: String(item.vendor ?? '').trim(),
    platform: String(item.platform ?? '').trim(),
    model: String(item.model ?? '').trim(),
    version: String(item.version ?? '').trim(),
  };
};

const statusLabel = (status: string, zh: boolean) => {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'online' || normalized === 'up') return zh ? '在线' : 'Online';
  if (normalized === 'offline' || normalized === 'down') return zh ? '离线' : 'Offline';
  if (normalized === 'disabled') return zh ? '已禁用' : 'Disabled';
  return status || (zh ? '未知' : 'Unknown');
};

const statusClass = (status: string) => {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'online' || normalized === 'up') return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
  if (normalized === 'offline' || normalized === 'down') return 'bg-rose-500/10 text-rose-700 dark:text-rose-300';
  return 'bg-slate-500/10 text-slate-600 dark:text-slate-300';
};

const CmdbDevicePicker: React.FC<CmdbDevicePickerProps> = ({
  open,
  onClose,
  language = 'zh',
  onSelect,
  selectedDeviceId,
  initialQuery = '',
}) => {
  const zh = language === 'zh';
  const [query, setQuery] = useState(initialQuery);
  const [rows, setRows] = useState<CmdbDeviceCandidate[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestSequence = useRef(0);

  useEscapeClose(open, onClose);

  useEffect(() => {
    if (!open) return;
    setQuery(initialQuery);
    setError('');
  }, [open, initialQuery]);

  useEffect(() => {
    if (!open) return;
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      setRows([]);
      setHasMore(false);
      setLoading(false);
      setError('');
      return;
    }

    const controller = new AbortController();
    const requestId = ++requestSequence.current;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError('');
      const params = new URLSearchParams({ q: cleanQuery, limit: '100' });
      try {
        const response = await apiRequest<NetworkDeviceSearchResponse>(
          `/api/monitoring/network-device-search?${params.toString()}`,
          { signal: controller.signal },
        );
        if (requestId !== requestSequence.current) return;
        const items = Array.isArray(response.items) ? response.items : [];
        setRows(items.map(normalizeCandidate).filter((item): item is CmdbDeviceCandidate => Boolean(item)));
        setHasMore(Boolean(response.has_more));
      } catch (requestError) {
        if (controller.signal.aborted || requestId !== requestSequence.current) return;
        setRows([]);
        setHasMore(false);
        setError(requestError instanceof Error ? requestError.message : (zh ? '设备搜索失败' : 'Device search failed'));
      } finally {
        if (!controller.signal.aborted && requestId === requestSequence.current) setLoading(false);
      }
    }, 220);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, query, zh]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[160] flex items-center justify-center bg-slate-950/50 p-3 backdrop-blur-[2px] sm:p-5"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="cmdb-snmp-device-picker-title"
        className="flex max-h-[82vh] w-full max-w-[720px] flex-col overflow-hidden rounded-xl border border-black/10 bg-[var(--card-bg)] shadow-2xl dark:border-white/10"
        onMouseDown={event => event.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-3 border-b border-black/8 px-4 py-3 dark:border-white/8">
          <div className="min-w-0">
            <h2 id="cmdb-snmp-device-picker-title" className="text-sm font-semibold text-black/85 dark:text-white/90">
              {zh ? '选择诊断设备' : 'Select a diagnostic device'}
            </h2>
            <p className="mt-0.5 text-[11px] text-black/45 dark:text-white/45">
              {zh ? '搜索主机名或管理 IP；列表只显示设备名称、IP 和状态。' : 'Search by hostname or management IP. Results show only name, IP, and status.'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={zh ? '关闭设备选择' : 'Close device picker'}
            title={zh ? '关闭设备选择' : 'Close device picker'}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-black/45 hover:bg-black/[.05] hover:text-black/80 focus:outline-none focus:ring-2 focus:ring-[#00bceb]/50 dark:text-white/50 dark:hover:bg-white/[.08] dark:hover:text-white"
          >
            <X size={16} />
          </button>
        </header>

        <div className="border-b border-black/6 p-3 dark:border-white/8">
          <div className="relative">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/35 dark:text-white/35" />
            <input
              autoFocus
              type="search"
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder={zh ? '输入设备名称或管理 IP 搜索' : 'Search hostname or management IP'}
              aria-label={zh ? '搜索诊断设备' : 'Search diagnostic devices'}
              className="w-full rounded-lg border border-black/10 bg-transparent py-2 pl-9 pr-3 text-sm outline-none focus:border-[#00bceb]/60 dark:border-white/10"
            />
          </div>
        </div>

        {error && (
          <div className="mx-3 mt-3 flex items-start gap-2 rounded-md border border-rose-500/20 bg-rose-500/[.05] px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="min-h-[180px] flex-1 overflow-y-auto overscroll-contain p-3">
          {loading ? (
            <div className="flex h-36 items-center justify-center text-xs text-black/45 dark:text-white/45">
              <span className="inline-flex items-center gap-2"><Loader2 size={15} className="animate-spin" />{zh ? '正在搜索设备…' : 'Searching devices…'}</span>
            </div>
          ) : !query.trim() ? (
            <div className="flex h-36 items-center justify-center rounded-lg border border-dashed border-black/10 text-xs text-black/40 dark:border-white/10 dark:text-white/40">
              {zh ? '输入主机名或管理 IP 开始搜索' : 'Enter a hostname or management IP to search'}
            </div>
          ) : rows.length === 0 ? (
            <div className="flex h-36 items-center justify-center rounded-lg border border-dashed border-black/10 text-xs text-black/40 dark:border-white/10 dark:text-white/40">
              {error ? (zh ? '搜索失败，请检查连接后重试' : 'Search failed. Check the connection and retry.') : (zh ? '没有匹配的纳管设备' : 'No managed devices match this search')}
            </div>
          ) : (
            <div className="space-y-1.5">
              {rows.map(device => {
                const selected = device.device_id === selectedDeviceId;
                return (
                  <button
                    key={device.device_id}
                    type="button"
                    disabled={!device.ip_address}
                    onClick={() => onSelect(device)}
                    className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${selected ? 'border-emerald-500/30 bg-emerald-500/[.05]' : 'border-black/7 bg-white/55 hover:border-[#00bceb]/35 hover:bg-[#00bceb]/[.035] dark:border-white/8 dark:bg-white/[.025] dark:hover:bg-white/[.05]'} disabled:cursor-not-allowed disabled:opacity-45`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-black/80 dark:text-white/85">{device.hostname || '—'}</span>
                      <span className="mt-0.5 block font-mono text-[11px] text-black/45 dark:text-white/45">{device.ip_address || (zh ? '未配置管理 IP' : 'No management IP')}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusClass(device.status || '')}`}>{statusLabel(device.status || '', zh)}</span>
                      {selected && <Check size={14} className="text-emerald-600 dark:text-emerald-300" />}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-black/6 px-4 py-2.5 text-[10px] text-black/45 dark:border-white/8 dark:text-white/45">
          <span>{hasMore ? (zh ? '匹配结果较多，请输入更具体的名称或 IP' : 'Too many matches; refine the hostname or IP') : rows.length ? (zh ? `找到 ${rows.length} 台` : `${rows.length} found`) : (zh ? '只搜索已纳管网络设备' : 'Searches managed network devices only')}</span>
          <button type="button" onClick={onClose} className="rounded-md border border-black/10 px-3 py-1.5 text-xs font-medium text-black/60 hover:bg-black/[.04] dark:border-white/10 dark:text-white/60 dark:hover:bg-white/[.06]">
            {zh ? '取消' : 'Cancel'}
          </button>
        </footer>
      </section>
    </div>
  );
};

export default CmdbDevicePicker;
