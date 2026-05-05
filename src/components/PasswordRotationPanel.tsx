import React, { useState, useCallback, useEffect, useMemo } from 'react';
import Pagination from './Pagination';
import { motion, AnimatePresence } from 'motion/react';
import {
  RefreshCw, Shield, AlertTriangle, CheckCircle2, Clock, Loader2, RotateCcw,
  Search, X, ShieldCheck, ShieldAlert, ShieldX, KeyRound, Server, Filter,
  Eye, EyeOff, Copy, Check, ChevronDown, User,
} from 'lucide-react';

interface RotationDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  auth_model: string;
  
  // Normal
  normal_username: string;
  normal_password_last_rotated: string;
  normal_password_expires_at: string;
  normal_password_days_remaining: number | null;
  normal_password_expired: boolean;
  
  // Admin
  admin_username: string;
  admin_password_last_rotated: string;
  admin_password_expires_at: string;
  admin_password_days_remaining: number | null;
  admin_password_expired: boolean;
  
  // Enable
  enable_password_last_rotated: string;
  enable_password_expires_at: string;
  enable_password_days_remaining: number | null;
  enable_password_expired: boolean;
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
    linux: 'Linux', ubuntu: 'Ubuntu', centos: 'CentOS', debian: 'Debian',
    esxi: 'VMware ESXi',
  };
  return map[p] || p || '-';
};

const platformColor = (p: string): string => {
  if (p?.startsWith('cisco')) return 'bg-blue-50 text-blue-600 border-blue-200';
  if (p?.startsWith('huawei')) return 'bg-red-50 text-red-600 border-red-200';
  if (p?.startsWith('h3c')) return 'bg-orange-50 text-orange-600 border-orange-200';
  if (p?.startsWith('arista')) return 'bg-cyan-50 text-cyan-600 border-cyan-200';
  if (p?.startsWith('juniper')) return 'bg-green-50 text-green-600 border-green-200';
  if (['linux', 'ubuntu', 'centos', 'debian'].includes(p)) return 'bg-slate-100 text-slate-700 border-slate-300';
  return 'bg-slate-50 text-slate-600 border-slate-200';
};

const isServer = (p: string): boolean => {
  const platform = (p || '').toLowerCase();
  return platform.includes('linux') || platform.includes('ubuntu') || platform.includes('centos') || platform.includes('server') || platform.includes('debian');
};

type StatusFilter = 'all' | 'healthy' | 'expiring' | 'expired' | 'unconfigured';

export default function PasswordRotationPanel({ language }: PasswordRotationPanelProps) {
  const zh = language === 'zh';
  const [devices, setDevices] = useState<RotationDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [rotating, setRotating] = useState<string | null>(null); // deviceId:role
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [revealKey, setRevealKey] = useState<string | null>(null); // deviceId:role
  const [revealedPwd, setRevealedPwd] = useState<string | null>(null);
  const [revealLoading, setRevealLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
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

  const handleRotate = async (deviceId: string, role: string = 'admin') => {
    const key = `${deviceId}:${role}`;
    setRotating(key);
    try {
      const token = localStorage.getItem('netops_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/${deviceId}/rotate-password?role=${role}`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (!data.success) throw new Error(data.data?.message || 'Rotation failed');
      
      setRevealKey(null); // Clear revealed password after rotation
      setRevealedPwd(null);
      
      // Delay fetch to allow backend async tasks to settle
      setTimeout(fetchStatus, 1500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRotating(null);
    }
  };

  const handleReveal = async (deviceId: string, role: string = 'admin') => {
    const key = `${deviceId}:${role}`;
    if (revealKey === key) { setRevealKey(null); setRevealedPwd(null); return; }
    setRevealLoading(true);
    setRevealKey(key);
    setRevealedPwd(null);
    setCopied(false);
    try {
      const token = localStorage.getItem('netops_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/${deviceId}/reveal-password?role=${role}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (data.success) { setRevealedPwd(data.data.password); }
      else { setError(data.message || (zh ? '获取密码失败' : 'Failed to reveal password')); setRevealKey(null); }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setRevealKey(null);
    } finally {
      setRevealLoading(false);
    }
  };

  const handleCopyPwd = () => {
    if (!revealedPwd) return;
    
    // Modern API
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(revealedPwd)
        .then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        })
        .catch(() => {
          // Fallback to legacy if modern fails
          legacyCopy(revealedPwd);
        });
    } else {
      legacyCopy(revealedPwd);
    }
  };

  const legacyCopy = (text: string) => {
    try {
      const textArea = document.createElement("textarea");
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Fallback copy failed', err);
    }
  };

  /* ── computed stats ── */
  const stats = useMemo(() => {
    let total = 0;
    let expired = 0;
    let healthy = 0;
    let expiring = 0;

    devices.forEach(d => {
      ['normal', 'admin', 'enable'].forEach(role => {
        const days = (d as any)[`${role}_password_days_remaining`];
        const isExp = (d as any)[`${role}_password_expired`];
        
        if (days !== null || role === 'admin') {
          total++;
          if (isExp) expired++;
          else if (days !== null && days <= 14) expiring++;
          else healthy++;
        }
      });
    });
    
    return { total, healthy, expiring, expired };
  }, [devices]);

  /* ── Flat account list computation & filtering ── */
  const accountList = useMemo(() => {
    const allAccounts: any[] = [];
    
    // 1. Flatten all devices into accounts
    devices.forEach(dev => {
      const roles = [
        { key: 'normal', label: zh ? '普通账号' : 'Normal', icon: User, color: 'blue' },
        { key: 'admin', label: zh ? '特权账号' : 'Privileged', icon: ShieldCheck, color: 'orange' },
        { key: 'enable', label: zh ? '提权密码' : 'Enable', icon: KeyRound, color: 'emerald' },
      ];

      roles.forEach(role => {
        const username = (dev as any)[`${role.key}_username`];
        const days = (dev as any)[`${role.key}_password_days_remaining`];
        const expired = (dev as any)[`${role.key}_password_expired`];
        const last = (dev as any)[`${role.key}_password_last_rotated`];
        const expiresAt = (dev as any)[`${role.key}_password_expires_at`];
        
        const platform = (dev.platform || '').toLowerCase();
        const isServer = platform.includes('linux') || platform.includes('ubuntu') || platform.includes('centos') || platform.includes('server') || platform.includes('debian');
        
        // Show if:
        // 1. It's an admin account (always show)
        // 2. It's a server AND we are looking at the 'normal' role (always show for servers)
        // 3. Or it has a username configured
        // 4. Or it has rotation history
        if (role.key === 'admin' || (isServer && role.key === 'normal') || username || days !== null) {
          allAccounts.push({
            ...dev,
            roleKey: role.key,
            roleLabel: role.label,
            roleIcon: role.icon,
            roleColor: role.color,
            // Fallback: If role-specific username is empty, use the main dev.username
            currentUsername: username || dev.username || (role.key === 'admin' ? 'admin' : ''),
            currentDays: days,
            currentExpired: expired,
            currentLastRotated: last,
            currentExpiresAt: expiresAt,
          });
        }
      });
    });

    // 2. Apply Filters
    let list = allAccounts;

    // Search filter
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(acc => 
        (acc.hostname || '').toLowerCase().includes(q) ||
        (acc.ip_address || '').toLowerCase().includes(q) ||
        (acc.currentUsername || '').toLowerCase().includes(q)
      );
    }

    // Status filter
    if (statusFilter !== 'all') {
      list = list.filter(acc => {
        if (statusFilter === 'expired') return acc.currentExpired;
        if (statusFilter === 'expiring') return acc.currentDays !== null && acc.currentDays <= 14 && acc.currentDays >= 0;
        if (statusFilter === 'healthy') return !acc.currentExpired && (acc.currentDays === null || acc.currentDays > 14);
        return true;
      });
    }

    return list;
  }, [devices, search, statusFilter, zh]);

  const paginatedAccounts = useMemo(() => {
    const start = (page - 1) * pageSize;
    return accountList.slice(start, start + pageSize);
  }, [accountList, page, pageSize]);

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
            </motion.button>
          );
        })}
      </div>

      {/* ═══ Stats Cards (Compact) ═══ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        {statCards.map((c, i) => {
          const isActive = statusFilter === c.id;
          return (
            <motion.button
              key={c.id}
              whileHover={{ y: -2 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => setStatusFilter(isActive ? 'all' : c.id)}
              className={`relative overflow-hidden p-3 rounded-xl border transition-all text-left ${
                isActive 
                  ? 'bg-slate-900 border-slate-900 shadow-lg ring-2 ring-slate-900/10' 
                  : 'bg-white border-black/[0.04] hover:border-black/[0.1] shadow-sm'
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className={`text-[10px] font-bold uppercase tracking-wider mb-0.5 ${isActive ? 'text-white/40' : 'text-black/30'}`}>{c.title}</p>
                  <p className={`text-xl font-black ${isActive ? 'text-white' : 'text-slate-800'}`}>{c.value}</p>
                </div>
                <div className={`p-2 rounded-lg ${isActive ? 'bg-white/10 text-white' : 'bg-black/[0.02] text-black/20'}`}>
                  <c.Icon size={16} />
                </div>
              </div>
            </motion.button>
          );
        })}
      </div>

      {/* ═══ Pro Toolbar ═══ */}
      <div className="flex items-center justify-between gap-3 mb-3 bg-white p-2 rounded-xl border border-black/[0.04] shadow-sm">
        <div className="flex items-center gap-2">
          <div className="h-7 px-2 rounded-lg bg-cyan-500 text-white flex items-center gap-1.5 shadow-sm shadow-cyan-500/20">
            <Shield size={12} />
            <span className="text-[10px] font-black uppercase tracking-tighter">{zh ? '凭据中心' : 'VAULT'}</span>
          </div>
          <div className="h-4 w-[1px] bg-black/5 mx-1" />
          <div className="flex items-center gap-3">
             <div className="relative">
                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/20" />
                <input
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={zh ? '快速搜索设备或账号...' : 'Quick search...'}
                  className="w-48 pl-8 pr-3 py-1.5 rounded-lg bg-black/[0.02] border-none text-[11px] text-black/70 placeholder:text-black/20 focus:ring-1 focus:ring-cyan-500/20"
                />
             </div>
          </div>
        </div>

        <button
          onClick={fetchStatus}
          disabled={loading}
          className="h-7 px-2.5 rounded-lg bg-black/[0.02] border border-black/[0.04] text-black/40 hover:bg-black/[0.05] hover:text-cyan-600 transition-all"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* ═══ High-Density Pro Table ═══ */}
      <div className="bg-white rounded-xl border border-black/[0.06] shadow-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse table-fixed">
            <thead>
              <tr className="bg-slate-50 border-b border-black/[0.05]">
                <th className="w-[220px] px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest border-r border-black/[0.03]">{zh ? '设备资产' : 'DEVICE ASSET'}</th>
                <th className="px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest border-r border-black/[0.03]">{zh ? '普通账号 (Normal)' : 'NORMAL IDENTITY'}</th>
                <th className="px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest border-r border-black/[0.03]">{zh ? '特权账号 (Admin)' : 'PRIVILEGED IDENTITY'}</th>
                <th className="px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest">{zh ? '提权凭据 (Enable)' : 'ENABLE SECRET'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.03]">
              {loading && !accountList.length ? (
                <tr><td colSpan={4} className="py-20 text-center"><Loader2 className="inline animate-spin text-cyan-500" size={24} /></td></tr>
              ) : accountList.length === 0 ? (
                <tr><td colSpan={4} className="py-20 text-center text-[11px] text-black/20 font-medium">{zh ? '未检索到凭据数据' : 'No data records found'}</td></tr>
              ) : (
                (() => {
                  const deviceGroups: Record<string, any[]> = {};
                  accountList.forEach(acc => {
                    if (!deviceGroups[acc.id]) deviceGroups[acc.id] = [];
                    deviceGroups[acc.id].push(acc);
                  });

                  const groupIds = Object.keys(deviceGroups);
                  const paginatedGroupIds = groupIds.slice((page - 1) * pageSize, page * pageSize);

                  return paginatedGroupIds.map((devId) => {
                    const accounts = deviceGroups[devId];
                    const first = accounts[0];
                    
                    // Map accounts to specific columns
                    const roles = {
                      normal: accounts.find(a => a.roleKey === 'normal'),
                      admin: accounts.find(a => a.roleKey === 'admin'),
                      enable: accounts.find(a => a.roleKey === 'enable')
                    };

                    const isDevServer = isServer(first.platform || '');

                    return (
                      <tr key={devId} className="group hover:bg-slate-50/50 transition-colors">
                        {/* Device Info */}
                        <td className="px-4 py-2 border-r border-black/[0.02]">
                          <div className="flex items-center gap-2.5">
                            <div className="h-8 w-8 rounded-lg bg-white border border-black/5 shadow-sm flex items-center justify-center text-slate-300 group-hover:text-cyan-500 transition-colors">
                              <Server size={14} />
                            </div>
                            <div className="min-w-0">
                              <div className="text-[12px] font-bold text-slate-700 truncate leading-tight tracking-tight">{first.hostname}</div>
                              <div className="flex items-center gap-1.5 mt-0.5">
                                <span className="text-[10px] font-mono text-slate-400">{first.ip_address}</span>
                                <span className={`px-1 rounded text-[8px] font-black uppercase ${platformColor(first.platform)}`}>
                                  {platformLabel(first.platform)}
                                </span>
                              </div>
                            </div>
                          </div>
                        </td>

                        {/* Account Columns */}
                        {['normal', 'admin', 'enable'].map((role) => {
                          const acc = roles[role as keyof typeof roles];
                          
                          // Optimization: Hide Enable column for servers
                          if (role === 'enable' && isDevServer) {
                            return (
                              <td key={role} className="px-4 py-2 border-r border-black/[0.02] bg-black/[0.01]">
                                <div className="flex items-center justify-center gap-1.5 opacity-20 grayscale">
                                  <Shield size={10} />
                                  <span className="text-[9px] font-black tracking-widest">{zh ? '不适用' : 'N/A'}</span>
                                </div>
                              </td>
                            );
                          }

                          if (!acc) return <td key={role} className="px-4 py-2 border-r border-black/[0.02] text-center"><span className="text-[10px] text-black/5 font-black">N/A</span></td>;

                          const key = `${acc.id}:${acc.roleKey}`;
                          const isRevealed = revealKey === key;
                          const isRotating = rotating === key;

                          return (
                            <td key={role} className={`px-4 py-2 border-r border-black/[0.02] ${acc.currentExpired ? 'bg-red-50/20' : ''}`}>
                              <div className="flex items-center justify-between gap-2">
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-1.5">
                                    <span className="text-[11px] font-mono font-bold text-slate-600 truncate">{acc.currentUsername || '—'}</span>
                                    {acc.currentExpiresAt && (
                                      <span className={`text-[9px] font-black ${acc.currentExpired ? 'text-red-500' : 'text-emerald-500/60'}`}>
                                        {acc.currentExpired ? 'EXP' : `${acc.currentDays}d`}
                                      </span>
                                    )}
                                  </div>
                                  <div className="flex items-center justify-between text-[8px] font-bold uppercase tracking-tighter mt-0.5">
                                    <span className="text-slate-300">
                                      {acc.currentLastRotated 
                                        ? `ROT: ${new Date(acc.currentLastRotated).toLocaleDateString()}` 
                                        : (zh ? '未曾轮换' : 'NOT ROTATED')}
                                    </span>
                                    <span className={acc.currentExpired ? 'text-red-400' : 'text-slate-300'}>
                                      {acc.currentExpiresAt 
                                        ? `EXP: ${new Date(acc.currentExpiresAt).toLocaleDateString()}` 
                                        : (zh ? '到期时间待定' : 'EXP: PENDING')}
                                    </span>
                                  </div>
                                </div>

                                <div className="flex items-center gap-1 shrink-0">
                                  <button
                                    onClick={() => handleReveal(acc.id, acc.roleKey)}
                                    className={`h-6 w-6 rounded-md flex items-center justify-center transition-all ${isRevealed ? 'bg-cyan-500 text-white shadow-sm' : 'bg-black/[0.03] text-black/20 hover:text-black/60 hover:bg-black/[0.06]'}`}
                                  >
                                    {revealLoading && revealKey === key ? <Loader2 size={10} className="animate-spin" /> : (isRevealed ? <EyeOff size={10} /> : <Eye size={10} />)}
                                  </button>
                                  <button
                                    onClick={() => handleRotate(acc.id, acc.roleKey)}
                                    disabled={isRotating}
                                    className={`h-6 px-1.5 rounded-md border text-[9px] font-bold transition-all ${isRotating ? 'bg-black/5 text-black/10' : 'bg-white border-cyan-500/40 text-cyan-600 hover:bg-cyan-500 hover:text-white active:scale-95'}`}
                                  >
                                    {isRotating ? <Loader2 size={10} className="animate-spin" /> : <RotateCcw size={10} />}
                                  </button>
                                </div>
                              </div>
                              
                              {isRevealed && revealedPwd && (
                                <motion.div 
                                  initial={{ opacity: 0, scale: 0.9 }}
                                  animate={{ opacity: 1, scale: 1 }}
                                  className="absolute mt-1 z-10 flex items-center gap-2 bg-slate-900 px-2 py-1 rounded-md text-cyan-400 font-mono text-[10px] shadow-2xl border border-white/10"
                                >
                                  {revealedPwd}
                                  <button onClick={handleCopyPwd} className="hover:text-white transition-colors">
                                    {copied ? <Check size={10} /> : <Copy size={10} />}
                                  </button>
                                </motion.div>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  });
                })()
              )}
            </tbody>
          </table>
        </div>

        {/* Footer Info & Pagination */}
        <div className="px-4 py-2.5 bg-slate-50 border-t border-black/[0.05] flex items-center justify-between">
          <div className="flex items-center gap-4">
             <div className="flex items-center gap-1.5 text-[9px] font-bold text-slate-400 uppercase">
                <span className="w-2 h-2 rounded-full bg-emerald-500" /> {zh ? '监控正常' : 'Healthy'}
             </div>
             <div className="flex items-center gap-1.5 text-[9px] font-bold text-slate-400 uppercase">
                <span className="w-2 h-2 rounded-full bg-red-500" /> {zh ? '凭据过期' : 'Expired'}
             </div>
          </div>
          
          <Pagination
            currentPage={page}
            totalItems={Object.keys(accountList.reduce((acc, curr) => ({...acc, [curr.id]: 1}), {})).length}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(v) => { setPage(1); setPageSize(v); }}
            onPageChange={setPage}
            language={language}
          />
        </div>
      </div>
    </div>
  );
}
