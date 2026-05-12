import React, { useState, useCallback, useEffect } from 'react';
import { Search, MapPin, ArrowRight, Loader2, Server, Monitor, Network, AlertCircle, ChevronDown, ChevronUp, Cable, Clock, RotateCcw, Activity, Wifi, Globe, Zap, CheckCircle2, XCircle, Minus, Database, RefreshCw, Filter, Download } from 'lucide-react';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import * as XLSX from 'xlsx';

interface IPLocatorPageProps {
  language: string;
  t: (key: string) => string;
}

interface LocationEntry {
  switch_id: string;
  switch_name: string;
  port: string;
  vlan: string;
  type: string;
  is_uplink: boolean;
  uplink_neighbor?: string;
  uplink_port?: string;
  note?: string;
}

interface LocateResult {
  target_ip: string;
  found: boolean;
  mac: string | null;
  mac_display: string | null;
  arp_source: { device_id: string; device: string; interface: string } | null;
  locations: LocationEntry[];
  searched_devices: { arp: string[]; mac: string[]; lldp: string[] };
  cache?: {
    enabled: boolean;
    arp_cache_hit: boolean;
    ttl_seconds: number;
    force_refresh: boolean;
    cached_at: string | null;
  };
  timestamp: string;
  errors: string[];
}

// ── Connectivity Probe Types ──
interface TcpResult { success: boolean; port: number; latency_ms: number; detail: string }
interface PingResult { success: boolean; loss_percent: number; rtt: { min?: number; avg?: number; max?: number }; output: string; device?: string }
interface TracerouteHop { hop: number; ip: string; rtt_ms: number[]; timeout: boolean }
interface TracerouteResult { success: boolean; hops: TracerouteHop[]; output: string; device?: string }
interface ProbeResult {
  target: string;
  mode: string;
  source_device: string | null;
  timestamp: string;
  tests: {
    ping?: PingResult;
    tcp?: TcpResult[];
    traceroute?: TracerouteResult;
    error?: string;
  };
}

type TabMode = 'locate' | 'probe' | 'arp-table' | 'mac-changes';

interface ArpEntry {
  ip: string;
  mac: string;
  mac_raw: string;
  interface: string;
  device: string;
  device_id: number | null;
  cached_at: string;
  ttl_remaining: number;
  vendor: string;
}

interface MacChangeEntry {
  id: number;
  ip: string;
  old_mac: string;
  new_mac: string;
  old_vendor: string;
  new_vendor: string;
  old_device: string;
  new_device: string;
  detected_at: string;
}

interface MacChangesData {
  total: number;
  entries: MacChangeEntry[];
  timestamp: string;
}

interface ArpTableData {
  total: number;
  ttl_seconds: number;
  sweep_interval_seconds: number;
  entries: ArpEntry[];
  timestamp: string;
}

function formatRelativeTime(isoStr: string, zhLang: boolean): string {
  try {
    const then = new Date(isoStr);
    if (isNaN(then.getTime())) return isoStr;
    const diffSec = Math.max(0, Math.round((Date.now() - then.getTime()) / 1000));
    if (diffSec < 5) return zhLang ? '刚刚' : 'just now';
    if (diffSec < 60) return zhLang ? `${diffSec} 秒前` : `${diffSec}s ago`;
    const m = Math.floor(diffSec / 60);
    if (m < 60) return zhLang ? `${m} 分钟前` : `${m}m ago`;
    const h = Math.floor(m / 60);
    return zhLang ? `${h} 小时前` : `${h}h ago`;
  } catch {
    return isoStr;
  }
}

const IPLocatorPage: React.FC<IPLocatorPageProps> = ({ language }) => {
  const zh = language === 'zh';
  const [activeTab, setActiveTab] = useState<TabMode>('locate');
  const [ip, setIp] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LocateResult | null>(null);
  const [error, setError] = useState('');
  const [showDetails, setShowDetails] = useState(false);
  const [history, setHistory] = useState<{ ip: string; found: boolean; mac: string; switch_name: string; port: string; time: string }[]>([]);

  // ── Probe state ──
  const [probeIp, setProbeIp] = useState('');
  const [probeLoading, setProbeLoading] = useState(false);
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null);
  const [probeError, setProbeError] = useState('');
  const [probePorts, setProbePorts] = useState('22, 80, 443');
  const [probeTests, setProbeTests] = useState<Set<string>>(new Set(['ping', 'tcp', 'traceroute']));
  const [devices, setDevices] = useState<{ id: number; hostname: string; ip_address: string }[]>([]);
  const [sourceDeviceId, setSourceDeviceId] = useState<number | null>(null);

  // ── ARP Table state ──
  const [arpTable, setArpTable] = useState<ArpTableData | null>(null);
  const [arpLoading, setArpLoading] = useState(false);
  const [arpError, setArpError] = useState('');
  const [arpFilter, setArpFilter] = useState('');
  const [arpSweeping, setArpSweeping] = useState(false);
  const [arpPage, setArpPage] = useState(1);
  const [arpPageSize, setArpPageSize] = useState(20);

  // ── MAC Changes state ──
  const [macChanges, setMacChanges] = useState<MacChangesData | null>(null);
  const [macChangesLoading, setMacChangesLoading] = useState(false);
  const [macChangesError, setMacChangesError] = useState('');
  const [macFilter, setMacFilter] = useState('');
  const [macPage, setMacPage] = useState(1);
  const [macPageSize, setMacPageSize] = useState(20);

  const token = localStorage.getItem('netops_token') || '';

  // 加载设备列表用于设备侧探测 (使用 mode=light 和 page_size=500 防止加载过慢)
  useEffect(() => {
    fetch('/api/devices?mode=light&page_size=500', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : { items: [] })
      .then(data => {
        const list = Array.isArray(data) ? data : data?.items || data?.data || [];
        setDevices(list.filter((d: any) => d.status === 'online' && d.username));
      })
      .catch(() => {});
  }, [token]);

  // 切换到 ARP 表 tab 时自动加载
  const fetchArpTable = useCallback(async () => {
    setArpLoading(true);
    setArpError('');
    try {
      const resp = await fetch('/api/ip-locator/arp-table', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: ArpTableData = await resp.json();
      setArpTable(data);
    } catch (e: any) {
      setArpError(e.message || 'Failed to load ARP table');
    } finally {
      setArpLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (activeTab === 'arp-table' && !arpTable && !arpLoading) {
      fetchArpTable();
    }
  }, [activeTab, arpTable, arpLoading, fetchArpTable]);

  const triggerArpSweep = useCallback(async () => {
    setArpSweeping(true);
    try {
      const resp = await fetch('/api/ip-locator/arp-sweep', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      if (data.data) setArpTable(data.data);
    } catch {
      await fetchArpTable();
    } finally {
      setArpSweeping(false);
    }
  }, [token, fetchArpTable]);

  // ── MAC Changes fetch ──
  const fetchMacChanges = useCallback(async () => {
    setMacChangesLoading(true);
    setMacChangesError('');
    try {
      const resp = await fetch('/api/ip-locator/mac-changes?limit=1000', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: MacChangesData = await resp.json();
      setMacChanges(data);
      setMacPage(1);
    } catch (e: any) {
      setMacChangesError(e.message || 'Failed to load MAC changes');
    } finally {
      setMacChangesLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (activeTab === 'mac-changes' && !macChanges && !macChangesLoading) {
      fetchMacChanges();
    }
  }, [activeTab, macChanges, macChangesLoading, fetchMacChanges]);

  const doLocate = useCallback(async (targetIp?: string, forceRefresh: boolean = false) => {
    const trimmed = (targetIp ?? ip).trim();
    if (!trimmed) return;
    setIp(trimmed);
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const resp = await fetch('/api/ip-locator/locate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ ip: trimmed, force_refresh: forceRefresh }),
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      const data: LocateResult = await resp.json();
      setResult(data);

      const primary = data.locations?.find(l => !l.is_uplink) || data.locations?.[0];
      setHistory(prev => [{
        ip: trimmed,
        found: data.found,
        mac: data.mac_display || '-',
        switch_name: primary?.switch_name || '-',
        port: primary?.port || '-',
        time: new Date().toLocaleTimeString(),
      }, ...prev.filter(h => h.ip !== trimmed)].slice(0, 20));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [ip, token]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !loading) doLocate();
  };

  // ── Probe function ──
  const doProbe = useCallback(async () => {
    const trimmed = probeIp.trim();
    if (!trimmed) return;
    setProbeLoading(true);
    setProbeError('');
    setProbeResult(null);

    const ports = probePorts
      .split(/[,\s]+/)
      .map(s => parseInt(s, 10))
      .filter(n => n >= 1 && n <= 65535);

    try {
      const resp = await fetch('/api/ip-locator/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          target: trimmed,
          tests: Array.from(probeTests),
          tcp_ports: ports.length ? ports : [22, 80, 443],
          source_device_id: sourceDeviceId,
          ping_count: 4,
        }),
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      setProbeResult(await resp.json());
    } catch (e: unknown) {
      setProbeError(e instanceof Error ? e.message : String(e));
    } finally {
      setProbeLoading(false);
    }
  }, [probeIp, probeTests, probePorts, sourceDeviceId, token]);

  const handleProbeKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !probeLoading) doProbe();
  };

  const toggleTest = (t: string) => {
    setProbeTests(prev => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  const accessLocations = result?.locations?.filter(l => !l.is_uplink) || [];
  const uplinkLocations = result?.locations?.filter(l => l.is_uplink) || [];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={MapPin}
        title={zh ? 'IP 工具箱' : 'IP Toolbox'}
        subtitle={zh ? 'IP 地址定位 · 连通性探测 · 全链路诊断' : 'IP Locate · Connectivity Probe · Full-path Diagnostics'}
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-5">
      {/* ── Tab Bar ── */}
      <div className="flex gap-1 bg-black/[0.03] dark:bg-white/[0.04] rounded-xl p-1 w-fit">
        <button
          onClick={() => setActiveTab('locate')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${activeTab === 'locate' ? 'bg-white dark:bg-white/[0.08] text-[#164e63] dark:text-[var(--app-text)] shadow-sm' : 'text-black/40 dark:text-white/40 hover:text-black/60 dark:hover:text-white/60'}`}
        >
          <MapPin size={14} />
          {zh ? 'IP 定位' : 'IP Locate'}
        </button>
        <button
          onClick={() => setActiveTab('probe')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${activeTab === 'probe' ? 'bg-white dark:bg-white/[0.08] text-[#164e63] dark:text-[var(--app-text)] shadow-sm' : 'text-black/40 dark:text-white/40 hover:text-black/60 dark:hover:text-white/60'}`}
        >
          <Activity size={14} />
          {zh ? '连通性探测' : 'Connectivity Probe'}
        </button>
        <button
          onClick={() => setActiveTab('arp-table')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${activeTab === 'arp-table' ? 'bg-white dark:bg-white/[0.08] text-[#164e63] dark:text-[var(--app-text)] shadow-sm' : 'text-black/40 dark:text-white/40 hover:text-black/60 dark:hover:text-white/60'}`}
        >
          <Database size={14} />
          {zh ? 'ARP 表' : 'ARP Table'}
          {arpTable && <span className="text-[10px] bg-[#06b6d4]/10 text-[#0891b2] rounded-full px-1.5 py-0.5 font-mono">{arpTable.total}</span>}
        </button>
        <button
          onClick={() => setActiveTab('mac-changes')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${activeTab === 'mac-changes' ? 'bg-white dark:bg-white/[0.08] text-[#164e63] dark:text-[var(--app-text)] shadow-sm' : 'text-black/40 dark:text-white/40 hover:text-black/60 dark:hover:text-white/60'}`}
        >
          <RefreshCw size={14} />
          {zh ? 'MAC 变更' : 'MAC Changes'}
          {macChanges && macChanges.total > 0 && <span className="text-[10px] bg-amber-100 dark:bg-amber-500/15 text-amber-600 dark:text-amber-400 rounded-full px-1.5 py-0.5 font-mono">{macChanges.total}</span>}
        </button>
      </div>

      {/* ────────────────────────────────────── */}
      {/* TAB: IP Locate                         */}
      {/* ────────────────────────────────────── */}
      {activeTab === 'locate' && (<>
      {/* ── Search Card ── */}
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-5">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-lg">
            <MapPin size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#0891b2]" />
            <input
              type="text"
              value={ip}
              onChange={e => setIp(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={zh ? '输入 IP 地址，如 10.1.1.100 或 192.168.1.1' : 'Enter IP address, e.g. 10.1.1.100'}
              className="w-full pl-10 pr-4 py-3 rounded-xl border border-black/10 text-sm bg-white focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all placeholder:text-black/30"
              autoFocus
            />
          </div>
          <button
            onClick={() => doLocate()}
            disabled={loading || !ip.trim()}
            className="px-6 py-3 rounded-xl bg-[#0891b2] text-white text-sm font-semibold hover:bg-[#0e7490] disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2 shadow-sm"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
            {zh ? '定位' : 'Locate'}
          </button>
          {result?.cache?.arp_cache_hit && (
            <button
              onClick={() => doLocate(undefined, true)}
              disabled={loading}
              title={zh ? '跳过缓存，从设备实时采集最新数据' : 'Skip cache and query devices in real-time'}
              className="px-3 py-3 rounded-xl border border-amber-300 dark:border-amber-500/30 text-amber-600 dark:text-amber-400 text-sm hover:bg-amber-50 dark:hover:bg-amber-500/10 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5 font-medium"
            >
              <RotateCcw size={14} />
              {zh ? '实时刷新' : 'Refresh'}
            </button>
          )}
        </div>

        {/* Inline tips */}
        <div className="flex items-center gap-4 mt-3 text-[11px] text-black/30">
          <span>{zh ? '回车键快速查询' : 'Press Enter to search'}</span>
          <span>·</span>
          <span>{zh ? '流程：ARP 表查 MAC → MAC 表查端口 → LLDP 查上联' : 'Flow: ARP→MAC→Switch Port→LLDP Uplink'}</span>
        </div>
      </div>

      {/* ── Loading ── */}
      {loading && (
        <div className="bg-[#ecfeff]/60 dark:bg-cyan-500/5 border border-[#06b6d4]/20 rounded-2xl px-6 py-5">
          <div className="flex items-center gap-3">
            <Loader2 size={20} className="animate-spin text-[#0891b2]" />
            <div>
              <p className="text-sm font-semibold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '正在定位...' : 'Locating...'}</p>
              <p className="text-xs text-[#0891b2] mt-0.5">{zh ? '正在查询网关 ARP 表和交换机 MAC 地址表，请稍候' : 'Querying gateway ARP tables and switch MAC tables, please wait'}</p>
            </div>
          </div>
        </div>
      )}

      {/* ── Error ── */}
      {error && !loading && (
        <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-2xl px-5 py-4 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-300">{zh ? '查询失败' : 'Locate Failed'}</p>
            <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* ── Result ── */}
      {result && !loading && (
        <div className="space-y-4">
          {result.found && accessLocations.length > 0 ? (
            <div className="bg-gradient-to-r from-emerald-50 to-[#ecfeff] dark:from-emerald-950/40 dark:to-cyan-950/30 border border-emerald-200/60 dark:border-emerald-500/20 rounded-2xl overflow-hidden">
              {/* Path header */}
              <div className="px-5 py-3.5 border-b border-emerald-200/40 dark:border-emerald-500/15 bg-white/40 dark:bg-white/[0.03]">
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="w-6 h-6 rounded-full bg-emerald-500 flex items-center justify-center">
                    <MapPin size={13} className="text-white" />
                  </div>
                  <span className="text-sm font-bold text-emerald-800 dark:text-emerald-300">{zh ? '定位成功' : 'Located'}</span>
                  {result.cache?.arp_cache_hit && result.cache.cached_at ? (
                    <span className="inline-flex items-center gap-1 text-[10px] bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-200/60 dark:border-amber-500/20 rounded-full px-2.5 py-0.5 font-medium">
                      <Clock size={10} />
                      {zh ? `ARP 缓存命中 · ${formatRelativeTime(result.cache.cached_at, zh)}采集` : `ARP cached · collected ${formatRelativeTime(result.cache.cached_at, false)}`}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[10px] bg-emerald-100/60 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-500/20 rounded-full px-2.5 py-0.5 font-medium">
                      <Zap size={10} />
                      {zh ? '实时采集' : 'Real-time'}
                    </span>
                  )}
                  <span className="text-xs text-emerald-600 dark:text-emerald-400/70 ml-auto font-mono">{result.timestamp?.replace('T', ' ').slice(0, 19)}</span>
                </div>
              </div>

              {/* Path flow: IP → MAC → Switch:Port */}
              <div className="px-5 py-5">
                <div className="flex items-center gap-1.5 flex-wrap">
                  {/* IP */}
                  <div className="flex items-center gap-2.5 bg-white dark:bg-white/[0.06] rounded-xl px-4 py-3 border border-black/8 dark:border-white/10 shadow-sm">
                    <Monitor size={16} className="text-violet-500" />
                    <div>
                      <p className="text-[10px] text-black/40 dark:text-white/40 font-medium uppercase tracking-wide">IP</p>
                      <p className="text-base font-bold text-[#164e63] dark:text-[var(--app-text)] font-mono">{result.target_ip}</p>
                    </div>
                  </div>

                  <ArrowRight size={16} className="text-black/20 dark:text-white/20 mx-1 flex-shrink-0" />

                  {/* MAC */}
                  <div className="flex items-center gap-2.5 bg-white dark:bg-white/[0.06] rounded-xl px-4 py-3 border border-black/8 dark:border-white/10 shadow-sm">
                    <Cable size={16} className="text-amber-500" />
                    <div>
                      <p className="text-[10px] text-black/40 dark:text-white/40 font-medium uppercase tracking-wide">MAC</p>
                      <p className="text-base font-bold text-[#164e63] dark:text-[var(--app-text)] font-mono">{result.mac_display}</p>
                      {result.arp_source && (
                        <p className="text-[10px] text-black/35 mt-0.5">
                          via {result.arp_source.device} ({result.arp_source.interface})
                        </p>
                      )}
                    </div>
                  </div>

                  <ArrowRight size={16} className="text-black/20 dark:text-white/20 mx-1 flex-shrink-0" />

                  {/* Switch:Port(s) */}
                  {accessLocations.map((loc, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <span className="text-xs text-black/30 mx-1">/</span>}
                      <div className="flex items-center gap-2.5 bg-white dark:bg-white/[0.06] rounded-xl px-4 py-3 border border-[#06b6d4]/30 dark:border-[#06b6d4]/20 shadow-sm ring-1 ring-[#06b6d4]/10">
                        <Server size={16} className="text-[#0891b2]" />
                        <div>
                          <p className="text-[10px] text-black/40 dark:text-white/40 font-medium uppercase tracking-wide">
                            {loc.type === 'ARP_DIRECT'
                              ? (zh ? 'ARP 来源设备:接口' : 'ARP Source:Interface')
                              : (zh ? '交换机:端口' : 'Switch:Port')}
                          </p>
                          <p className="text-base font-bold text-[#164e63] dark:text-[var(--app-text)]">
                            <span className="font-mono">{loc.switch_name}</span>
                            <span className="text-[#0891b2] mx-1">:</span>
                            <span className="font-mono text-[#0891b2]">{loc.port}</span>
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            {loc.vlan && <span className="text-[10px] bg-cyan-50 dark:bg-cyan-500/10 text-cyan-700 dark:text-cyan-400 rounded px-1.5 py-0.5 font-medium">VLAN {loc.vlan}</span>}
                            {loc.type === 'ARP_DIRECT'
                              ? <span className="text-[10px] bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 rounded px-1.5 py-0.5 font-medium">{zh ? '直连/网关' : 'Direct/Gateway'}</span>
                              : loc.type && <span className="text-[10px] text-black/35">{loc.type}</span>}
                          </div>
                          {loc.note && (
                            <p className="text-[10px] text-amber-600 mt-1">{loc.note}</p>
                          )}
                          {loc.uplink_neighbor && (
                            <p className="text-[10px] text-black/35 mt-1 flex items-center gap-1">
                              <Network size={10} />
                              {zh ? '上联' : 'Uplink'}: {loc.uplink_neighbor} ({loc.uplink_port})
                            </p>
                          )}
                        </div>
                      </div>
                    </React.Fragment>
                  ))}
                </div>

                {/* Uplink entries */}
                {uplinkLocations.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-emerald-200/40 dark:border-emerald-500/15">
                    <p className="text-[10px] text-black/35 dark:text-white/35 font-medium mb-2">{zh ? '上联口也匹配到该 MAC（可忽略）' : 'Also seen on uplink ports (can ignore)'}:</p>
                    <div className="flex flex-wrap gap-1.5">
                      {uplinkLocations.map((loc, i) => (
                        <span key={i} className="text-[10px] bg-black/5 text-black/50 rounded px-2 py-0.5 font-mono">
                          {loc.switch_name}:{loc.port}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : !result.found ? (
            <div className="bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 rounded-2xl px-5 py-4">
              <div className="flex items-start gap-3">
                <AlertCircle size={18} className="text-amber-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">{zh ? '未找到该 IP 地址' : 'IP Address Not Found'}</p>
                  {result.errors?.map((err, i) => (
                    <p key={i} className="text-xs text-amber-600 mt-0.5">{err}</p>
                  ))}
                  {result.mac && (
                    <p className="text-xs text-amber-600 mt-1.5">
                      {zh ? `MAC 地址 ${result.mac_display} 已从 ARP 表获取，但未在任何交换机 MAC 表中匹配到端口` : `MAC ${result.mac_display} resolved from ARP but not found in any switch MAC table`}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : null}

          {/* Detail toggle */}
          {result.searched_devices && (
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="flex items-center gap-1.5 text-xs text-black/40 dark:text-white/40 hover:text-black/60 dark:hover:text-white/60 transition-colors ml-1"
            >
              {showDetails ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {zh ? `查询详情（扫描了 ${result.searched_devices.arp?.length || 0} 台 ARP + ${result.searched_devices.mac?.length || 0} 台 MAC）` :
                `Details (scanned ${result.searched_devices.arp?.length || 0} ARP + ${result.searched_devices.mac?.length || 0} MAC devices)`}
            </button>
          )}

          {showDetails && result.searched_devices && (
            <div className="bg-black/[0.02] dark:bg-white/[0.03] rounded-xl border border-black/5 dark:border-white/8 px-5 py-3.5 text-xs text-black/50 dark:text-white/50 space-y-2">
              {result.cache?.arp_cache_hit && result.cache.cached_at && (
                <div className="flex items-center gap-2 pb-2 border-b border-black/5 mb-1">
                  <Clock size={11} className="text-amber-500" />
                  <span className="font-semibold text-amber-600">{zh ? 'ARP 数据来源' : 'ARP Data Source'}:</span>
                  <span className="text-amber-600">
                    {zh
                      ? `缓存命中（${formatRelativeTime(result.cache.cached_at, true)}采集，TTL ${result.cache.ttl_seconds}s）`
                      : `Cache hit (collected ${formatRelativeTime(result.cache.cached_at, false)}, TTL ${result.cache.ttl_seconds}s)`}
                  </span>
                </div>
              )}
              <div>
                <span className="font-semibold text-black/60 dark:text-white/60">{zh ? 'ARP 查询设备' : 'ARP Devices'}:</span>{' '}
                {result.cache?.arp_cache_hit
                  ? (zh ? '（缓存命中，未查设备）' : '(cache hit, no device queried)')
                  : (result.searched_devices.arp?.join(', ') || '-')}
              </div>
              <div>
                <span className="font-semibold text-black/60 dark:text-white/60">{zh ? 'MAC 查询设备' : 'MAC Devices'}:</span>{' '}
                {result.searched_devices.mac?.join(', ') || '-'}
              </div>
              {(result.searched_devices.lldp?.length ?? 0) > 0 && (
                <div>
                  <span className="font-semibold text-black/60 dark:text-white/60">{zh ? 'LLDP 查询设备' : 'LLDP Devices'}:</span>{' '}
                  {result.searched_devices.lldp?.join(', ')}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── History ── */}
      {history.length > 0 && !loading && (
        <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-5">
          <div className="flex items-center gap-2 mb-3">
            <Clock size={14} className="text-black/30 dark:text-white/30" />
            <p className="text-xs font-semibold text-black/40 dark:text-white/40 uppercase tracking-wider">{zh ? '查询历史' : 'Recent Queries'}</p>
            <button
              onClick={() => setHistory([])}
              className="ml-auto text-[10px] text-black/25 dark:text-white/25 hover:text-black/50 dark:hover:text-white/50 transition-colors flex items-center gap-1"
            >
              <RotateCcw size={10} />
              {zh ? '清空' : 'Clear'}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => doLocate(h.ip)}
                className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono transition-all hover:shadow-sm ${h.found ? 'border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-500/15' : 'border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-500/15'}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${h.found ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                {h.ip}
                {h.found && <span className="text-[10px] text-black/30 font-sans">→ {h.switch_name}:{h.port}</span>}
              </button>
            ))}
          </div>
        </div>
      )}
      </>)}

      {/* ────────────────────────────────────── */}
      {/* TAB: Connectivity Probe                */}
      {/* ────────────────────────────────────── */}
      {activeTab === 'probe' && (<>

      {/* ── Probe Search Card ── */}
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-5 space-y-4">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-lg">
            <Activity size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#0891b2]" />
            <input
              type="text"
              value={probeIp}
              onChange={e => setProbeIp(e.target.value)}
              onKeyDown={handleProbeKeyDown}
              placeholder={zh ? '输入目标 IP，如 10.1.1.1 或 192.168.1.1' : 'Target IP, e.g. 10.1.1.1'}
              className="w-full pl-10 pr-4 py-3 rounded-xl border border-black/10 text-sm bg-white focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all placeholder:text-black/30"
            />
          </div>
          <button
            onClick={doProbe}
            disabled={probeLoading || !probeIp.trim()}
            className="px-6 py-3 rounded-xl bg-[#0891b2] text-white text-sm font-semibold hover:bg-[#0e7490] disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2 shadow-sm"
          >
            {probeLoading ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />}
            {zh ? '探测' : 'Probe'}
          </button>
        </div>

        {/* Options row */}
        <div className="flex flex-wrap items-center gap-4">
          {/* Test toggles */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-black/40 dark:text-white/40 font-medium">{zh ? '测试项:' : 'Tests:'}</span>
            {(['ping', 'tcp', 'traceroute'] as const).map(t => (
              <button
                key={t}
                onClick={() => toggleTest(t)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all border ${probeTests.has(t) ? 'bg-[#ecfeff] dark:bg-cyan-500/10 border-[#06b6d4]/30 text-[#0891b2]' : 'bg-black/[0.02] dark:bg-white/[0.04] border-black/5 dark:border-white/8 text-black/30 dark:text-white/30'}`}
              >
                {t === 'ping' ? 'PING' : t === 'tcp' ? 'TCP' : 'Traceroute'}
              </button>
            ))}
          </div>

          {/* TCP Ports */}
          {probeTests.has('tcp') && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-black/40 dark:text-white/40 font-medium">{zh ? '端口:' : 'Ports:'}</span>
              <input
                type="text"
                value={probePorts}
                onChange={e => setProbePorts(e.target.value)}
                placeholder="22, 80, 443"
                className="w-36 px-3 py-1 rounded-lg border border-black/10 text-xs font-mono bg-white focus:ring-2 focus:ring-[#06b6d4]/20 outline-none"
              />
            </div>
          )}

          {/* Source device */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-black/40 dark:text-white/40 font-medium">{zh ? '探测源:' : 'Source:'}</span>
            <select
              value={sourceDeviceId ?? ''}
              onChange={e => setSourceDeviceId(e.target.value ? Number(e.target.value) : null)}
              title={zh ? '选择探测源设备' : 'Select probe source device'}
              className="px-3 py-1 rounded-lg border border-black/10 text-xs bg-white focus:ring-2 focus:ring-[#06b6d4]/20 outline-none min-w-[120px]"
            >
              <option value="">{zh ? '服务器（本机）' : 'Server (local)'}</option>
              {devices.map(d => (
                <option key={d.id} value={d.id}>{d.hostname || d.ip_address}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* ── Probe Loading ── */}
      {probeLoading && (
        <div className="bg-[#ecfeff]/60 dark:bg-cyan-500/5 border border-[#06b6d4]/20 rounded-2xl px-6 py-5">
          <div className="flex items-center gap-3">
            <Loader2 size={20} className="animate-spin text-[#0891b2]" />
            <div>
              <p className="text-sm font-semibold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '正在探测...' : 'Probing...'}</p>
              <p className="text-xs text-[#0891b2] mt-0.5">{zh ? '执行 PING/TCP/Traceroute 测试，请稍候' : 'Running PING/TCP/Traceroute tests, please wait'}</p>
            </div>
          </div>
        </div>
      )}

      {/* ── Probe Error ── */}
      {probeError && !probeLoading && (
        <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-2xl px-5 py-4 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-300">{zh ? '探测失败' : 'Probe Failed'}</p>
            <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{probeError}</p>
          </div>
        </div>
      )}

      {/* ── Probe Result ── */}
      {probeResult && !probeLoading && (
        <div className="space-y-4">
          {/* Header */}
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-black/5 dark:border-white/8 bg-gradient-to-r from-[#ecfeff]/50 dark:from-cyan-950/30 to-transparent">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-[#0891b2] flex items-center justify-center">
                  <Activity size={14} className="text-white" />
                </div>
                <div>
                  <span className="text-sm font-bold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '探测结果' : 'Probe Results'}</span>
                  <span className="text-xs text-black/35 dark:text-white/35 ml-3">{probeResult.target}</span>
                  {probeResult.source_device && (
                    <span className="text-xs text-[#0891b2] ml-2">via {probeResult.source_device}</span>
                  )}
                </div>
                <span className="text-[10px] text-black/30 ml-auto font-mono">{probeResult.timestamp?.replace('T', ' ').slice(0, 19)}</span>
              </div>
            </div>

            <div className="p-5 space-y-5">
              {/* ── PING Result ── */}
              {probeResult.tests.ping && (() => {
                const p = probeResult.tests.ping!;
                return (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Wifi size={14} className="text-[#0891b2]" />
                      <span className="text-xs font-bold text-[#164e63] dark:text-[var(--app-text)] uppercase tracking-wide">PING</span>
                      {p.success
                        ? <CheckCircle2 size={14} className="text-emerald-500" />
                        : <XCircle size={14} className="text-red-500" />}
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      <div className="bg-black/[0.02] dark:bg-white/[0.04] rounded-xl px-4 py-3">
                        <p className="text-[10px] text-black/40 dark:text-white/40 font-medium">{zh ? '状态' : 'Status'}</p>
                        <p className={`text-sm font-bold ${p.success ? 'text-emerald-600' : 'text-red-600'}`}>
                          {p.success ? (zh ? '可达' : 'Reachable') : (zh ? '不可达' : 'Unreachable')}
                        </p>
                      </div>
                      <div className="bg-black/[0.02] dark:bg-white/[0.04] rounded-xl px-4 py-3">
                        <p className="text-[10px] text-black/40 dark:text-white/40 font-medium">{zh ? '丢包率' : 'Loss'}</p>
                        <p className={`text-sm font-bold ${p.loss_percent === 0 ? 'text-emerald-600' : p.loss_percent < 50 ? 'text-amber-600' : 'text-red-600'}`}>
                          {p.loss_percent}%
                        </p>
                      </div>
                      <div className="bg-black/[0.02] dark:bg-white/[0.04] rounded-xl px-4 py-3">
                        <p className="text-[10px] text-black/40 dark:text-white/40 font-medium">{zh ? '平均延迟' : 'Avg RTT'}</p>
                        <p className="text-sm font-bold text-[#164e63] dark:text-[var(--app-text)] font-mono">
                          {p.rtt.avg != null ? `${p.rtt.avg} ms` : '-'}
                        </p>
                      </div>
                      <div className="bg-black/[0.02] dark:bg-white/[0.04] rounded-xl px-4 py-3">
                        <p className="text-[10px] text-black/40 dark:text-white/40 font-medium">{zh ? '延迟范围' : 'RTT Range'}</p>
                        <p className="text-xs font-mono text-black/50 dark:text-white/50">
                          {p.rtt.min != null && p.rtt.max != null ? `${p.rtt.min} – ${p.rtt.max} ms` : '-'}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* ── TCP Result ── */}
              {probeResult.tests.tcp && probeResult.tests.tcp.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Globe size={14} className="text-[#0891b2]" />
                    <span className="text-xs font-bold text-[#164e63] dark:text-[var(--app-text)] uppercase tracking-wide">TCP</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {probeResult.tests.tcp.map((tc, i) => (
                      <div
                        key={i}
                        className={`flex items-center gap-2.5 rounded-xl px-4 py-3 border ${tc.success ? 'bg-emerald-50/50 dark:bg-emerald-500/10 border-emerald-200/60 dark:border-emerald-500/20' : 'bg-red-50/50 dark:bg-red-500/10 border-red-200/60 dark:border-red-500/20'}`}
                      >
                        {tc.success
                          ? <CheckCircle2 size={14} className="text-emerald-500 flex-shrink-0" />
                          : <XCircle size={14} className="text-red-400 flex-shrink-0" />}
                        <div>
                          <p className="text-sm font-bold font-mono text-[#164e63] dark:text-[var(--app-text)]">
                            :{tc.port}
                          </p>
                          <p className={`text-[10px] ${tc.success ? 'text-emerald-600' : 'text-red-500'}`}>
                            {tc.success ? `${tc.latency_ms} ms` : (zh ? tc.detail : tc.detail)}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Traceroute Result ── */}
              {probeResult.tests.traceroute && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Network size={14} className="text-[#0891b2]" />
                    <span className="text-xs font-bold text-[#164e63] dark:text-[var(--app-text)] uppercase tracking-wide">Traceroute</span>
                    <span className="text-[10px] text-black/30 dark:text-white/30">
                      {probeResult.tests.traceroute.hops?.length || 0} {zh ? '跳' : 'hops'}
                    </span>
                  </div>
                  {probeResult.tests.traceroute.hops?.length > 0 ? (
                    <div className="bg-black/[0.02] dark:bg-white/[0.03] rounded-xl border border-black/5 dark:border-white/8 overflow-hidden">
                      <div className="grid grid-cols-[3rem_1fr_6rem] text-[10px] font-medium text-black/40 dark:text-white/40 uppercase tracking-wider px-4 py-2 border-b border-black/5 dark:border-white/8">
                        <span>{zh ? '跳数' : 'Hop'}</span>
                        <span>IP</span>
                        <span>{zh ? '延迟' : 'RTT'}</span>
                      </div>
                      {probeResult.tests.traceroute.hops.map((h, i) => (
                        <div key={i} className={`grid grid-cols-[3rem_1fr_6rem] px-4 py-2 text-xs ${i % 2 ? 'bg-black/[0.01] dark:bg-white/[0.02]' : ''} ${h.ip === probeResult.target ? 'bg-emerald-50/50 dark:bg-emerald-500/10' : ''}`}>
                          <span className="text-black/40 dark:text-white/40 font-mono">{h.hop}</span>
                          <span className={`font-mono ${h.timeout ? 'text-black/25 dark:text-white/25' : h.ip === probeResult.target ? 'text-emerald-700 dark:text-emerald-400 font-semibold' : 'text-[#164e63] dark:text-[var(--app-text)]'}`}>
                            {h.ip}
                          </span>
                          <span className="text-black/40 dark:text-white/40 font-mono">
                            {h.rtt_ms.length > 0 ? h.rtt_ms.map(r => `${r}ms`).join(' / ') : (h.timeout ? '*' : '-')}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-black/35">{zh ? '未获取到路由跳数' : 'No hops captured'}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      </>)}

      {/* ────────────────────────────────────── */}
      {/* TAB: ARP Table                         */}
      {/* ────────────────────────────────────── */}
      {activeTab === 'arp-table' && (<>

      {/* ── Controls ── */}
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-5">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 max-w-md">
            <Filter size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-black/30" />
            <input
              type="text"
              value={arpFilter}
              onChange={e => { setArpFilter(e.target.value); setArpPage(1); }}
              placeholder={zh ? '搜索 IP / MAC / 厂商 / 设备 / 接口...' : 'Filter by IP / MAC / vendor / device / interface...'}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-black/10 text-sm bg-white focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all placeholder:text-black/30"
            />
          </div>
          <button
            onClick={fetchArpTable}
            disabled={arpLoading}
            className="px-4 py-2.5 rounded-xl border border-black/10 text-sm text-black/50 hover:bg-black/[0.03] disabled:opacity-40 transition-all flex items-center gap-1.5"
          >
            <RotateCcw size={13} className={arpLoading ? 'animate-spin' : ''} />
            {zh ? '刷新' : 'Refresh'}
          </button>
          <button
            onClick={triggerArpSweep}
            disabled={arpSweeping || arpLoading}
            title={zh ? '立即从所有网关设备采集全量 ARP 数据' : 'Collect full ARP data from all gateways now'}
            className="px-4 py-2.5 rounded-xl bg-[#0891b2] text-white text-sm font-semibold hover:bg-[#0e7490] disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5 shadow-sm"
          >
            {arpSweeping ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            {zh ? '立即采集' : 'Sweep Now'}
          </button>
          <button
            onClick={() => {
              if (!arpTable || arpTable.entries.length === 0) return;
              const q = arpFilter.trim().toLowerCase();
              const rows = (q ? arpTable.entries.filter(e =>
                e.ip.toLowerCase().includes(q) || e.mac.toLowerCase().includes(q) ||
                e.device.toLowerCase().includes(q) || e.interface.toLowerCase().includes(q) ||
                (e.vendor || '').toLowerCase().includes(q)
              ) : arpTable.entries).map(e => ({
                IP: e.ip,
                MAC: e.mac,
                [zh ? '厂商' : 'Vendor']: e.vendor || '',
                [zh ? '接口' : 'Interface']: e.interface || '',
                [zh ? '来源设备' : 'Device']: e.device || '',
                [zh ? '采集时间' : 'Collected']: e.cached_at?.replace('T', ' ').slice(0, 19) || '',
              }));
              const ws = XLSX.utils.json_to_sheet(rows);
              const wb = XLSX.utils.book_new();
              XLSX.utils.book_append_sheet(wb, ws, 'ARP Table');
              XLSX.writeFile(wb, `arp_table_${new Date().toISOString().slice(0, 10)}.xlsx`);
            }}
            disabled={!arpTable || arpTable.total === 0}
            className="px-4 py-2.5 rounded-xl border border-black/10 text-sm text-black/50 hover:bg-black/[0.03] disabled:opacity-40 transition-all flex items-center gap-1.5"
          >
            <Download size={13} />
            {zh ? '导出' : 'Export'}
          </button>
        </div>

        {/* Stats bar */}
        {arpTable && (
          <div className="flex items-center gap-4 mt-3 text-[11px] text-black/30 flex-wrap">
            <span className="flex items-center gap-1"><Database size={10} /> {arpTable.total} {zh ? '条记录' : 'entries'}</span>
            <span>·</span>
            <span>{zh ? `采集间隔 ${Math.round(arpTable.sweep_interval_seconds / 60)} 分钟` : `Sweep every ${Math.round(arpTable.sweep_interval_seconds / 60)}m`}</span>
            <span>·</span>
            <span>{zh ? `TTL ${Math.round(arpTable.ttl_seconds / 60)} 分钟` : `TTL ${Math.round(arpTable.ttl_seconds / 60)}m`}</span>
            <span>·</span>
            <span>{zh ? '更新时间' : 'Updated'}: {arpTable.timestamp?.replace('T', ' ').slice(0, 19)}</span>
          </div>
        )}
      </div>

      {/* ── Error ── */}
      {arpError && !arpLoading && (
        <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-2xl px-5 py-4 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-300">{zh ? '加载失败' : 'Load Failed'}</p>
            <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{arpError}</p>
          </div>
        </div>
      )}

      {/* ── Loading ── */}
      {arpLoading && (
        <div className="bg-[#ecfeff]/60 dark:bg-cyan-500/5 border border-[#06b6d4]/20 rounded-2xl px-6 py-5">
          <div className="flex items-center gap-3">
            <Loader2 size={18} className="text-[#0891b2] animate-spin" />
            <span className="text-sm font-semibold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '正在加载 ARP 表...' : 'Loading ARP table...'}</span>
          </div>
        </div>
      )}

      {/* ── Empty state ── */}
      {!arpLoading && !arpError && arpTable && arpTable.total === 0 && (
        <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-8 text-center">
          <Database size={32} className="mx-auto text-black/15 dark:text-white/15 mb-3" />
          <p className="text-sm text-black/40 dark:text-white/40">{zh ? '暂无 ARP 缓存数据。点击「立即采集」从网关设备获取 ARP 表。' : 'No ARP cache data. Click "Sweep Now" to collect from gateways.'}</p>
        </div>
      )}

      {/* ── ARP Table ── */}
      {!arpLoading && arpTable && arpTable.total > 0 && (() => {
        const q = arpFilter.trim().toLowerCase();
        const filtered = q
          ? arpTable.entries.filter(e =>
              e.ip.toLowerCase().includes(q) ||
              e.mac.toLowerCase().includes(q) ||
              e.mac_raw.toLowerCase().includes(q) ||
              e.device.toLowerCase().includes(q) ||
              e.interface.toLowerCase().includes(q) ||
              (e.vendor || '').toLowerCase().includes(q)
            )
          : arpTable.entries;
        const pageStart = (arpPage - 1) * arpPageSize;
        const pageEntries = filtered.slice(pageStart, pageStart + arpPageSize);

        return (
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
            {/* Table header */}
            <div className="grid grid-cols-[1fr_1fr_6rem_6rem_10rem_8rem] gap-2 px-5 py-2.5 text-[10px] font-bold text-black/40 dark:text-white/40 uppercase tracking-wider border-b border-black/5 dark:border-white/8 bg-black/[0.01] dark:bg-white/[0.02]">
              <span>IP</span>
              <span>MAC</span>
              <span>{zh ? '厂商' : 'Vendor'}</span>
              <span>{zh ? '接口' : 'Interface'}</span>
              <span>{zh ? '来源设备' : 'Device'}</span>
              <span>{zh ? '采集时间' : 'Collected'}</span>
            </div>

            {/* Table body */}
            <div>
              {filtered.length === 0 ? (
                <div className="px-5 py-6 text-center text-xs text-black/30">
                  {zh ? `未找到匹配 "${arpFilter}" 的记录` : `No entries matching "${arpFilter}"`}
                </div>
              ) : (
                pageEntries.map((entry, idx) => (
                  <div
                    key={entry.ip}
                    className={`grid grid-cols-[1fr_1fr_6rem_6rem_10rem_8rem] gap-2 px-5 py-2 text-xs items-center border-b border-black/[0.03] dark:border-white/[0.05] hover:bg-[#ecfeff]/30 dark:hover:bg-cyan-500/5 transition-colors cursor-pointer ${idx % 2 ? 'bg-black/[0.008] dark:bg-white/[0.015]' : ''}`}
                    onClick={() => { setIp(entry.ip); setActiveTab('locate'); }}
                    title={zh ? '点击定位此 IP' : 'Click to locate this IP'}
                  >
                    <span className="font-mono font-semibold text-[#164e63]">{entry.ip}</span>
                    <span className="font-mono text-black/50">{entry.mac}</span>
                    <span className="text-black/45 truncate" title={entry.vendor}>{entry.vendor || '-'}</span>
                    <span className="text-black/45 truncate" title={entry.interface}>{entry.interface || '-'}</span>
                    <span className="text-[#0891b2] truncate font-medium" title={entry.device}>{entry.device || '-'}</span>
                    <span className="text-black/30" title={entry.cached_at}>{formatRelativeTime(entry.cached_at, zh)}</span>
                  </div>
                ))
              )}
            </div>

            <Pagination
              currentPage={arpPage}
              totalItems={filtered.length}
              itemsPerPage={arpPageSize}
              onPageChange={setArpPage}
              onItemsPerPageChange={(v) => { setArpPage(1); setArpPageSize(v); }}
              language={language}
            />
          </div>
        );
      })()}

      </>)}

      {/* ────────────────────────────────────── */}
      {/* TAB: MAC Changes                       */}
      {/* ────────────────────────────────────── */}
      {activeTab === 'mac-changes' && (<>

      {/* ── Controls ── */}
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-5">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
            <input
              value={macFilter}
              onChange={e => { setMacFilter(e.target.value); setMacPage(1); }}
              placeholder={zh ? '搜索 IP / MAC / 厂商 / 设备...' : 'Search IP / MAC / Vendor / Device...'}
              className="w-full pl-9 pr-8 py-2.5 text-sm bg-black/[0.02] border border-black/8 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all"
            />
            {macFilter && (
              <button onClick={() => { setMacFilter(''); setMacPage(1); }} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                <X size={13} />
              </button>
            )}
          </div>
          <button
            onClick={fetchMacChanges}
            disabled={macChangesLoading}
            className="px-4 py-2.5 rounded-xl border border-black/10 text-sm text-black/50 hover:bg-black/[0.03] disabled:opacity-40 transition-all flex items-center gap-1.5"
          >
            <RotateCcw size={13} className={macChangesLoading ? 'animate-spin' : ''} />
            {zh ? '刷新' : 'Refresh'}
          </button>
        </div>
        {macChanges && (
          <div className="flex items-center gap-4 mt-3 text-[11px] text-black/30 dark:text-white/30 flex-wrap">
            <span>{macChanges.total} {zh ? '条变更记录' : 'change records'}</span>
            <span>·</span>
            <span>{zh ? '更新时间' : 'Updated'}: {macChanges.timestamp?.replace('T', ' ').slice(0, 19)}</span>
          </div>
        )}
      </div>

      {/* ── Error ── */}
      {macChangesError && !macChangesLoading && (
        <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-2xl px-5 py-4 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-300">{zh ? '加载失败' : 'Load Failed'}</p>
            <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{macChangesError}</p>
          </div>
        </div>
      )}

      {/* ── Loading ── */}
      {macChangesLoading && (
        <div className="bg-[#ecfeff]/60 dark:bg-cyan-500/5 border border-[#06b6d4]/20 rounded-2xl px-6 py-5">
          <div className="flex items-center gap-3">
            <Loader2 size={18} className="text-[#0891b2] animate-spin" />
            <span className="text-sm font-semibold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '正在加载变更记录...' : 'Loading change log...'}</span>
          </div>
        </div>
      )}

      {/* ── Empty ── */}
      {!macChangesLoading && !macChangesError && macChanges && macChanges.total === 0 && (
        <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-8 text-center">
          <CheckCircle2 size={32} className="mx-auto text-emerald-300 dark:text-emerald-500/50 mb-3" />
          <p className="text-sm text-black/40 dark:text-white/40">{zh ? '暂无 MAC 变更记录。所有 IP-MAC 绑定关系稳定。' : 'No MAC changes detected. All IP-MAC bindings are stable.'}</p>
        </div>
      )}

      {/* ── Change List ── */}
      {!macChangesLoading && macChanges && macChanges.total > 0 && (() => {
        const q = macFilter.trim().toLowerCase();
        const filtered = q
          ? macChanges.entries.filter(e =>
              e.ip.toLowerCase().includes(q) ||
              e.old_mac.toLowerCase().includes(q) ||
              e.new_mac.toLowerCase().includes(q) ||
              (e.old_vendor || '').toLowerCase().includes(q) ||
              (e.new_vendor || '').toLowerCase().includes(q) ||
              (e.old_device || '').toLowerCase().includes(q) ||
              (e.new_device || '').toLowerCase().includes(q)
            )
          : macChanges.entries;
        const pageStart = (macPage - 1) * macPageSize;
        const pageEntries = filtered.slice(pageStart, pageStart + macPageSize);

        return (
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
            {/* Table header */}
            <div className="grid grid-cols-[8rem_1fr_1fr_8rem_8rem] gap-2 px-5 py-2.5 text-[10px] font-bold text-black/40 dark:text-white/40 uppercase tracking-wider border-b border-black/5 dark:border-white/8 bg-black/[0.01] dark:bg-white/[0.02]">
              <span>IP</span>
              <span>{zh ? '旧 MAC → 新 MAC' : 'Old MAC → New MAC'}</span>
              <span>{zh ? '厂商变化' : 'Vendor Change'}</span>
              <span>{zh ? '来源设备' : 'Device'}</span>
              <span>{zh ? '检测时间' : 'Detected'}</span>
            </div>

            <div>
              {filtered.length === 0 ? (
                <div className="px-5 py-6 text-center text-xs text-black/30">
                  {zh ? `未找到匹配 "${macFilter}" 的记录` : `No entries matching "${macFilter}"`}
                </div>
              ) : (
                pageEntries.map((entry, idx) => (
                  <div
                    key={entry.id}
                    className={`grid grid-cols-[8rem_1fr_1fr_8rem_8rem] gap-2 px-5 py-2.5 text-xs items-center border-b border-black/[0.03] dark:border-white/[0.05] hover:bg-amber-50/30 dark:hover:bg-amber-500/5 transition-colors ${idx % 2 ? 'bg-black/[0.008] dark:bg-white/[0.015]' : ''}`}
                  >
                    <span
                      className="font-mono font-semibold text-[#164e63] cursor-pointer hover:text-[#0891b2]"
                      onClick={() => { setIp(entry.ip); setActiveTab('locate'); }}
                      title={zh ? '点击定位此 IP' : 'Click to locate this IP'}
                    >{entry.ip}</span>
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="font-mono text-red-400 truncate" title={entry.old_mac}>{entry.old_mac}</span>
                      <ArrowRight size={12} className="text-black/20 dark:text-white/20 flex-shrink-0" />
                      <span className="font-mono text-emerald-600 dark:text-emerald-400 truncate" title={entry.new_mac}>{entry.new_mac}</span>
                    </div>
                    <div className="flex items-center gap-1.5 min-w-0 text-black/45 dark:text-white/45">
                      <span className="truncate">{entry.old_vendor || '?'}</span>
                      <ArrowRight size={10} className="text-black/15 dark:text-white/15 flex-shrink-0" />
                      <span className="truncate">{entry.new_vendor || '?'}</span>
                    </div>
                    <span className="text-[#0891b2] truncate font-medium" title={entry.new_device}>{entry.new_device || '-'}</span>
                    <span className="text-black/30 dark:text-white/30" title={entry.detected_at}>{formatRelativeTime(entry.detected_at, zh)}</span>
                  </div>
                ))
              )}
            </div>

            <Pagination
              currentPage={macPage}
              totalItems={filtered.length}
              itemsPerPage={macPageSize}
              onPageChange={setMacPage}
              onItemsPerPageChange={(v) => { setMacPage(1); setMacPageSize(v); }}
              language={language}
            />
          </div>
        );
      })()}

      </>)}
      </div>
    </div>
  );
};

export default IPLocatorPage;
