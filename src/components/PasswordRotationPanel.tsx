import { useState, useCallback, useEffect, useMemo } from 'react';
import Pagination from './Pagination';
import { motion, AnimatePresence } from 'motion/react';
import {
  RefreshCw, Shield, AlertTriangle, CheckCircle2, Clock, Loader2, RotateCcw,
  Search, X, ShieldCheck, ShieldAlert, ShieldX, KeyRound, Server, Filter,
  Eye, EyeOff, Copy, Check,
} from 'lucide-react';

interface RotationDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  password_last_rotated: string;
  password_expires_at: string;
  days_remaining: number | null;
  expired: boolean;
}

interface PasswordRotationPanelProps {
  language: string;
}

const API_BASE = import.meta.env.VITE_API_BASE || '';

/* ── platform display helper ── */
const platformLabel = (p: string): string => {
  const map: Record<string, string> = {
    cisco_ios: 'Cisco IOS', cisco_nxos: 'Cisco NX-OS', cisco_xe: 'Cisco IOS-XE',
    huawei_vrp: 'Huawei VRP', h3c_comware: 'H3C Comware',
    arista_eos: 'Arista EOS', juniper_junos: 'Juniper JunOS',
  };
  return map[p] || p || '-';
};

const platformColor = (p: string): string => {
  if (p?.startsWith('cisco')) return 'bg-blue-50 text-blue-600 border-blue-200';
  if (p?.startsWith('huawei')) return 'bg-red-50 text-red-600 border-red-200';
  if (p?.startsWith('h3c')) return 'bg-orange-50 text-orange-600 border-orange-200';
  if (p?.startsWith('arista')) return 'bg-cyan-50 text-cyan-600 border-cyan-200';
  if (p?.startsWith('juniper')) return 'bg-green-50 text-green-600 border-green-200';
  return 'bg-slate-50 text-slate-600 border-slate-200';
};

type StatusFilter = 'all' | 'healthy' | 'expiring' | 'expired' | 'unconfigured';

export default function PasswordRotationPanel({ language }: PasswordRotationPanelProps) {
  const zh = language === 'zh';
  const [devices, setDevices] = useState<RotationDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [rotating, setRotating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [revealId, setRevealId] = useState<string | null>(null);
  const [revealedPwd, setRevealedPwd] = useState<string | null>(null);
  const [revealLoading, setRevealLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('netops_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/rotation/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (data.success) {
        setDevices(data.data || []);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);
  useEffect(() => { setPage(1); }, [search, statusFilter]);

  const handleRotate = async (deviceId: string) => {
    setRotating(deviceId);
    try {
      const token = localStorage.getItem('netops_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/${deviceId}/rotate-password`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (!data.success) throw new Error(data.data?.message || 'Rotation failed');
      await fetchStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRotating(null);
    }
  };

  const handleReveal = async (deviceId: string) => {
    if (revealId === deviceId) { setRevealId(null); setRevealedPwd(null); return; }
    setRevealLoading(true);
    setRevealId(deviceId);
    setRevealedPwd(null);
    setCopied(false);
    try {
      const token = localStorage.getItem('netops_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/${deviceId}/reveal-password`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (data.success) { setRevealedPwd(data.data.password); }
      else { setError(data.message || (zh ? '获取密码失败' : 'Failed to reveal password')); setRevealId(null); }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setRevealId(null);
    } finally {
      setRevealLoading(false);
    }
  };

  const handleCopyPwd = () => {
    if (!revealedPwd) return;
    navigator.clipboard.writeText(revealedPwd).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  /* ── computed stats ── */
  const stats = useMemo(() => {
    const total = devices.length;
    const expired = devices.filter(d => d.expired).length;
    const expiring = devices.filter(d => !d.expired && d.days_remaining !== null && d.days_remaining <= 14).length;
    const unconfigured = devices.filter(d => !d.password_expires_at).length;
    const healthy = total - expired - expiring - unconfigured;
    return { total, healthy, expiring, expired, unconfigured };
  }, [devices]);

  /* ── filtering ── */
  const filtered = useMemo(() => {
    let list = devices;
    if (statusFilter !== 'all') {
      list = list.filter(d => {
        if (statusFilter === 'expired') return d.expired;
        if (statusFilter === 'expiring') return !d.expired && d.days_remaining !== null && d.days_remaining <= 14;
        if (statusFilter === 'unconfigured') return !d.password_expires_at;
        return !d.expired && (d.days_remaining === null || d.days_remaining > 14) && !!d.password_expires_at;
      });
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(d =>
        (d.hostname || '').toLowerCase().includes(q) ||
        (d.ip_address || '').toLowerCase().includes(q) ||
        (d.platform || '').toLowerCase().includes(q)
      );
    }
    return list;
  }, [devices, statusFilter, search]);

  const paginatedFiltered = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, page, pageSize]);

  /* ── status badge ── */
  const statusBadge = (dev: RotationDevice) => {
    if (!dev.password_expires_at) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-500 border border-slate-200">
          <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
          {zh ? '未配置' : 'Not Set'}
        </span>
      );
    }
    if (dev.expired) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-50 text-red-600 border border-red-200">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
          {zh ? '已过期' : 'Expired'}
        </span>
      );
    }
    if (dev.days_remaining !== null && dev.days_remaining <= 14) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-600 border border-amber-200">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          {zh ? '即将过期' : 'Expiring'}
        </span>
      );
    }
    return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-600 border border-emerald-200">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        {zh ? '正常' : 'OK'}
      </span>
    );
  };

  /* ── days remaining display ── */
  const daysCell = (dev: RotationDevice) => {
    if (dev.days_remaining === null) return <span className="text-black/25">—</span>;
    const d = dev.days_remaining;
    const cls = d < 0 ? 'text-red-600 font-bold' : d <= 7 ? 'text-red-500' : d <= 14 ? 'text-amber-500' : 'text-black/50';
    return (
      <span className={cls}>
        {d < 0 ? `${zh ? '已过期' : 'overdue'} ${Math.abs(d)}${zh ? '天' : 'd'}` : `${d}${zh ? '天' : 'd'}`}
      </span>
    );
  };

  /* ══════════ Stat card data ══════════ */
  const statCards = [
    {
      key: 'total', value: stats.total,
      label: zh ? '凭据总数' : 'Total', sub: zh ? '已纳管' : 'MANAGED',
      Icon: KeyRound, filter: 'all' as StatusFilter,
      gradient: 'from-slate-700 to-slate-800', iconBg: 'bg-white/[0.06]',
      iconCls: 'text-slate-300', valCls: 'text-white', labelCls: 'text-white/50', subCls: 'bg-white/10 text-white/60',
    },
    {
      key: 'healthy', value: stats.healthy,
      label: zh ? '状态正常' : 'Healthy', sub: zh ? '安全' : 'SECURE',
      Icon: ShieldCheck, filter: 'healthy' as StatusFilter,
      gradient: 'from-emerald-600 to-emerald-700', iconBg: 'bg-white/[0.08]',
      iconCls: 'text-white/70', valCls: 'text-white', labelCls: 'text-white/60', subCls: 'bg-white/15 text-white/70',
    },
    {
      key: 'expiring', value: stats.expiring,
      label: zh ? '即将过期' : 'Expiring', sub: '≤14D',
      Icon: ShieldAlert, filter: 'expiring' as StatusFilter,
      gradient: 'from-amber-600 to-amber-700', iconBg: 'bg-white/[0.08]',
      iconCls: 'text-white/70', valCls: 'text-white', labelCls: 'text-white/60', subCls: 'bg-white/15 text-white/70',
      pulse: stats.expiring > 0,
    },
    {
      key: 'expired', value: stats.expired,
      label: zh ? '已过期' : 'Expired', sub: zh ? '紧急' : 'URGENT',
      Icon: ShieldX, filter: 'expired' as StatusFilter,
      gradient: 'from-red-600 to-red-700', iconBg: 'bg-white/[0.08]',
      iconCls: 'text-white/70', valCls: 'text-white', labelCls: 'text-white/60', subCls: 'bg-white/15 text-white/80',
      pulse: stats.expired > 0,
    },
  ];

  return (
    <div className="space-y-4">
      {/* ═══ Stat Cards ═══ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statCards.map(c => {
          const isActive = statusFilter === c.filter;
          return (
            <motion.button
              key={c.key}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => setStatusFilter(isActive && c.filter !== 'all' ? 'all' : c.filter)}
              className={`group relative rounded-xl overflow-hidden shadow-sm transition-all
                bg-gradient-to-br ${c.gradient}
                ${isActive ? 'ring-2 ring-white/20 shadow-lg' : 'hover:shadow-md'}`}
            >
              <div className="px-4 py-3.5 flex items-center justify-between relative z-10">
                <div className="text-left">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className={`text-[8px] font-bold uppercase tracking-[0.15em] px-1.5 py-0.5 rounded ${c.subCls}`}>{c.sub}</span>
                    <span className={`text-[10px] font-medium ${c.labelCls}`}>{c.label}</span>
                  </div>
                  <p className={`text-3xl font-black tabular-nums leading-none ${c.valCls}`}>{c.value}</p>
                </div>
                <div className={`h-10 w-10 rounded-xl ${c.iconBg} flex items-center justify-center backdrop-blur-sm`}>
                  <c.Icon size={20} className={`${c.iconCls} ${c.pulse ? 'animate-pulse' : ''}`} />
                </div>
              </div>
              {isActive && <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20" />}
            </motion.button>
          );
        })}
      </div>

      {/* ═══ Main Table Card ═══ */}
      <div className="bg-white rounded-xl border border-black/5 shadow-sm overflow-hidden">
        {/* Header / Toolbar */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-black/5 bg-black/[0.008]">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-cyan-50 border border-cyan-200 flex items-center justify-center">
              <Shield size={16} className="text-cyan-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-black/80">{zh ? '凭据轮换明细' : 'Credential Rotation Details'}</h3>
              <p className="text-[10px] text-black/30 mt-0.5">
                {zh ? `共 ${filtered.length} 条记录` : `${filtered.length} record${filtered.length !== 1 ? 's' : ''}`}
                {statusFilter !== 'all' && <span className="ml-1 text-cyan-600/60">• {zh ? '已筛选' : 'filtered'}</span>}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Search */}
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/25 pointer-events-none" />
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder={zh ? '搜索主机名 / IP...' : 'Search hostname / IP...'}
                className="w-48 pl-7 pr-7 py-1.5 rounded-lg bg-black/[0.03] border border-black/[0.06]
                  text-[11px] text-black/70 placeholder:text-black/25
                  focus:outline-none focus:border-cyan-500/30 focus:ring-1 focus:ring-cyan-500/15 transition-colors"
              />
              {search && (
                <button onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-black/25 hover:text-black/50">
                  <X size={10} />
                </button>
              )}
            </div>

            {/* Status filter */}
            {statusFilter !== 'all' && (
              <button
                onClick={() => setStatusFilter('all')}
                className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-[10px] font-medium
                  bg-cyan-500/10 border border-cyan-500/15 text-cyan-400 hover:bg-cyan-500/20 transition-colors"
              >
                <Filter size={10} />
                {zh ? '清除筛选' : 'Clear'}
                <X size={9} />
              </button>
            )}

            {/* Refresh */}
            <button
              onClick={fetchStatus}
              disabled={loading}
              className="p-2 rounded-lg border border-black/[0.06] bg-black/[0.02] text-black/40
                hover:text-black/70 hover:bg-black/[0.04] hover:border-black/[0.1] transition-all disabled:opacity-40"
              title={zh ? '刷新' : 'Refresh'}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Error Banner */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="mx-4 mt-3 flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                <AlertTriangle size={14} className="text-red-500 shrink-0" />
                <span className="text-xs text-red-600 flex-1">{error}</span>
                <button onClick={() => setError(null)} className="text-red-400/50 hover:text-red-500"><X size={12} /></button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-black/35 border-b border-black/[0.06]">
                <th className="px-5 py-2.5 font-semibold">{zh ? '设备' : 'Device'}</th>
                <th className="px-3 py-2.5 font-semibold">{zh ? '平台' : 'Platform'}</th>
                <th className="px-3 py-2.5 font-semibold">IP</th>
                <th className="px-3 py-2.5 font-semibold">{zh ? '上次轮换' : 'Last Rotated'}</th>
                <th className="px-3 py-2.5 font-semibold">{zh ? '到期时间' : 'Expires'}</th>
                <th className="px-3 py-2.5 font-semibold">{zh ? '剩余' : 'Remaining'}</th>
                <th className="px-3 py-2.5 font-semibold">{zh ? '状态' : 'Status'}</th>
                <th className="px-3 py-2.5 font-semibold text-right">{zh ? '操作' : 'Action'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.04]">
              {/* Loading */}
              {loading && !devices.length && (
                <tr>
                  <td colSpan={8} className="px-6 py-16 text-center">
                    <div className="inline-block w-6 h-6 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin mb-3" />
                    <p className="text-sm text-black/30">{zh ? '正在加载凭据状态…' : 'Loading credential status...'}</p>
                  </td>
                </tr>
              )}

              {/* Empty */}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-6 py-16 text-center">
                    <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-black/[0.03] border border-black/[0.06] mb-4">
                      <KeyRound size={24} className="text-black/15" />
                    </div>
                    <p className="text-sm text-black/30 mb-1">
                      {search || statusFilter !== 'all'
                        ? (zh ? '没有匹配的设备凭据' : 'No credentials match current filters')
                        : (zh ? '暂无纳管设备' : 'No managed devices yet')}
                    </p>
                    <p className="text-[11px] text-black/20">
                      {search || statusFilter !== 'all'
                        ? (zh ? '尝试调整搜索或筛选条件' : 'Try adjusting search or filter criteria')
                        : (zh ? '设备投产后将自动纳入凭据管理' : 'Devices will appear here after going to production')}
                    </p>
                  </td>
                </tr>
              )}

              {/* Data rows */}
              {!loading && paginatedFiltered.map((dev, i) => (
                <motion.tr
                  key={dev.id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.02 }}
                  className="group hover:bg-black/[0.015] transition-colors"
                >
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="h-7 w-7 rounded-lg bg-black/[0.03] border border-black/[0.06] flex items-center justify-center shrink-0">
                        <Server size={13} className="text-black/30" />
                      </div>
                      <span className="text-[13px] font-medium text-black/80">{dev.hostname || '—'}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-medium border ${platformColor(dev.platform)}`}>
                      {platformLabel(dev.platform)}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="text-xs font-mono text-black/45">{dev.ip_address}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="text-xs text-black/40">
                      {dev.password_last_rotated ? new Date(dev.password_last_rotated).toLocaleDateString() : '—'}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="text-xs text-black/40">
                      {dev.password_expires_at ? new Date(dev.password_expires_at).toLocaleDateString() : '—'}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-xs tabular-nums">
                    {daysCell(dev)}
                  </td>
                  <td className="px-3 py-3">
                    {statusBadge(dev)}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      {/* Reveal password */}
                      <button
                        onClick={() => handleReveal(dev.id)}
                        disabled={revealLoading && revealId === dev.id}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium
                          bg-amber-50 border border-amber-200 text-amber-600
                          hover:bg-amber-100 hover:border-amber-300
                          active:scale-[0.97] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                        title={zh ? '查看密码' : 'Reveal password'}
                      >
                        {revealLoading && revealId === dev.id
                          ? <Loader2 size={12} className="animate-spin" />
                          : revealId === dev.id ? <EyeOff size={12} /> : <Eye size={12} />}
                      </button>
                      {/* Rotate */}
                      <button
                        onClick={() => handleRotate(dev.id)}
                        disabled={rotating === dev.id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium
                          bg-cyan-50 border border-cyan-200 text-cyan-600
                          hover:bg-cyan-100 hover:border-cyan-300
                          active:scale-[0.97] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {rotating === dev.id
                          ? <Loader2 size={12} className="animate-spin" />
                          : <RotateCcw size={12} />}
                        {zh ? '立即轮换' : 'Rotate Now'}
                      </button>
                    </div>
                    {/* Revealed password inline */}
                    <AnimatePresence>
                      {revealId === dev.id && revealedPwd && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                          className="mt-1.5 flex items-center gap-1.5 justify-end"
                        >
                          <code className="px-2 py-1 rounded bg-slate-100 border border-black/10 text-[11px] font-mono text-amber-700 select-all">
                            {revealedPwd}
                          </code>
                          <button
                            onClick={handleCopyPwd}
                            className="p-1 rounded hover:bg-black/5 transition-colors"
                            title={zh ? '复制' : 'Copy'}
                          >
                            {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} className="text-black/40" />}
                          </button>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {filtered.length > 0 && (
          <div>
            <Pagination
              currentPage={page}
              totalItems={filtered.length}
              itemsPerPage={pageSize}
              onItemsPerPageChange={(v) => { setPage(1); setPageSize(v); }}
              onPageChange={setPage}
              language={language}
            />
          </div>
        )}
      </div>
    </div>
  );
}
