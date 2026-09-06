import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Search, MapPin, ArrowRight, Loader2, Server, Monitor, Network, AlertCircle, ChevronDown, ChevronUp, Cable, Clock, RotateCcw, Activity, Wifi, Globe, Zap, CheckCircle2, XCircle, Minus, Database, RefreshCw, Filter, Download, X, ShieldAlert, Check, Play, FileText, Copy, Router, ExternalLink, Cpu, MemoryStick, Eye, Users, Sliders, Settings } from 'lucide-react';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { ActionButton } from '../components/ui/ActionIconButton';
import * as XLSX from 'xlsx';
import { formatMacAddress } from '../utils/resourceFormatters';
import { useSearchParams } from 'react-router-dom';

interface IPLocatorPageProps {
  language: string;
  t: (key: string) => string;
  mode?: 'diagnose-only' | 'toolbox' | 'nsot-only';
}

interface LocationEntry {
  switch_id: string;
  switch_name: string;
  port: string;
  vlan: string;
  vlan_source?: string;
  type: string;
  is_uplink: boolean;
  uplink_neighbor?: string;
  uplink_port?: string;
  note?: string;
}

interface TraceHop {
  switch_id?: string;
  switch_name?: string;
  port?: string;
  vlan?: string;
  type?: string;
  is_uplink?: boolean;
  is_aggregation?: boolean;
  is_trunk?: boolean;
  neighbor_name?: string;
  neighbor_port?: string;
  evidence?: string;
}

interface LocatorContext {
  address: {
    ip: string;
    type: string;
    prefix: string;
    prefix_length?: number | null;
    netmask: string;
    network_type: string;
    purpose: string;
    status: string;
    last_seen: string;
  };
  l2: {
    mac: string;
    vlan: string;
    vlan_name: string;
    vlan_source: string;
    switch_id: string;
    switch_name: string;
    port: string;
    description: string;
    admin_status: string;
    oper_status: string;
    mode: string;
    native_vlan: string;
    allowed_vlans: string;
    last_seen: string;
  };
  l3: {
    gateway: string;
    gateway_device: string;
    gateway_device_id?: string;
    gateway_interface: string;
    vrf: string;
    next_hop: string;
    route_source: string;
    route_interface: string;
    route_last_updated: string;
    upstream_devices?: Array<{ device: string; device_id?: string; port?: string; peer_port?: string }>;
    downstream_devices?: Array<{ device: string; device_id?: string; port?: string; peer_port?: string }>;
    adjacent_devices?: Array<{ device: string; device_id?: string; port?: string; peer_port?: string }>;
  };
  business: {
    hostname: string;
    asset_type: string;
    department: string;
    tenant: string;
    site: string;
    owner: string;
    criticality: string;
    description: string;
    config_backup_at: string;
    business_systems?: string[];
    business_level?: string;
    open_alerts: Array<{ id: string; severity: string; title: string; created_at: string; interface: string }>;
  };
  freshness: {
    endpoint_last_seen: string;
    arp_last_updated: string;
    mac_last_updated: string;
    interface_last_seen: string;
    collected_at: string;
  };
  path: Array<{ kind: string; label: string; detail: string }>;
}

interface LocateResult {
  target_ip: string;
  found: boolean;
  mac: string | null;
  mac_display: string | null;
  arp_source: { device_id: string; device: string; interface: string; vlan?: string } | null;
  locations: LocationEntry[];
  searched_devices: { arp: string[]; mac: string[]; lldp: string[] };
  cache?: {
    enabled: boolean;
    arp_cache_hit: boolean;
    ttl_seconds: number;
    force_refresh: boolean;
    cached_at: string | null;
    endpoint_cache_stale?: boolean;
    endpoint_cache_age_seconds?: number | null;
  };
  timestamp: string;
  errors: string[];
  trace_status?: string;
  trace_hops?: TraceHop[];
  context?: LocatorContext;
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

type TabMode = 'locate' | 'probe' | 'arp-table' | 'mac-changes' | 'diagnose' | 'nsot';
type NsotSubTab = 'endpoints' | 'inventory' | 'routes' | 'neighbors' | 'bgp_routes';

const PATH_KIND_LABELS: Record<string, [string, string]> = {
  ip: ['IP 地址', 'IP Address'],
  mac: ['MAC 地址', 'MAC Address'],
  access: ['接入设备', 'Access Device'],
  vlan: ['二层 VLAN', 'Layer 2 VLAN'],
  transit: ['中间设备', 'Transit Device'],
  gateway: ['网关设备', 'Gateway Device'],
  network: ['目标网段', 'Target Network'],
};

function formatPathKind(kind: string, zhLang: boolean): string {
  const labels = PATH_KIND_LABELS[kind] || [kind, kind];
  return labels[zhLang ? 0 : 1];
}

function formatExactTime(value: string, zhLang: boolean): string {
  if (!value) return zhLang ? '暂无时间' : 'No timestamp';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(zhLang ? 'zh-CN' : 'en-US', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date);
}

const FreshnessItem: React.FC<{ label: string; value: string; thresholdSeconds: number; zhLang: boolean }> = ({ label, value, thresholdSeconds, zhLang }) => {
  const parsed = value ? new Date(value).getTime() : NaN;
  const ageSeconds = Number.isNaN(parsed) ? null : Math.max(0, Math.round((Date.now() - parsed) / 1000));
  const status = ageSeconds === null
    ? (zhLang ? '未知' : 'Unknown')
    : ageSeconds <= thresholdSeconds
      ? (zhLang ? '较新' : 'Fresh')
      : (zhLang ? '较旧' : 'Stale');
  const statusClass = ageSeconds === null
    ? 'text-black/35 dark:text-white/35'
    : ageSeconds <= thresholdSeconds
      ? 'text-emerald-600 dark:text-emerald-400'
      : 'text-amber-600 dark:text-amber-400';

  return (
    <div className="rounded-lg border border-black/5 dark:border-white/10 bg-white/80 dark:bg-white/[0.04] px-3 py-2" title={value || (zhLang ? '该类数据尚未采集' : 'No observation yet')}>
      <div className="flex items-center gap-1.5 text-[10px] text-black/45 dark:text-white/45">
        <Clock size={10} />
        <span>{label}</span>
        <span className={`ml-auto font-medium ${statusClass}`}>{status}</span>
      </div>
      <div className="mt-1 text-[11px] font-medium text-black/70 dark:text-white/70">
        {value ? formatExactTime(value, zhLang) : (zhLang ? '暂无采集记录' : 'No observation')}
      </div>
      {value && <div className="mt-0.5 text-[10px] text-black/35 dark:text-white/35">{formatRelativeTime(value, zhLang)}</div>}
    </div>
  );
};

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
  vlan?: string;
  vlan_id?: number | null;
  vlan_source?: string;
  age_seconds?: number | null;
  freshness?: 'fresh' | 'stale' | 'unknown';
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

interface ArpSweepStatus {
  kind: 'success' | 'warning';
  message: string;
}

const LocatorContextCard: React.FC<{ title: string; icon: React.ComponentType<any>; children: React.ReactNode }> = ({ title, icon: Icon, children }) => (
  <div className="rounded-xl border border-black/5 dark:border-white/10 bg-white/70 dark:bg-white/[0.04] p-4">
    <div className="flex items-center gap-2 mb-3">
      <Icon size={14} className="text-[#0891b2]" />
      <p className="text-xs font-semibold text-[#164e63] dark:text-[var(--app-text)]">{title}</p>
    </div>
    <div className="space-y-2">{children}</div>
  </div>
);

const LocatorContextField: React.FC<{ label: string; value?: string | number | null; mono?: boolean; tone?: string }> = ({ label, value, mono, tone }) => (
  <div className="flex items-start justify-between gap-3 text-xs">
    <span className="text-black/40 dark:text-white/40 flex-shrink-0">{label}</span>
    <span className={`${mono ? 'font-mono' : ''} ${tone || 'text-black/70 dark:text-white/70'} text-right break-all`}>{value || '-'}</span>
  </div>
);

const ADDRESS_TYPE_LABELS: Record<string, [string, string]> = {
  management: ['管理网', 'Management'],
  transit: ['互联/传输网', 'Transit'],
  loopback: ['环回地址', 'Loopback'],
  user_access: ['用户接入网', 'User Access'],
  network_service: ['网络服务网', 'Network Service'],
  wan: ['广域网', 'WAN'],
  vpn: ['VPN 网络', 'VPN'],
  vip: ['虚拟服务地址', 'VIP'],
  server: ['服务器网', 'Server'],
  unclassified: ['未分类', 'Unclassified'],
  unknown: ['未知', 'Unknown'],
};

function formatAddressType(value: string, zhLang: boolean): string {
  const labels = ADDRESS_TYPE_LABELS[value] || [value, value];
  return labels[zhLang ? 0 : 1] || value;
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

const generateSequenceEvents = (result: any, lanes?: any[]) => {
  if (!result || !result.hops) return [];
  const events: any[] = [];
  const hops = result.hops;
  const proto = result.protocol || 'ICMP';
  const port = result.port || 80;
  
  const getMac = (ip: string, suffix: string) => {
    if (!ip) return `00:50:56:00:00:${suffix}`;
    const parts = ip.split('.');
    if (parts.length < 4) return `00:50:56:00:00:${suffix}`;
    const h3 = parseInt(parts[2] || '0').toString(16).padStart(2, '0');
    const h4 = parseInt(parts[3] || '0').toString(16).padStart(2, '0');
    return `00:50:56:ab:${h3}:${h4}`;
  };

  const srcMac = getMac(result.source_ip, '01');
  const targetMac = getMac(result.target_ip, 'ff');
  const probeStep = (result.steps || []).find((step: any) => /^P8\.(?!5\.)/.test(String(step?.name || '')));
  const probeText = `${probeStep?.message || ''}\n${probeStep?.log || ''}`;
  const probeFailed = Boolean(probeStep && (
    probeStep.status !== 'success' ||
    /(?:100(?:\.0+)?%\s*(?:packet\s+loss|loss)|丢包率\s*100(?:\.0+)?%|request\s*time\s*out|request\s*timeout|timeout|未收到响应|探测失败|验证失败)/i.test(probeText)
  ));

  const getColIndex = (id: string, defaultVal: number) => {
    if (lanes) {
      const idx = lanes.findIndex(l => l.id === id);
      if (idx !== -1) return idx;
    }
    return defaultVal;
  };

  const targetIdx = lanes ? (lanes.length - 1) : (hops.length + 1);
  const lastHopIsTarget = hops.length > 0 && hops[hops.length - 1].ip === result.target_ip;

  hops.forEach((hop: any, idx: number) => {
    // 如果最后一跳的 IP 等于目标 IP，我们跳过它作为“中间跳”的绘制，完全交给最后的端口探测处理
    if (lastHopIsTarget && idx === hops.length - 1) {
      return;
    }

    const hopIdx = getColIndex(`hop-${idx}`, idx + 1);
    const ttl = idx + 1;
    
    const isBlocked = hop.status === 'blocked';
    const isTimeout = hop.status === 'timeout';
    
    let infoStr = proto === 'TCP' ? `TCP SYN (TTL=${ttl}, DstPort=${port})` : `ICMP Echo Request (TTL=${ttl})`;
    if (isBlocked) {
      infoStr += ` [Blocked by Firewall/ACL]`;
    } else if (isTimeout) {
      infoStr += ` [Request Timeout]`;
    }

    events.push({
      id: `probe-${idx}`,
      type: 'probe',
      protocol: proto,
      srcIp: result.source_ip,
      dstIp: result.target_ip,
      srcMac,
      dstMac: getMac(hop.ip, 'aa'),
      ttl,
      l4Name: proto,
      info: infoStr,
      startCol: 0,
      endCol: hopIdx,
      status: hop.status,
      direction: 'forward',
      label: proto === 'TCP' ? `Probe SYN (TTL=${ttl})` : `Probe Ping (TTL=${ttl})`,
      cpu_usage: hop.cpu_usage,
      memory_usage: hop.memory_usage,
      deviceName: hop.device_name
    });

    if (!isBlocked && !isTimeout && !probeFailed) {
      const latencyStr = hop.rtt_ms && hop.rtt_ms.length > 0 ? ` (${Math.round(hop.rtt_ms[0])}ms)` : '';
      events.push({
        id: `response-${idx}`,
        type: 'response',
        protocol: 'ICMP',
        srcIp: hop.ip,
        dstIp: result.source_ip,
        srcMac: getMac(hop.ip, 'aa'),
        dstMac: srcMac,
        ttl: 64,
        l4Name: 'ICMP',
        info: `ICMP Time Exceeded (TTL expired in transit)`,
        startCol: 0,
        endCol: hopIdx,
        status: 'active',
        direction: 'backward',
        label: `ICMP TTL Expired${latencyStr}`,
        cpu_usage: hop.cpu_usage,
        memory_usage: hop.memory_usage,
        deviceName: hop.device_name
      });
    }
  });

  const isReachable = Boolean(result.report && result.report.conclusion === 'reachable' && !probeFailed);
  const isPortProbeFailed = Boolean(probeFailed || (result.report && result.report.conclusion === 'interrupted'));
  const isTimeout = isPortProbeFailed && (
    proto === 'ICMP' ||
    (result.report.reason || '').toLowerCase().includes('timeout') ||
    (result.report.reason || '').toLowerCase().includes('超时') ||
    (result.report.reason || '').toLowerCase().includes('no response') ||
    /request\s*time\s*out|request\s*timeout|timeout|未收到响应/i.test(probeText)
  );
  const isRefused = isPortProbeFailed && !isTimeout;

  if (isReachable || isPortProbeFailed) {
    const finalTtl = hops.length + 1;
    const finalHop = hops.length > 0 ? hops[hops.length - 1] : null;
    const finalCpu = finalHop ? finalHop.cpu_usage : undefined;
    const finalMem = finalHop ? finalHop.memory_usage : undefined;
    const finalDevName = finalHop ? finalHop.device_name : undefined;
    
    // final-probe
    events.push({
      id: 'final-probe',
      type: 'probe',
      protocol: proto,
      srcIp: result.source_ip,
      dstIp: result.target_ip,
      srcMac,
      dstMac: targetMac,
      ttl: finalTtl,
      l4Name: proto,
      info: isTimeout 
        ? (proto === 'TCP' ? `TCP SYN (DstPort=${port}) [No Response/Timeout]` : `ICMP Echo Request [Timeout]`)
        : (proto === 'TCP' ? `TCP SYN (DstPort=${port})` : `ICMP Echo Request`),
      startCol: 0,
      endCol: targetIdx,
      status: isTimeout ? 'timeout' : 'active',
      direction: 'forward',
      label: isTimeout
        ? (proto === 'TCP' ? `TCP SYN (Timeout)` : `ICMP Request (Timeout)`)
        : (proto === 'TCP' ? `TCP SYN (Port ${port})` : `ICMP Echo Request`),
      cpu_usage: finalCpu,
      memory_usage: finalMem,
      deviceName: finalDevName
    });

    // final-response (只有在未超时的情况下才会有回包)
    if (!isTimeout) {
      const latencyStr = finalHop && finalHop.rtt_ms && finalHop.rtt_ms.length > 0 ? ` (${Math.round(finalHop.rtt_ms[0])}ms)` : '';
      events.push({
        id: 'final-response',
        type: 'response',
        protocol: proto,
        srcIp: result.target_ip,
        dstIp: result.source_ip,
        srcMac: targetMac,
        dstMac: srcMac,
        ttl: 64,
        l4Name: proto,
        info: isReachable
          ? (proto === 'TCP' ? `TCP SYN-ACK (Port ${port} Open / Established)` : `ICMP Echo Reply`)
          : (proto === 'TCP' ? `TCP RST (Connection Refused / Closed)` : `ICMP Destination Unreachable`),
        startCol: 0,
        endCol: targetIdx,
        status: isReachable ? 'active' : 'refused',
        direction: 'backward',
        label: isReachable
          ? (proto === 'TCP' ? `TCP SYN-ACK (Reachable)${latencyStr}` : `ICMP Echo Reply${latencyStr}`)
          : (proto === 'TCP' ? `TCP RST (Closed)${latencyStr}` : `Destination Unreachable${latencyStr}`),
        cpu_usage: finalCpu,
        memory_usage: finalMem,
        deviceName: finalDevName
      });
    }
  }

  return events;
};

const reconcileDiagnosticProbeResult = (raw: any) => {
  if (!raw) return raw;
  const steps = Array.isArray(raw.steps) ? raw.steps : [];
  const probeStep = steps.find((step: any) => /^P8\.(?!5\.)/.test(String(step?.name || '')));
  if (!probeStep) return raw;

  const probeText = `${probeStep.message || ''}\n${probeStep.log || ''}`;
  const packetLoss100 = /(?:100(?:\.0+)?%\s*(?:packet\s+loss|loss)|丢包率\s*100(?:\.0+)?%)/i.test(probeText);
  const timeoutText = /request\s*time\s*out|request\s*timeout|timeout|未收到响应|探测失败|验证失败/i.test(probeText);
  const probeFailed = probeStep.status !== 'success' || packetLoss100 || timeoutText;
  if (!probeFailed) return raw;

  const targetIp = String(raw.target_ip || '').trim();
  const hops = (raw.hops || []).map((hop: any) => {
    if (String(hop?.ip || '').trim() !== targetIp) return hop;
    return {
      ...hop,
      status: 'timeout',
      detail: 'P8 当前探测未收到响应；控制平面路径或历史 ARP/MAC 记录不代表目标当前可达。',
    };
  });
  const report = {
    ...(raw.report || {}),
    conclusion: 'interrupted',
    interrupted_at: raw.report?.interrupted_at || '目标主机/策略层',
    reason: 'P8 当前源设备探测失败，目标端未返回响应；不能依据历史路由或 ARP/MAC 记录判定路径可达。',
    impact: `${raw.protocol || 'ICMP'} 探测不可达`,
    evidence: [
      ...(Array.isArray(raw.report?.evidence) ? raw.report.evidence : []),
      'P8 当前探测失败，已覆盖历史控制面可达结论',
    ],
  };
  return { ...raw, hops, report };
};

const IPLocatorPage: React.FC<IPLocatorPageProps> = ({ language, t, mode }) => {
  const zh = language === 'zh';
  const token = localStorage.getItem('netops_token') || '';
  const [searchParams] = useSearchParams();
  const requestedIp = searchParams.get('ip')?.trim() || '';
  const autoLocateIpRef = useRef('');
  const [activeTab, setActiveTab] = useState<TabMode>(mode === 'diagnose-only' ? 'diagnose' : mode === 'nsot-only' ? 'nsot' : 'locate');

  useEffect(() => {
    setActiveTab(mode === 'diagnose-only' ? 'diagnose' : mode === 'nsot-only' ? 'nsot' : 'locate');
  }, [mode]);

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
  const [probeTests, setProbeTests] = useState<Set<string>>(new Set(['ping']));
  const [devices, setDevices] = useState<{ id: number; hostname: string; ip_address: string; platform?: string; cpu_usage?: number; memory_usage?: number; status?: string; model?: string; vendor?: string; role?: string; device_category?: string }[]>([]);
  const [allDevices, setAllDevices] = useState<{ id: number; hostname: string; ip_address: string; platform?: string; cpu_usage?: number; memory_usage?: number; status?: string; model?: string; vendor?: string; role?: string; device_category?: string }[]>([]);
  const [sourceDeviceId, setSourceDeviceId] = useState<number | null>(null);

  // ── CMDB Autocomplete state ──
  const [showSourceDropdown, setShowSourceDropdown] = useState(false);
  const [showTargetDropdown, setShowTargetDropdown] = useState(false);
  const sourceDropdownRef = useRef<HTMLDivElement>(null);
  const targetDropdownRef = useRef<HTMLDivElement>(null);

  // ── Hop popover state ──
  const [activeHopIdx, setActiveHopIdx] = useState<number | null>(null);
  const [activeSubHopIdx, setActiveSubHopIdx] = useState<number>(0);
  const [viewMode, setViewMode] = useState<'topology' | 'sequence'>('topology');
  const [cmdbFilterQuery, setCmdbFilterQuery] = useState('');
  const hopPopoverRef = useRef<HTMLDivElement>(null);

  // ── ARP Table state ──
  const [arpTable, setArpTable] = useState<ArpTableData | null>(null);
  const [arpLoading, setArpLoading] = useState(false);
  const [arpError, setArpError] = useState('');
  const [arpFilter, setArpFilter] = useState('');
  const [arpSweeping, setArpSweeping] = useState(false);
  const [arpSweepStatus, setArpSweepStatus] = useState<ArpSweepStatus | null>(null);
  const [arpPage, setArpPage] = useState(1);
  const [arpPageSize, setArpPageSize] = useState(10);

  // ── MAC Changes state ──
  const [macChanges, setMacChanges] = useState<MacChangesData | null>(null);
  const [macChangesLoading, setMacChangesLoading] = useState(false);
  const [macChangesError, setMacChangesError] = useState('');
  const [macFilter, setMacFilter] = useState('');
  const [macPage, setMacPage] = useState(1);
  const [macPageSize, setMacPageSize] = useState(10);

  // ── NSOT (Network Source of Truth) state ──
  const [nsotSubTab, setNsotSubTab] = useState<NsotSubTab>('endpoints');
  const [nsotEndpoints, setNsotEndpoints] = useState<any>(null);
  const [nsotInventory, setNsotInventory] = useState<any>(null);
  const [nsotRoutes, setNsotRoutes] = useState<any>(null);
  const [nsotNeighbors, setNsotNeighbors] = useState<any>(null);
  const [nsotBgpRoutes, setNsotBgpRoutes] = useState<any>(null);
  const [nsotLoading, setNsotLoading] = useState(false);
  const [nsotError, setNsotError] = useState('');
  const [nsotFilter, setNsotFilter] = useState('');
  const [nsotSweeping, setNsotSweeping] = useState(false);
  const [nsotSweepSuccessMsg, setNsotSweepSuccessMsg] = useState('');
  const [nsotPage, setNsotPage] = useState(1);
  const [nsotPageSize, setNsotPageSize] = useState(10);

  // Advanced Search/Filter States
  const [nsotShowAdvanced, setNsotShowAdvanced] = useState(false);

  // ── NSOT Collection Policy Modal state ──
  const [nsotPolicyModalOpen, setNsotPolicyModalOpen] = useState(false);
  const [nsotPlans, setNsotPlans] = useState<any[]>([]);
  const [nsotSelectedPlanDeviceId, setNsotSelectedPlanDeviceId] = useState('');
  const [nsotPlansLoading, setNsotPlansLoading] = useState(false);
  const [nsotPlanMessage, setNsotPlanMessage] = useState('');
  const [nsotPlanSearch, setNsotPlanSearch] = useState('');

  const fetchNsotCollectionPlans = useCallback(async () => {
    setNsotPlansLoading(true);
    try {
      const resp = await fetch('/api/collection-plans/devices', {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!resp.ok) return;
      const json = await resp.json();
      const rows = Array.isArray(json.data) ? json.data : [];
      setNsotPlans(rows);
      setNsotSelectedPlanDeviceId((curr) => curr || rows[0]?.device?.id || '');
    } catch {
      setNsotPlanMessage(zh ? '采集能力策略加载失败' : 'Failed to load collection policies');
    } finally {
      setNsotPlansLoading(false);
    }
  }, [token, zh]);

  const updateNsotCollectionPlan = useCallback(async (collector: string, enabled: boolean) => {
    const current = nsotPlans.find((row) => row.device?.id === nsotSelectedPlanDeviceId);
    if (!current) return;
    const overrides = { ...(current.plan?.overrides || {}), [collector]: enabled };
    try {
      const resp = await fetch(`/api/collection-plans/devices/${nsotSelectedPlanDeviceId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ policy: { collectors: overrides } }),
      });
      const json = await resp.json();
      if (!resp.ok) throw new Error(json.detail || 'Update failed');
      setNsotPlanMessage(zh ? '采集能力策略已更新' : 'Collection policy updated');
      fetchNsotCollectionPlans();
    } catch {
      setNsotPlanMessage(zh ? '采集能力策略更新失败' : 'Failed to update collection policy');
    }
  }, [fetchNsotCollectionPlans, nsotPlans, nsotSelectedPlanDeviceId, token, zh]);

  const resetNsotCollectionPlan = useCallback(async () => {
    if (!nsotSelectedPlanDeviceId) return;
    try {
      const resp = await fetch(`/api/collection-plans/devices/${nsotSelectedPlanDeviceId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error('Reset failed');
      setNsotPlanMessage(zh ? '已恢复角色默认策略' : 'Reset to role default policy');
      fetchNsotCollectionPlans();
    } catch {
      setNsotPlanMessage(zh ? '恢复默认策略失败' : 'Failed to reset policy');
    }
  }, [fetchNsotCollectionPlans, nsotSelectedPlanDeviceId, token, zh]);
  // Endpoints tab filters
  const [epFilterIp, setEpFilterIp] = useState('');
  const [epFilterMac, setEpFilterMac] = useState('');
  const [epFilterSwitch, setEpFilterSwitch] = useState('');
  const [epFilterVlan, setEpFilterVlan] = useState('');
  const [epFilterStatus, setEpFilterStatus] = useState('all'); // all, active, inactive
  const [epFilterSource, setEpFilterSource] = useState('all');
  // Inventory tab filters
  const [invFilterIp, setInvFilterIp] = useState('');
  const [invFilterDevice, setInvFilterDevice] = useState('');
  const [invFilterType, setInvFilterType] = useState('all');
  // Routes tab filters
  const [routeFilterDevice, setRouteFilterDevice] = useState('');
  const [routeFilterPrefix, setRouteFilterPrefix] = useState('');
  const [routeFilterNextHop, setRouteFilterNextHop] = useState('');
  const [routeFilterProtocol, setRouteFilterProtocol] = useState('all');
  // Neighbors tab filters
  const [neighFilterDevice, setNeighFilterDevice] = useState('');
  const [neighFilterProtocol, setNeighFilterProtocol] = useState('all');
  // BGP routes filters
  const [bgpFilterDevice, setBgpFilterDevice] = useState('');
  const [bgpFilterVrf, setBgpFilterVrf] = useState('');
  const [bgpFilterPrefix, setBgpFilterPrefix] = useState('');
  const [bgpFilterNextHop, setBgpFilterNextHop] = useState('');
  const [bgpFilterStatus, setBgpFilterStatus] = useState('all');

  const resetNsotAdvancedFilters = useCallback(() => {
    setEpFilterIp('');
    setEpFilterMac('');
    setEpFilterSwitch('');
    setEpFilterVlan('');
    setEpFilterStatus('all');
    setEpFilterSource('all');
    setInvFilterIp('');
    setInvFilterDevice('');
    setInvFilterType('all');
    setRouteFilterDevice('');
    setRouteFilterPrefix('');
    setRouteFilterNextHop('');
    setRouteFilterProtocol('all');
    setNeighFilterDevice('');
    setNeighFilterProtocol('all');
    setBgpFilterDevice('');
    setBgpFilterVrf('');
    setBgpFilterPrefix('');
    setBgpFilterNextHop('');
    setBgpFilterStatus('all');
  }, []);

  // ── Path Diagnose state ──
  const [diagHistory, setDiagHistory] = useState<{
    source_ip: string;
    target_ip: string;
    protocol: string;
    port: string;
    vrf: string;
    conclusion: string;
    timestamp: string;
  }[]>(() => {
    try {
      const stored = localStorage.getItem('nexora_npa_history');
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  const [diagSourceIp, setDiagSourceIp] = useState('');
  const [diagTargetIp, setDiagTargetIp] = useState('');
  const [diagPort, setDiagPort] = useState('443');
  const [diagProtocol, setDiagProtocol] = useState('TCP');
  const [diagVrf, setDiagVrf] = useState('');
  const [diagLoading, setDiagLoading] = useState(false);
  const [diagResult, setDiagResult] = useState<any>(null);
  const [diagError, setDiagError] = useState('');
  const [diagCurrentStep, setDiagCurrentStep] = useState<number>(-1);
  const [copiedCmd, setCopiedCmd] = useState(false);
  const [selectedStepIdx, setSelectedStepIdx] = useState<number | null>(null);


  const getStepNames = useCallback(() => {
    const p8Name = diagProtocol === 'ICMP' ? "P8. ICMP 验证 (ICMP Validation)" : `P8. ${diagProtocol} 验证 (${diagProtocol} Validation)`;
    return [
      "P0. VRF 发现 (VRF Discovery)",
      "P1. 资产发现 (Asset Discovery)",
      "P2. 目标分类 (Target Classification)",
      "P3. ARP 分析 (ARP Analysis)",
      "P4. MAC 定位 (MAC Analysis)",
      "P4.5. 实时接口链路验证 (Live Interface Validation)",
      "P5. 路由递归 (Route Recursion)",
      "P5.5. FIB 验证 (FIB Verification)",
      "P6. 策略分析 (Policy Analysis)",
      "P6.5. BGP 分析 (BGP Analysis)",
      "P7. Overlay 分析 (Overlay Analysis)",
      "P7.5. HA 分析 (HA Analysis)",
      p8Name,
      "P8.5. 性能分析 (Performance Analysis)",
      "P9. AI 根因推导 (AI Root Cause Engine)",
      "P9.5. 证据一致性检查 (Evidence Consistency)",
      "P10. 智能报告 (Smart Report)"
    ];
  }, [diagProtocol]);

  const doDiagnose = useCallback(async (
    overrideSrc?: string,
    overrideTgt?: string,
    overrideProto?: string,
    overridePort?: string,
    overrideVrf?: string
  ) => {
    const srcIp = (overrideSrc !== undefined ? overrideSrc : diagSourceIp).trim();
    const tgtIp = (overrideTgt !== undefined ? overrideTgt : diagTargetIp).trim();
    const proto = overrideProto !== undefined ? overrideProto : diagProtocol;
    const portStr = overridePort !== undefined ? overridePort : diagPort;
    const vrf = overrideVrf !== undefined ? overrideVrf : diagVrf;

    if (!srcIp || !tgtIp) return;
    setDiagLoading(true);
    setDiagError('');
    setDiagResult(null);
    setDiagCurrentStep(0);
    setSelectedStepIdx(null);

    // Sync input fields if overridden
    if (overrideSrc !== undefined) setDiagSourceIp(overrideSrc);
    if (overrideTgt !== undefined) setDiagTargetIp(overrideTgt);
    if (overrideProto !== undefined) setDiagProtocol(overrideProto);
    if (overridePort !== undefined) setDiagPort(overrideProto === 'ICMP' ? '' : overridePort);
    if (overrideVrf !== undefined) setDiagVrf(overrideVrf);

    const stepNames = getStepNames();
    
    let currentStepIdx = 0;
    const interval = setInterval(() => {
      // 自动前进到 P5 路由递归。之后需要等待真实的 API 结果。
      if (currentStepIdx < 5) {
        currentStepIdx += 1;
        setDiagCurrentStep(currentStepIdx);
      } else {
        clearInterval(interval);
      }
    }, 500);

    try {
      const resp = await fetch('/api/ip-locator/diagnose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({
          source_ip: srcIp,
          target_ip: tgtIp,
          port: parseInt(portStr, 10) || 443,
          protocol: proto,
          vrf: vrf.trim() || undefined,
        }),
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      const data = reconcileDiagnosticProbeResult(await resp.json());
      
      clearInterval(interval);
      setDiagCurrentStep(stepNames.length - 1);
      setDiagResult(data);

      // Save to local diagnostic history
      setDiagHistory(prev => {
        const newEntry = {
          source_ip: srcIp,
          target_ip: tgtIp,
          protocol: proto,
          port: proto === 'ICMP' ? 'N/A' : portStr,
          vrf: vrf.trim(),
          conclusion: data.report?.conclusion || 'unknown',
          timestamp: new Date().toISOString(),
        };
        const filtered = prev.filter(h => !(h.source_ip === srcIp && h.target_ip === tgtIp && h.protocol === proto && h.port === newEntry.port && h.vrf === newEntry.vrf));
        const updated = [newEntry, ...filtered].slice(0, 10);
        try {
          localStorage.setItem('nexora_npa_history', JSON.stringify(updated));
        } catch { /* noop */ }
        return updated;
      });
    } catch (e: unknown) {
      clearInterval(interval);
      setDiagError(e instanceof Error ? e.message : String(e));
    } finally {
      setDiagLoading(false);
    }
  }, [diagSourceIp, diagTargetIp, diagPort, diagProtocol, diagVrf, token, getStepNames]);

  const exportToMarkdown = (res: any) => {
    if (!res || !res.report) return;
    const rep = res.report;
    const stepsText = res.steps ? res.steps.map((s: any) => {
      let mark = '[-]';
      if (s.status === 'success') mark = '[x]';
      else if (s.status === 'failed') mark = '[!]';
      else if (s.status === 'warning') mark = '[?]';
      return `- ${mark} **${s.name}**: ${s.message || s.desc || ''}`;
    }).join('\n') : '';

    const evidenceText = rep.evidence && rep.evidence.length > 0
      ? rep.evidence.map((ev: string) => `- ⚠️ ${ev}`).join('\n')
      : (zh ? '无' : 'None');

    const markdown = `# Smart NPA 智能路径诊断报告

- **诊断时间**: ${res.timestamp?.replace('T', ' ').slice(0, 19) || ''}
- **源 IP 地址**: ${res.source_ip || ''}
- **目标 IP 地址**: ${res.target_ip || ''}
- **协议/端口**: ${res.protocol || 'TCP'}${res.protocol !== 'ICMP' ? `:${res.port || '443'}` : ''}
- **诊断结论**: ${rep.conclusion === 'interrupted' ? (zh ? '检测到阻断' : 'Blocked') : (zh ? '路径可达' : 'Reachable')}
- **AI 置信度**: ${rep.confidence || 'N/A'}

---

## 🛠 诊断验证清单 (AI Checklist)

${stepsText}

---

## ⚠️ 关键根因证据 (Key Evidences)

${evidenceText}

---

## 📄 诊断结论与分析

### 1. 结论详情
${rep.conclusion === 'interrupted' ? (zh ? `路径中断于设备：${rep.interrupted_at}` : `Path blocked at device: ${rep.interrupted_at}`) : (zh ? '全路径网络连通性正常' : 'End-to-end connectivity is normal')}

### 2. 根因分析
${rep.reason || ''}

### 3. 业务影响范围
${rep.impact || ''}

### 4. 修复与优化建议
${rep.suggestion || ''}

${rep.repair_commands ? `---

## 💻 修复命令 (Recommended CLI Fixes)

\`\`\`
${rep.repair_commands}
\`\`\`
` : ''}
`;

    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `NPA_Report_${res.target_ip || 'npa'}_${new Date().toISOString().slice(0, 10)}.md`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };


  // 加载设备列表用于设备侧探测 (使用 mode=light 和 page_size=500 防止加载过慢)
  useEffect(() => {
    fetch('/api/devices?mode=light&page_size=500', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : { items: [] })
      .then(data => {
        const list = Array.isArray(data) ? data : data?.items || data?.data || [];
        setAllDevices(list);
        setDevices(list.filter((d: any) => d.status === 'online' && d.username));
      })
      .catch(() => {});
  }, [token]);

  // ── CMDB autocomplete helpers ──
  const isServerPlatform = useCallback((platform: string) => {
    const p = (platform || '').toLowerCase();
    return ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'rocky', 'alma', 'server', 'windows'].some(k => p.includes(k));
  }, []);

  const filterCmdbDevices = useCallback((query: string) => {
    const q = query.trim().toLowerCase();
    if (!q) return allDevices.slice(0, 12);
    return allDevices.filter(d =>
      (d.hostname || '').toLowerCase().includes(q) ||
      (d.ip_address || '').toLowerCase().includes(q) ||
      (d.model || '').toLowerCase().includes(q)
    ).slice(0, 12);
  }, [allDevices]);

  const sourceMatches = useMemo(() => filterCmdbDevices(diagSourceIp), [filterCmdbDevices, diagSourceIp]);
  const targetMatches = useMemo(() => filterCmdbDevices(diagTargetIp), [filterCmdbDevices, diagTargetIp]);

  const quickSelectDevices = useMemo(() => {
    const q = cmdbFilterQuery.toLowerCase().trim();
    if (!q) return allDevices.slice(0, 6);
    return allDevices.filter(d => 
      (d.hostname || '').toLowerCase().includes(q) || 
      (d.ip_address || '').toLowerCase().includes(q) ||
      (d.model || '').toLowerCase().includes(q)
    ).slice(0, 10);
  }, [allDevices, cmdbFilterQuery]);

  // Click-outside handler for dropdowns and escape key for modal
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (sourceDropdownRef.current && !sourceDropdownRef.current.contains(e.target as Node)) {
        setShowSourceDropdown(false);
      }
      if (targetDropdownRef.current && !targetDropdownRef.current.contains(e.target as Node)) {
        setShowTargetDropdown(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setActiveHopIdx(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  // Find CMDB device by IP for hop popover
  const findDeviceByIp = useCallback((ip: string) => {
    return allDevices.find(d => d.ip_address === ip) || null;
  }, [allDevices]);

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
    setArpError('');
    setArpSweepStatus(null);
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
      setArpSweepStatus({
        kind: Number(data?.sweep?.collected_entries || 0) > 0 ? 'success' : 'warning',
        message: data.message || (zh ? 'ARP 采集已完成。' : 'ARP collection completed.'),
      });
    } catch (e: any) {
      setArpError(e.message || (zh ? 'ARP 采集失败' : 'ARP collection failed'));
      await fetchArpTable();
    } finally {
      setArpSweeping(false);
    }
  }, [token, fetchArpTable, zh]);

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

  // ── NSOT fetch ──
  const fetchNsotData = useCallback(async () => {
    setNsotLoading(true);
    setNsotError('');
    try {
      const [epResp, invResp, rcResp, rnResp, bgpResp] = await Promise.all([
        fetch('/api/ip-locator/network-endpoints', { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/ip-locator/ip-inventory', { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/ip-locator/route-cache', { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/ip-locator/routing-neighbors', { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/ip-locator/bgp-routes', { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (!epResp.ok || !invResp.ok || !rcResp.ok || !rnResp.ok || !bgpResp.ok) throw new Error('Failed to fetch NSOT data');
      const [ep, inv, rc, rn, bgp] = await Promise.all([
        epResp.json(),
        invResp.json(),
        rcResp.json(),
        rnResp.json(),
        bgpResp.json()
      ]);
      setNsotEndpoints(ep);
      setNsotInventory(inv);
      setNsotRoutes(rc);
      setNsotNeighbors(rn);
      setNsotBgpRoutes(bgp);
    } catch (e: any) {
      setNsotError(e.message || 'Failed to load NSOT data');
    } finally {
      setNsotLoading(false);
    }
  }, [token]);

  const handleNsotSweep = useCallback(async () => {
    setNsotSweeping(true);
    setNsotError('');
    setNsotSweepSuccessMsg('');
    try {
      const resp = await fetch('/api/ip-locator/nsot-sweep', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      setNsotSweepSuccessMsg(zh ? '数据采集任务已在后台启动，同步过程可能需要 1~2 分钟，请稍后刷新查看。' : 'Data collection task started in the background. It may take 1-2 minutes, please refresh later.');
    } catch (e: any) {
      setNsotError(e.message || 'Failed to trigger NSOT sweep');
    } finally {
      setNsotSweeping(false);
    }
  }, [token, zh]);

  useEffect(() => {
    if (activeTab === 'nsot' && !nsotEndpoints && !nsotLoading) {
      fetchNsotData();
    }
  }, [activeTab, nsotEndpoints, nsotLoading, fetchNsotData]);

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
        mac: formatMacAddress(data.mac_display || '-'),
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

  useEffect(() => {
    if (mode === 'diagnose-only' || mode === 'nsot-only' || !requestedIp || autoLocateIpRef.current === requestedIp) {
      return;
    }
    autoLocateIpRef.current = requestedIp;
    setActiveTab('locate');
    void doLocate(requestedIp);
  }, [doLocate, mode, requestedIp]);

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
  const locatorContext = result?.context;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={mode === 'diagnose-only' ? ShieldAlert : mode === 'nsot-only' ? Database : MapPin}
        title={mode === 'diagnose-only' ? (zh ? 'NPA 智能路径诊断' : 'NPA Path Diagnostics') : mode === 'nsot-only' ? (zh ? '网络事实库' : 'Network Source of Truth') : (zh ? 'IP 定位' : 'IP Locator')}
        subtitle={mode === 'diagnose-only' ? (zh ? '网络协议与路径全链条故障排查与一键式诊断' : 'End-to-end network protocol and path diagnostics') : mode === 'nsot-only' ? (zh ? '全网终端事实库、IP 资产明细与路由缓存离线数据库' : 'IP endpoints, inventory assets, and route cache database') : (zh ? 'IP 地址定位 · 连通性探测 · 全链路诊断' : 'IP Locate · Connectivity Probe · Full-path Diagnostics')}
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-5">
      {/* ── Tab Bar ── */}
      {mode !== 'diagnose-only' && mode !== 'nsot-only' && (
        <div className="flex gap-1 bg-black/[0.03] dark:bg-white/[0.04] rounded-xl p-1 w-fit">
          {mode !== 'toolbox' && (
            <button
              onClick={() => setActiveTab('diagnose')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${activeTab === 'diagnose' ? 'bg-white dark:bg-white/[0.08] text-[#164e63] dark:text-[var(--app-text)] shadow-sm' : 'text-black/40 dark:text-white/40 hover:text-black/60 dark:hover:text-white/60'}`}
            >
              <ShieldAlert size={14} className="text-rose-500" />
              {zh ? 'NPA 智能路径诊断' : 'NPA Path Diagnostics'}
            </button>
          )}
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
      )}

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
          {result.cache?.endpoint_cache_stale && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
              {zh
                ? `历史端点缓存已超过 ${Math.round((result.cache.endpoint_cache_age_seconds || 0) / 60)} 分钟，系统已跳过该缓存并重新查询设备。`
                : `The endpoint cache is ${Math.round((result.cache.endpoint_cache_age_seconds || 0) / 60)} minutes old; it was skipped and devices were queried again.`}
            </div>
          )}
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
                      <p className="text-base font-bold text-[#164e63] dark:text-[var(--app-text)] font-mono">{formatMacAddress(result.mac_display)}</p>
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
                            {loc.vlan && <span title={loc.vlan_source || 'unknown'} className="text-[10px] bg-cyan-50 dark:bg-cyan-500/10 text-cyan-700 dark:text-cyan-400 rounded px-1.5 py-0.5 font-medium">VLAN {loc.vlan}</span>}
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
          ) : result.trace_status === 'incomplete' ? (
            <div className="bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 rounded-2xl px-5 py-4">
              <div className="flex items-start gap-3">
                <AlertCircle size={18} className="text-amber-500 mt-0.5 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">{zh ? '链路追踪未完成' : 'Path Trace Incomplete'}</p>
                  <p className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
                    {zh ? '已从 ARP 获取 MAC，但当前路径证据不足，系统未把中间接口判定为主机接入口。' : 'The MAC was resolved from ARP, but the path evidence is incomplete, so an intermediate interface is not marked as a host port.'}
                  </p>
                  {result.errors?.map((err, i) => (
                    <p key={i} className="text-xs text-amber-600 dark:text-amber-400 mt-1">{err}</p>
                  ))}
                  {(result.trace_hops?.length ?? 0) > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-amber-800 dark:text-amber-300">
                      {result.trace_hops?.map((hop, i) => (
                        <React.Fragment key={`${hop.switch_id || hop.switch_name}-${hop.port}-${i}`}>
                          {i > 0 && <ArrowRight size={11} className="text-amber-400" />}
                          <span className="rounded bg-white/70 dark:bg-white/10 px-2 py-1 font-mono">
                            {hop.switch_name || hop.switch_id || '-'}:{hop.port || '-'}
                            {hop.is_aggregation ? ' · LAG' : hop.is_trunk ? ' · Trunk' : ''}
                          </span>
                        </React.Fragment>
                      ))}
                    </div>
                  )}
                </div>
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
                      {zh ? `MAC 地址 ${formatMacAddress(result.mac_display)} 已从 ARP 表获取，但未在任何交换机 MAC 表中匹配到端口` : `MAC ${formatMacAddress(result.mac_display)} resolved from ARP but not found in any switch MAC table`}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : null}

          {locatorContext && (
            <div className="rounded-2xl border border-black/5 dark:border-white/10 bg-slate-50/70 dark:bg-white/[0.025] p-4 space-y-4">
              <div className="flex items-center gap-2">
                <Network size={15} className="text-[#0891b2]" />
                <p className="text-sm font-semibold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '定位上下文' : 'Locator Context'}</p>
                <span className="text-[10px] text-black/35 dark:text-white/35 ml-auto">
                  {zh ? '查询时间' : 'Query time'} · {formatExactTime(locatorContext.freshness.collected_at, zh)}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                <LocatorContextCard title={zh ? '基础信息' : 'Address'} icon={Globe}>
                  <LocatorContextField label="IP" value={locatorContext.address.ip} mono />
                   <LocatorContextField label={zh ? '地址类型' : 'Type'} value={formatAddressType(locatorContext.address.type || locatorContext.address.network_type, zh)} />
                  <LocatorContextField label={zh ? '所属网段' : 'Prefix'} value={locatorContext.address.prefix} mono />
                  <LocatorContextField label={zh ? '掩码' : 'Netmask'} value={locatorContext.address.netmask} mono />
                  <LocatorContextField label={zh ? '网段用途' : 'Purpose'} value={locatorContext.address.purpose || locatorContext.address.network_type} />
                  <LocatorContextField label={zh ? '状态' : 'Status'} value={locatorContext.address.status} tone={locatorContext.address.status === 'active' ? 'text-emerald-600' : undefined} />
                </LocatorContextCard>

                <LocatorContextCard title={zh ? '二层定位' : 'Layer 2'} icon={Cable}>
                  <LocatorContextField label="MAC" value={formatMacAddress(locatorContext.l2.mac || result.mac_display)} mono />
                  <LocatorContextField label="VLAN" value={locatorContext.l2.vlan ? `${locatorContext.l2.vlan}${locatorContext.l2.vlan_name ? ` · ${locatorContext.l2.vlan_name}` : ''}` : ''} mono />
                  <LocatorContextField label={zh ? 'VLAN 来源' : 'VLAN Source'} value={locatorContext.l2.vlan_source} />
                  <LocatorContextField label={zh ? '接入设备' : 'Switch'} value={locatorContext.l2.switch_name} />
                  <LocatorContextField label={zh ? '接入接口' : 'Port'} value={locatorContext.l2.port} mono />
                  <LocatorContextField label={zh ? '接口描述' : 'Description'} value={locatorContext.l2.description} />
                  <LocatorContextField label={zh ? '状态 / 模式' : 'State / Mode'} value={[locatorContext.l2.admin_status, locatorContext.l2.oper_status, locatorContext.l2.mode].filter(Boolean).join(' / ')} />
                </LocatorContextCard>

                <LocatorContextCard title={zh ? '三层定位' : 'Layer 3'} icon={Router}>
                  <LocatorContextField label={zh ? '默认网关' : 'Gateway'} value={locatorContext.l3.gateway} mono />
                  <LocatorContextField label={zh ? '网关设备' : 'Gateway Device'} value={locatorContext.l3.gateway_device} />
                  <LocatorContextField label={zh ? '三层接口' : 'L3 Interface'} value={locatorContext.l3.gateway_interface || locatorContext.l3.route_interface} mono />
                  <LocatorContextField label="VRF" value={locatorContext.l3.vrf} />
                  <LocatorContextField label={zh ? '路由下一跳' : 'Next Hop'} value={locatorContext.l3.next_hop} mono />
                  <LocatorContextField label={zh ? '路由来源' : 'Route Source'} value={locatorContext.l3.route_source} />
                  <LocatorContextField label={zh ? '路由更新时间' : 'Route Updated'} value={locatorContext.l3.route_last_updated ? formatRelativeTime(locatorContext.l3.route_last_updated, zh) : ''} />
                  <LocatorContextField
                    label={zh ? '上联设备' : 'Upstream Devices'}
                    value={locatorContext.l3.upstream_devices?.map(item => `${item.device}${item.port ? ` (${item.port}${item.peer_port ? ` ↔ ${item.peer_port}` : ''})` : ''}`).join(', ')}
                  />
                   <LocatorContextField
                     label={zh ? '下联设备' : 'Downstream Devices'}
                     value={locatorContext.l3.downstream_devices?.map(item => `${item.device}${item.port ? ` (${item.port}${item.peer_port ? ` ↔ ${item.peer_port}` : ''})` : ''}`).join(', ') || (zh ? '未发现可信下联' : 'No verified downstream')}
                   />
                   <LocatorContextField
                     label={zh ? '邻接设备（方向未判定）' : 'Adjacent Devices (direction unknown)'}
                     value={locatorContext.l3.adjacent_devices?.map(item => `${item.device}${item.port ? ` (${item.port}${item.peer_port ? ` ↔ ${item.peer_port}` : ''})` : ''}`).join(', ')}
                   />
                </LocatorContextCard>

                <LocatorContextCard title={zh ? '业务关联' : 'Business'} icon={Users}>
                  <LocatorContextField label={zh ? '主机名称' : 'Hostname'} value={locatorContext.business.hostname} />
                  <LocatorContextField label={zh ? '业务/租户' : 'Tenant'} value={locatorContext.business.tenant} />
                  <LocatorContextField label={zh ? '区域/站点' : 'Site'} value={locatorContext.business.site} />
                  <LocatorContextField label={zh ? '部门' : 'Department'} value={locatorContext.business.department} />
                  <LocatorContextField label={zh ? '负责人' : 'Owner'} value={locatorContext.business.owner} />
                  <LocatorContextField label={zh ? '重要级别' : 'Criticality'} value={locatorContext.business.criticality} />
                  <LocatorContextField label={zh ? '关联业务系统' : 'Business Systems'} value={locatorContext.business.business_systems?.join(', ')} />
                  <LocatorContextField label={zh ? '业务等级' : 'Business Level'} value={locatorContext.business.business_level} />
                  <LocatorContextField label={zh ? '最近配置备份' : 'Last Config Backup'} value={locatorContext.business.config_backup_at ? formatRelativeTime(locatorContext.business.config_backup_at, zh) : ''} />
                  {locatorContext.business.open_alerts.length > 0 && (
                    <div className="pt-1 flex items-center gap-1.5 text-amber-600">
                      <AlertCircle size={12} />
                      <span>{zh ? `${locatorContext.business.open_alerts.length} 条未恢复告警` : `${locatorContext.business.open_alerts.length} open alert(s)`}</span>
                    </div>
                  )}
                </LocatorContextCard>
              </div>

              {locatorContext.path.length > 1 && (
                <div className="rounded-xl border border-cyan-200/60 dark:border-cyan-500/20 bg-cyan-50/40 dark:bg-cyan-500/[0.04] p-3">
                  <div className="flex items-center gap-2 mb-3">
                    <Network size={14} className="text-cyan-600" />
                    <p className="text-xs font-semibold text-cyan-800 dark:text-cyan-300">{zh ? '已确认的网络路径' : 'Evidence-backed Network Path'}</p>
                    <span className="text-[10px] text-cyan-700/60 dark:text-cyan-300/60 ml-auto">{zh ? '仅展示拓扑库已有证据' : 'Only topology-backed hops are shown'}</span>
                  </div>
                  <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
                    {locatorContext.path.map((node, index) => (
                      <React.Fragment key={`${node.kind}-${node.label}-${index}`}>
                        {index > 0 && <ArrowRight size={13} className="text-cyan-500/50 flex-shrink-0" />}
                        <div className="min-w-[148px] rounded-lg border border-white/80 dark:border-white/10 bg-white/90 dark:bg-white/[0.06] px-3.5 py-3 shadow-sm">
                          <p className="text-[10px] font-semibold tracking-wide text-cyan-700/70 dark:text-cyan-300/70">{formatPathKind(node.kind, zh)}</p>
                          <p className="mt-1 text-sm font-semibold text-[#164e63] dark:text-[var(--app-text)] truncate" title={node.label}>{node.label}</p>
                          {node.detail && <p className="mt-1 text-[11px] text-black/50 dark:text-white/50 truncate" title={node.detail}>{node.detail}</p>}
                        </div>
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              )}

              <div className="pt-3 border-t border-black/5 dark:border-white/10">
                <div className="flex items-center justify-between gap-3 mb-2">
                  <p className="text-[11px] font-semibold text-black/55 dark:text-white/55">{zh ? '各来源最新观测时间' : 'Latest observation by source'}</p>
                  <p className="text-[10px] text-black/35 dark:text-white/35">{zh ? '不同采集任务独立运行，时间不必相同' : 'Collectors run independently; timestamps may differ'}</p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-2">
                  <FreshnessItem label={zh ? '端点定位' : 'Endpoint'} value={locatorContext.freshness.endpoint_last_seen} thresholdSeconds={15 * 60} zhLang={zh} />
                  <FreshnessItem label="ARP" value={locatorContext.freshness.arp_last_updated} thresholdSeconds={10 * 60} zhLang={zh} />
                  <FreshnessItem label={zh ? '接口快照' : 'Interface'} value={locatorContext.freshness.interface_last_seen} thresholdSeconds={2 * 60 * 60} zhLang={zh} />
                  <FreshnessItem label={zh ? '路由快照' : 'Route'} value={locatorContext.l3.route_last_updated} thresholdSeconds={15 * 60} zhLang={zh} />
                </div>
              </div>
            </div>
          )}

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
          <ActionButton
            icon={Download}
            variant="accent"
            onClick={() => {
              if (!arpTable || arpTable.entries.length === 0) return;
              const q = arpFilter.trim().toLowerCase();
              const rows = (q ? arpTable.entries.filter(e =>
                e.ip.toLowerCase().includes(q) || e.mac.toLowerCase().includes(q) ||
                e.device.toLowerCase().includes(q) || e.interface.toLowerCase().includes(q) ||
                (e.vendor || '').toLowerCase().includes(q)
              ) : arpTable.entries).map(e => ({
                IP: e.ip,
                MAC: formatMacAddress(e.mac),
                VLAN: e.vlan || '',
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
          >
            {zh ? '导出' : 'Export'}
          </ActionButton>
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

        {arpSweepStatus && (
          <div className={`mt-3 rounded-xl border px-3.5 py-2.5 text-xs flex items-start gap-2 ${
            arpSweepStatus.kind === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-amber-200 bg-amber-50 text-amber-700'
          }`}>
            {arpSweepStatus.kind === 'success' ? <CheckCircle2 size={14} className="mt-0.5 flex-shrink-0" /> : <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />}
            <span>{arpSweepStatus.message}</span>
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
          <p className="text-sm text-black/40 dark:text-white/40">{zh ? '暂无 ARP 数据。点击「立即采集」从在线设备获取 ARP 表。' : 'No ARP data. Click "Sweep Now" to collect from online devices.'}</p>
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
              String(e.vlan ?? '').toLowerCase().includes(q) ||
              (e.vendor || '').toLowerCase().includes(q)
            )
          : arpTable.entries;
        const pageStart = (arpPage - 1) * arpPageSize;
        const pageEntries = filtered.slice(pageStart, pageStart + arpPageSize);

        return (
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
            {/* Table header */}
            <div className="grid grid-cols-[1fr_1fr_5rem_6rem_6rem_10rem_8rem] gap-2 px-5 py-2.5 text-[10px] font-bold text-black/40 dark:text-white/40 uppercase tracking-wider border-b border-black/5 dark:border-white/8 bg-black/[0.01] dark:bg-white/[0.02]">
              <span>IP</span>
              <span>MAC</span>
              <span>VLAN</span>
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
                    className={`grid grid-cols-[1fr_1fr_5rem_6rem_6rem_10rem_8rem] gap-2 px-5 py-2 text-xs items-center border-b border-black/[0.03] dark:border-white/[0.05] hover:bg-[#ecfeff]/30 dark:hover:bg-cyan-500/5 transition-colors cursor-pointer ${idx % 2 ? 'bg-black/[0.008] dark:bg-white/[0.015]' : ''}`}
                    onClick={() => { setIp(entry.ip); setActiveTab('locate'); }}
                    title={zh ? '点击定位此 IP' : 'Click to locate this IP'}
                  >
                    <span className="font-mono font-semibold text-[#164e63]">{entry.ip}</span>
                    <span className="font-mono text-black/50">{formatMacAddress(entry.mac)}</span>
                    <span className="font-mono text-cyan-700 dark:text-cyan-400">{entry.vlan || '-'}</span>
                    <span className="text-black/45 truncate" title={entry.vendor}>{entry.vendor || '-'}</span>
                    <span className="text-black/45 truncate" title={entry.interface}>{entry.interface || '-'}</span>
                    <span className="text-[#0891b2] truncate font-medium" title={entry.device}>{entry.device || '-'}</span>
                    <span className={entry.freshness === 'stale' ? 'text-amber-600' : 'text-black/30'} title={`${entry.cached_at} · ${entry.vlan_source || 'unknown VLAN source'}`}>
                      {formatRelativeTime(entry.cached_at, zh)}{entry.freshness === 'stale' ? (zh ? ' · 已过期' : ' · stale') : ''}
                    </span>
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

      {/* ────────────────────────────────────── */}
      {/* TAB: Network Source of Truth (NSOT)   */}
      {/* ────────────────────────────────────── */}
      {activeTab === 'nsot' && (<>
      {/* ── Stats Cards ── */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        {/* Card: network_endpoints */}
        <button onClick={() => { setNsotSubTab('endpoints'); setNsotPage(1); setNsotFilter(''); resetNsotAdvancedFilters(); }} className={`text-left bg-white dark:bg-[#1f2937]/30 rounded-2xl border shadow-sm p-5 transition-all ${nsotSubTab === 'endpoints' ? 'border-[#06b6d4] ring-2 ring-[#06b6d4]/20' : 'border-black/5 dark:border-white/5 hover:border-[#06b6d4]/30'}`}>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 to-cyan-600 flex items-center justify-center">
              <Monitor size={18} className="text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/80 dark:text-white/80">{zh ? '终端事实库' : 'Endpoint Cache'}</div>
              <div className="text-[10px] font-mono text-black/30 dark:text-white/30">network_endpoints</div>
            </div>
          </div>
          <div className="text-3xl font-bold text-[#0891b2] mb-1">{nsotEndpoints?.total ?? '—'}</div>
          <div className="text-[11px] text-black/40 dark:text-white/40">
            {zh ? '活跃' : 'Active'}: {nsotEndpoints?.active ?? 0} · {zh ? '字段' : 'Cols'}: 17
          </div>
          {nsotEndpoints?.timestamp && <div className="text-[10px] text-black/25 dark:text-white/25 mt-1">{zh ? '更新于' : 'Updated'}: {formatRelativeTime(nsotEndpoints.timestamp, zh)}</div>}
        </button>

        {/* Card: ip_inventory */}
        <button onClick={() => { setNsotSubTab('inventory'); setNsotPage(1); setNsotFilter(''); resetNsotAdvancedFilters(); }} className={`text-left bg-white dark:bg-[#1f2937]/30 rounded-2xl border shadow-sm p-5 transition-all ${nsotSubTab === 'inventory' ? 'border-emerald-400 ring-2 ring-emerald-400/20' : 'border-black/5 dark:border-white/5 hover:border-emerald-400/30'}`}>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 flex items-center justify-center">
              <Globe size={18} className="text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/80 dark:text-white/80">{zh ? 'IP 资产明细' : 'IP Inventory'}</div>
              <div className="text-[10px] font-mono text-black/30 dark:text-white/30">ip_inventory</div>
            </div>
          </div>
          <div className="text-3xl font-bold text-emerald-500 mb-1">{nsotInventory?.total ?? '—'}</div>
          <div className="text-[11px] text-black/40 dark:text-white/40">
            {nsotInventory?.type_stats ? Object.entries(nsotInventory.type_stats).map(([k, v]) => `${k}: ${v}`).join(' · ') : `${zh ? '字段' : 'Cols'}: 6`}
          </div>
          {nsotInventory?.timestamp && <div className="text-[10px] text-black/25 dark:text-white/25 mt-1">{zh ? '更新于' : 'Updated'}: {formatRelativeTime(nsotInventory.timestamp, zh)}</div>}
        </button>

        {/* Card: route_cache */}
        <button onClick={() => { setNsotSubTab('routes'); setNsotPage(1); setNsotFilter(''); resetNsotAdvancedFilters(); }} className={`text-left bg-white dark:bg-[#1f2937]/30 rounded-2xl border shadow-sm p-5 transition-all ${nsotSubTab === 'routes' ? 'border-violet-400 ring-2 ring-violet-400/20' : 'border-black/5 dark:border-white/5 hover:border-violet-400/30'}`}>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-violet-600 flex items-center justify-center">
              <Network size={18} className="text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/80 dark:text-white/80">{zh ? '路由事实库' : 'Route Table'}</div>
              <div className="text-[10px] font-mono text-black/30 dark:text-white/30">route_table</div>
            </div>
          </div>
          <div className="text-3xl font-bold text-violet-500 mb-1">{nsotRoutes?.site_stats ? Object.keys(nsotRoutes.site_stats).length : (nsotRoutes?.total ?? '—')}</div>
          <div className="text-[11px] text-black/40 dark:text-white/40">
            {nsotRoutes?.site_stats ? `${zh ? '站点' : 'Sites'}: ${Object.keys(nsotRoutes.site_stats).length} · ${zh ? '路由条目' : 'Routes'}: ${nsotRoutes.total ?? 0}` : `${zh ? '字段' : 'Cols'}: 11`}
          </div>
          {nsotRoutes?.timestamp && <div className="text-[10px] text-black/25 dark:text-white/25 mt-1">{zh ? '更新于' : 'Updated'}: {formatRelativeTime(nsotRoutes.timestamp, zh)}</div>}
        </button>

        {/* Card: routing_neighbors */}
        <button onClick={() => { setNsotSubTab('neighbors'); setNsotPage(1); setNsotFilter(''); resetNsotAdvancedFilters(); }} className={`text-left bg-white dark:bg-[#1f2937]/30 rounded-2xl border shadow-sm p-5 transition-all ${nsotSubTab === 'neighbors' ? 'border-indigo-400 ring-2 ring-indigo-400/20' : 'border-black/5 dark:border-white/5 hover:border-indigo-400/30'}`}>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center">
              <Users size={18} className="text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/80 dark:text-white/80">{zh ? '路由协议邻居' : 'Routing Neighbors'}</div>
              <div className="text-[10px] font-mono text-black/30 dark:text-white/30">routing_neighbors</div>
            </div>
          </div>
          <div className="text-3xl font-bold text-indigo-500 mb-1">{nsotNeighbors?.site_stats ? Object.keys(nsotNeighbors.site_stats).length : (nsotNeighbors?.total ?? '—')}</div>
          <div className="text-[11px] text-black/40 dark:text-white/40">
            {nsotNeighbors?.site_stats ? `${zh ? '站点' : 'Sites'}: ${Object.keys(nsotNeighbors.site_stats).length} · ${zh ? '邻居条目' : 'Neighbors'}: ${nsotNeighbors.total ?? 0}` : `${zh ? '字段' : 'Cols'}: 12`}
          </div>
          {nsotNeighbors?.timestamp && <div className="text-[10px] text-black/25 dark:text-white/25 mt-1">{zh ? '更新于' : 'Updated'}: {formatRelativeTime(nsotNeighbors.timestamp, zh)}</div>}
        </button>

        {/* Card: bgp_routes */}
        <button onClick={() => { setNsotSubTab('bgp_routes'); setNsotPage(1); setNsotFilter(''); resetNsotAdvancedFilters(); }} className={`text-left bg-white dark:bg-[#1f2937]/30 rounded-2xl border shadow-sm p-5 transition-all ${nsotSubTab === 'bgp_routes' ? 'border-amber-400 ring-2 ring-amber-400/20' : 'border-black/5 dark:border-white/5 hover:border-amber-400/30'}`}>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center">
              <Activity size={18} className="text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/80 dark:text-white/80">{zh ? 'BGP 路由表' : 'BGP RIB Table'}</div>
              <div className="text-[10px] font-mono text-black/30 dark:text-white/30">bgp_route_table</div>
            </div>
          </div>
          <div className="text-3xl font-bold text-amber-500 mb-1">{nsotBgpRoutes?.site_stats ? Object.keys(nsotBgpRoutes.site_stats).length : (nsotBgpRoutes?.total ?? '—')}</div>
          <div className="text-[11px] text-black/40 dark:text-white/40">
            {nsotBgpRoutes?.site_stats ? `${zh ? '站点' : 'Sites'}: ${Object.keys(nsotBgpRoutes.site_stats).length} · ${zh ? 'BGP条目' : 'BGP routes'}: ${nsotBgpRoutes.total ?? 0}` : `${zh ? '最佳路径' : 'Best'}: ${nsotBgpRoutes?.entries ? nsotBgpRoutes.entries.filter((e: any) => e.is_best).length : 0}`}
          </div>
          {nsotBgpRoutes?.timestamp && <div className="text-[10px] text-black/25 dark:text-white/25 mt-1">{zh ? '更新于' : 'Updated'}: {formatRelativeTime(nsotBgpRoutes.timestamp, zh)}</div>}
        </button>
      </div>

      {/* ── Toolbar ── */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/30" />
          <input
            className="w-full pl-9 pr-3 py-2 bg-white dark:bg-[#1f2937]/30 rounded-xl border border-black/5 dark:border-white/5 text-sm placeholder-black/30 dark:placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-[#06b6d4]/30"
            placeholder={zh ? '搜索...' : 'Search...'}
            value={nsotFilter}
            onChange={e => { setNsotFilter(e.target.value); setNsotPage(1); }}
          />
        </div>
        <button
          onClick={() => setNsotShowAdvanced(!nsotShowAdvanced)}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium border transition-all ${
            nsotShowAdvanced
              ? 'bg-[#06b6d4]/10 border-[#06b6d4] text-[#0891b2]'
              : 'bg-white dark:bg-[#1f2937]/30 border-black/5 dark:border-white/5 text-black/50 dark:text-white/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]'
          }`}
        >
          <Filter size={13} />
          {zh ? '高级搜索' : 'Advanced'}
        </button>
        <button
          onClick={() => { setNsotPolicyModalOpen(true); fetchNsotCollectionPlans(); }}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-white dark:bg-[#1f2937]/30 border border-black/5 dark:border-white/5 text-black/70 dark:text-white/70 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] rounded-xl text-sm font-medium transition-colors"
          title={zh ? '设置各设备的 NSOT 事实库采集能力与策略' : 'Configure NSOT collection capabilities per device'}
        >
          <Sliders size={13} className="text-[#06b6d4]" />
          {zh ? '采集策略与能力' : 'Collection Policy'}
        </button>
        <button
          onClick={handleNsotSweep}
          disabled={nsotLoading || nsotSweeping}
          className="flex items-center gap-1.5 px-4 py-2 bg-[#06b6d4] hover:bg-[#0891b2] text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-50"
        >
          {nsotSweeping ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {zh ? '立即同步全网数据' : 'Sync All Data'}
        </button>
        <button
          onClick={() => { setNsotEndpoints(null); setNsotInventory(null); setNsotRoutes(null); setNsotNeighbors(null); setNsotBgpRoutes(null); fetchNsotData(); }}
          disabled={nsotLoading || nsotSweeping}
          className="flex items-center gap-1.5 px-4 py-2 bg-[#06b6d4]/10 hover:bg-[#06b6d4]/20 text-[#0891b2] rounded-xl text-sm font-medium transition-colors disabled:opacity-50"
        >
          <RotateCcw size={13} className={nsotLoading ? 'animate-spin' : ''} />
          {zh ? '刷新' : 'Refresh'}
        </button>
      </div>

      {/* ── Advanced Search Panel ── */}
      {nsotShowAdvanced && (
        <div className="bg-white dark:bg-[#1f2937]/35 rounded-2xl border border-black/5 dark:border-white/5 p-4 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="flex items-center justify-between pb-2 border-b border-black/[0.03] dark:border-white/[0.03]">
            <div className="flex items-center gap-2 text-xs font-semibold text-black/50 dark:text-white/50">
              <Filter size={13} className="text-[#06b6d4]" />
              <span>{zh ? '高级过滤条件' : 'Advanced Filter Options'}</span>
            </div>
            <button
              onClick={resetNsotAdvancedFilters}
              className="flex items-center gap-1 text-[11px] text-rose-500 hover:text-rose-600 font-medium transition-colors"
            >
              <RotateCcw size={11} />
              {zh ? '重置条件' : 'Reset Filters'}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {nsotSubTab === 'endpoints' && (
              <>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? 'IP 地址' : 'IP Address'}</label>
                  <input
                    type="text"
                    value={epFilterIp}
                    onChange={e => { setEpFilterIp(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. 192.168.1.1"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? 'MAC 地址' : 'MAC Address'}</label>
                  <input
                    type="text"
                    value={epFilterMac}
                    onChange={e => { setEpFilterMac(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. aa-bb-cc"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '交换机/设备' : 'Switch/Device'}</label>
                  <input
                    type="text"
                    value={epFilterSwitch}
                    onChange={e => { setEpFilterSwitch(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. R1"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? 'VLAN' : 'VLAN'}</label>
                  <input
                    type="text"
                    value={epFilterVlan}
                    onChange={e => { setEpFilterVlan(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. 10"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '终端状态' : 'Status'}</label>
                  <select
                    value={epFilterStatus}
                    onChange={e => { setEpFilterStatus(e.target.value); setNsotPage(1); }}
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white dark:bg-[#1f2937]"
                  >
                    <option value="all">{zh ? '全部状态' : 'All Status'}</option>
                    <option value="active">{zh ? '活跃' : 'Active'}</option>
                    <option value="inactive">{zh ? '离线' : 'Inactive'}</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '采集来源' : 'Source'}</label>
                  <select
                    value={epFilterSource}
                    onChange={e => { setEpFilterSource(e.target.value); setNsotPage(1); }}
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white dark:bg-[#1f2937]"
                  >
                    <option value="all">{zh ? '全部来源' : 'All Sources'}</option>
                    <option value="arp">ARP</option>
                    <option value="mac">MAC</option>
                    <option value="lldp">LLDP</option>
                  </select>
                </div>
              </>
            )}

            {nsotSubTab === 'inventory' && (
              <>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? 'IP 地址' : 'IP Address'}</label>
                  <input
                    type="text"
                    value={invFilterIp}
                    onChange={e => { setInvFilterIp(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. 10.1."
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '所属设备' : 'Device'}</label>
                  <input
                    type="text"
                    value={invFilterDevice}
                    onChange={e => { setInvFilterDevice(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. R1"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '接口类型' : 'Interface Type'}</label>
                  <select
                    value={invFilterType}
                    onChange={e => { setInvFilterType(e.target.value); setNsotPage(1); }}
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white dark:bg-[#1f2937]"
                  >
                    <option value="all">{zh ? '全部类型' : 'All Types'}</option>
                    <option value="loopback">Loopback</option>
                    <option value="physical">Physical</option>
                    <option value="vlan">Vlan</option>
                    <option value="tunnel">Tunnel</option>
                  </select>
                </div>
              </>
            )}

            {nsotSubTab === 'routes' && (
              <>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '所属设备' : 'Device'}</label>
                  <input
                    type="text"
                    value={routeFilterDevice}
                    onChange={e => { setRouteFilterDevice(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. R1"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '目的网络前缀' : 'Destination Prefix'}</label>
                  <input
                    type="text"
                    value={routeFilterPrefix}
                    onChange={e => { setRouteFilterPrefix(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. 10.1.0.0"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '下一跳' : 'Next Hop'}</label>
                  <input
                    type="text"
                    value={routeFilterNextHop}
                    onChange={e => { setRouteFilterNextHop(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. 192.168.1.2"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '路由协议' : 'Protocol'}</label>
                  <select
                    value={routeFilterProtocol}
                    onChange={e => { setRouteFilterProtocol(e.target.value); setNsotPage(1); }}
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white dark:bg-[#1f2937]"
                  >
                    <option value="all">{zh ? '全部协议' : 'All Protocols'}</option>
                    <option value="connected">{zh ? '直连 (connected)' : 'connected'}</option>
                    <option value="local">{zh ? '本地 (local)' : 'local'}</option>
                    <option value="static">{zh ? '静态 (static)' : 'static'}</option>
                    <option value="periodic_static">{zh ? '周期静态 (periodic static)' : 'periodic static'}</option>
                    <option value="user_static">{zh ? '用户静态 (user static)' : 'user static'}</option>
                    <option value="ospf">OSPF</option>
                    <option value="bgp">BGP</option>
                    <option value="eigrp">EIGRP</option>
                    <option value="isis">IS-IS</option>
                    <option value="rip">RIP</option>
                  </select>
                </div>
              </>
            )}

            {nsotSubTab === 'neighbors' && (
              <>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '所属设备' : 'Device'}</label>
                  <input
                    type="text"
                    value={neighFilterDevice}
                    onChange={e => { setNeighFilterDevice(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. R1"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '路由协议' : 'Protocol'}</label>
                  <select
                    value={neighFilterProtocol}
                    onChange={e => { setNeighFilterProtocol(e.target.value); setNsotPage(1); }}
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white dark:bg-[#1f2937]"
                  >
                    <option value="all">{zh ? '全部协议' : 'All Protocols'}</option>
                    <option value="ospf">OSPF</option>
                    <option value="bgp">BGP</option>
                    <option value="eigrp">EIGRP</option>
                    <option value="isis">IS-IS</option>
                    <option value="rip">RIP</option>
                  </select>
                </div>
              </>
            )}

            {nsotSubTab === 'bgp_routes' && (
              <>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '所属设备' : 'Device'}</label>
                  <input
                    type="text"
                    value={bgpFilterDevice}
                    onChange={e => { setBgpFilterDevice(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. R1"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">VRF</label>
                  <input
                    type="text"
                    value={bgpFilterVrf}
                    onChange={e => { setBgpFilterVrf(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. default"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '目的网络前缀' : 'Destination Prefix'}</label>
                  <input
                    type="text"
                    value={bgpFilterPrefix}
                    onChange={e => { setBgpFilterPrefix(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. 10.1.0.0"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '下一跳' : 'Next Hop'}</label>
                  <input
                    type="text"
                    value={bgpFilterNextHop}
                    onChange={e => { setBgpFilterNextHop(e.target.value); setNsotPage(1); }}
                    placeholder="e.g. 192.168.1.2"
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-black/40 dark:text-white/40 mb-1">{zh ? '路由状态' : 'Route Status'}</label>
                  <select
                    value={bgpFilterStatus}
                    onChange={e => { setBgpFilterStatus(e.target.value); setNsotPage(1); }}
                    className="w-full px-3 py-1.5 rounded-lg border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white dark:bg-[#1f2937]"
                  >
                    <option value="all">{zh ? '全部状态' : 'All Statuses'}</option>
                    <option value="best">{zh ? '最佳路径 (Best)' : 'Best Path'}</option>
                    <option value="active">{zh ? '活跃 (Active)' : 'Active Path'}</option>
                    <option value="backup">{zh ? '备用/非最佳 (Backup)' : 'Backup Path'}</option>
                  </select>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {nsotError && <div className="bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded-xl p-3 text-sm text-rose-600 dark:text-rose-400">{nsotError}</div>}

      {nsotSweepSuccessMsg && (
        <div className="bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-900/60 rounded-xl p-3 text-sm text-emerald-600 dark:text-emerald-400 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-emerald-500" />
            <span>{nsotSweepSuccessMsg}</span>
          </div>
          <button onClick={() => setNsotSweepSuccessMsg('')} className="text-emerald-500 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300">
            <X size={14} />
          </button>
        </div>
      )}

      {nsotLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-[#0891b2]" />
          <span className="ml-3 text-sm text-black/40 dark:text-white/40">{zh ? '加载中...' : 'Loading...'}</span>
        </div>
      )}

      {/* ── Data Table ── */}
      {!nsotLoading && (() => {
        const currentData = nsotSubTab === 'endpoints' ? nsotEndpoints
          : nsotSubTab === 'inventory' ? nsotInventory
          : nsotSubTab === 'neighbors' ? nsotNeighbors
          : nsotSubTab === 'bgp_routes' ? nsotBgpRoutes
          : nsotRoutes;
        if (!currentData) return null;

        const columns: { key: string; label: string; width?: string }[] = nsotSubTab === 'endpoints'
          ? [
              { key: 'ip', label: 'IP' },
              { key: 'mac_display', label: 'MAC' },
              { key: 'vendor', label: zh ? '厂商' : 'Vendor' },
              { key: 'switch_name', label: zh ? '交换机' : 'Switch' },
              { key: 'site', label: zh ? '站点' : 'Site' },
              { key: 'switch_port', label: zh ? '端口' : 'Port' },
              { key: 'vlan', label: 'VLAN' },
              { key: 'confidence', label: zh ? '置信度' : 'Confidence' },
              { key: 'source_type', label: zh ? '来源' : 'Source' },
              { key: 'is_active', label: zh ? '状态' : 'Status' },
              { key: 'last_seen', label: zh ? '最后发现' : 'Last Seen' },
            ]
          : nsotSubTab === 'inventory'
          ? [
              { key: 'ip', label: 'IP' },
              { key: 'mask', label: zh ? '掩码' : 'Mask' },
              { key: 'site_name', label: zh ? '站点' : 'Site' },
              { key: 'device_name', label: zh ? '设备' : 'Device' },
              { key: 'interface', label: zh ? '接口' : 'Interface' },
              { key: 'type', label: zh ? '类型' : 'Type' },
              { key: 'last_seen', label: zh ? '最后同步' : 'Last Seen' },
            ]
          : nsotSubTab === 'neighbors'
          ? [
              { key: 'site_name', label: zh ? '站点' : 'Site' },
              { key: 'device_name', label: zh ? '设备' : 'Device' },
              { key: 'protocol', label: zh ? '协议' : 'Protocol' },
              { key: 'neighbor_id', label: zh ? '邻居 Router ID' : 'Neighbor ID' },
              { key: 'neighbor_ip', label: zh ? '邻居 IP' : 'Neighbor IP' },
              { key: 'local_interface', label: zh ? '本地接口' : 'Local Intf' },
              { key: 'state', label: zh ? '状态' : 'State' },
              { key: 'uptime', label: zh ? '持续时间' : 'Uptime' },
              { key: 'remote_as', label: zh ? '对端 AS' : 'Remote AS' },
              { key: 'area_id', label: zh ? 'OSPF 区域' : 'Area ID' },
              { key: 'last_update', label: zh ? '最后更新' : 'Last Update' },
            ]
          : nsotSubTab === 'bgp_routes'
          ? [
              { key: 'site_name', label: zh ? '站点' : 'Site' },
              { key: 'device_name', label: zh ? '设备' : 'Device' },
              { key: 'local_as', label: 'Local AS' },
              { key: 'vrf_name', label: 'VRF' },
              { key: 'prefix', label: zh ? '目的网络前缀' : 'Prefix' },
              { key: 'next_hop', label: zh ? '下一跳' : 'Next Hop' },
              { key: 'metric', label: 'Metric' },
              { key: 'loc_pref', label: 'Local Pref' },
              { key: 'weight', label: 'Weight' },
              { key: 'as_path', label: 'AS Path' },
              { key: 'is_best', label: zh ? '最佳' : 'Best' },
              { key: 'is_active', label: zh ? '活跃' : 'Active' },
              { key: 'last_update', label: zh ? '最后更新' : 'Last Update' },
            ]
          : [
              { key: 'site_name', label: zh ? '站点' : 'Site' },
              { key: 'device_name', label: zh ? '设备' : 'Device' },
              { key: 'vrf_name', label: 'VRF' },
              { key: 'prefix', label: zh ? '前缀' : 'Prefix' },
              { key: 'mask', label: zh ? '掩码' : 'Mask' },
              { key: 'next_hop', label: zh ? '下一跳' : 'Next Hop' },
              { key: 'protocol', label: zh ? '协议' : 'Protocol' },
              { key: 'interface', label: zh ? '出接口' : 'Interface' },
              { key: 'metric', label: 'Metric' },
              { key: 'last_update', label: zh ? '最后更新' : 'Last Update' },
            ];

        const normalizeRouteProtocol = (proto: string): string => {
          const p = (proto || '').trim().toLowerCase();
          const aliases: Record<string, string> = {
            c: 'connected', connected: 'connected', direct: 'connected',
            l: 'local', local: 'local',
            s: 'static', static: 'static',
            p: 'periodic_static', periodic_static: 'periodic_static', 'periodic static': 'periodic_static',
            u: 'user_static', user_static: 'user_static', 'user static': 'user_static',
            o: 'ospf', ospf: 'ospf',
            b: 'bgp', bgp: 'bgp',
            d: 'eigrp', eigrp: 'eigrp',
            i: 'isis', isis: 'isis', 'is-is': 'isis',
            r: 'rip', rip: 'rip',
          };
          if (aliases[p]) return aliases[p];
          if (p.startsWith('ospf')) return 'ospf';
          if (p.startsWith('bgp')) return 'bgp';
          if (p.startsWith('eigrp')) return 'eigrp';
          if (p.startsWith('isis') || p.startsWith('is-is')) return 'isis';
          if (p.startsWith('rip')) return 'rip';
          return p;
        };

        const filterLower = nsotFilter.toLowerCase();
        const filtered = (currentData.entries || []).filter((e: any) => {
          // Global filter
          if (filterLower) {
            const matchesGlobal = columns.some(c => String(e[c.key] ?? '').toLowerCase().includes(filterLower));
            if (!matchesGlobal) return false;
          }
          // Advanced filters
          if (nsotShowAdvanced) {
            if (nsotSubTab === 'endpoints') {
              if (epFilterIp && !String(e.ip ?? '').toLowerCase().includes(epFilterIp.toLowerCase())) return false;
              const macVal = String(e.mac_display ?? e.mac ?? '').toLowerCase();
              if (epFilterMac && !macVal.includes(epFilterMac.toLowerCase())) return false;
              if (epFilterSwitch && !`${String(e.switch_name ?? '')} ${String(e.site ?? '')}`.toLowerCase().includes(epFilterSwitch.toLowerCase())) return false;
              if (epFilterVlan && !String(e.vlan ?? '').toLowerCase().includes(epFilterVlan.toLowerCase())) return false;
              if (epFilterStatus !== 'all') {
                const isActive = !!e.is_active;
                if (epFilterStatus === 'active' && !isActive) return false;
                if (epFilterStatus === 'inactive' && isActive) return false;
              }
              if (epFilterSource !== 'all' && !String(e.source_type ?? '').toLowerCase().includes(epFilterSource.toLowerCase())) return false;
            } else if (nsotSubTab === 'inventory') {
              if (invFilterIp && !String(e.ip ?? '').toLowerCase().includes(invFilterIp.toLowerCase())) return false;
              if (invFilterDevice && !String(e.device_name ?? '').toLowerCase().includes(invFilterDevice.toLowerCase())) return false;
              if (invFilterType !== 'all' && String(e.type ?? '').toLowerCase() !== invFilterType.toLowerCase()) return false;
            } else if (nsotSubTab === 'routes') {
              if (routeFilterDevice && !String(e.device_name ?? '').toLowerCase().includes(routeFilterDevice.toLowerCase())) return false;
              if (routeFilterPrefix && !String(e.prefix ?? '').toLowerCase().includes(routeFilterPrefix.toLowerCase())) return false;
              if (routeFilterNextHop && !String(e.next_hop ?? '').toLowerCase().includes(routeFilterNextHop.toLowerCase())) return false;
              if (routeFilterProtocol !== 'all' && normalizeRouteProtocol(e.protocol) !== routeFilterProtocol.toLowerCase()) return false;
            } else if (nsotSubTab === 'neighbors') {
              if (neighFilterDevice && !String(e.device_name ?? '').toLowerCase().includes(neighFilterDevice.toLowerCase())) return false;
              if (neighFilterProtocol !== 'all' && normalizeRouteProtocol(e.protocol) !== neighFilterProtocol.toLowerCase()) return false;
            } else if (nsotSubTab === 'bgp_routes') {
              if (bgpFilterDevice && !String(e.device_name ?? '').toLowerCase().includes(bgpFilterDevice.toLowerCase())) return false;
              if (bgpFilterVrf && !String(e.vrf_name ?? '').toLowerCase().includes(bgpFilterVrf.toLowerCase())) return false;
              if (bgpFilterPrefix && !String(e.prefix ?? '').toLowerCase().includes(bgpFilterPrefix.toLowerCase())) return false;
              if (bgpFilterNextHop && !String(e.next_hop ?? '').toLowerCase().includes(bgpFilterNextHop.toLowerCase())) return false;
              if (bgpFilterStatus !== 'all') {
                if (bgpFilterStatus === 'best' && !e.is_best) return false;
                if (bgpFilterStatus === 'active' && !e.is_active) return false;
                if (bgpFilterStatus === 'backup' && e.is_best) return false;
              }
            }
          }
          return true;
        });
        const totalPages = Math.max(1, Math.ceil(filtered.length / nsotPageSize));
        const safePage = Math.min(nsotPage, totalPages);
        const paged = filtered.slice((safePage - 1) * nsotPageSize, safePage * nsotPageSize);

        const accentColor = nsotSubTab === 'endpoints' ? '#0891b2'
          : nsotSubTab === 'inventory' ? '#10b981'
          : nsotSubTab === 'neighbors' ? '#6366f1'
          : nsotSubTab === 'bgp_routes' ? '#f59e0b'
          : '#8b5cf6';
        const tableName = nsotSubTab === 'endpoints' ? 'network_endpoints'
          : nsotSubTab === 'inventory' ? 'ip_inventory'
          : nsotSubTab === 'neighbors' ? 'routing_neighbors'
          : nsotSubTab === 'bgp_routes' ? 'bgp_route_table'
          : 'route_table';

        return (
          <div className="bg-white dark:bg-[#1f2937]/30 rounded-2xl border border-black/5 dark:border-white/5 shadow-sm overflow-hidden">
            <div className="px-5 py-3 border-b border-black/5 dark:border-white/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Database size={14} style={{ color: accentColor }} />
                <span className="text-sm font-semibold text-black/70 dark:text-white/70">{tableName}</span>
                <span className="text-[10px] bg-black/5 dark:bg-white/5 text-black/40 dark:text-white/40 rounded-full px-2 py-0.5 font-mono">{filtered.length} {zh ? '条' : 'rows'}</span>
              </div>
              <div className="text-[10px] text-black/30 dark:text-white/30">{columns.length} {zh ? '列' : 'columns'}</div>
            </div>

            {filtered.length === 0 ? (
              <div className="text-center py-12">
                <Database size={32} className="mx-auto mb-3 text-black/10 dark:text-white/10" />
                <div className="text-sm text-black/40 dark:text-white/40">{zh ? '暂无数据' : 'No data yet'}</div>
                <div className="text-[11px] text-black/25 dark:text-white/25 mt-1">{zh ? '后台 Collector 定时任务运行后将自动填充' : 'Data will be populated after background Collector tasks run'}</div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="nx-data-table text-left text-xs">
                  <thead>
                    <tr className="border-b border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02]">
                      {columns.map(col => (
                        <th key={col.key} className="px-4 py-2.5 text-[11px] font-semibold text-black/50 dark:text-white/50 whitespace-nowrap">{col.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {paged.map((row: any, idx: number) => (
                      <tr key={idx} className="border-b border-black/[0.03] dark:border-white/[0.03] hover:bg-black/[0.015] dark:hover:bg-white/[0.015] transition-colors">
                        {columns.map(col => {
                          const val = row[col.key];
                          // Special rendering
                          if (col.key === 'is_active' && nsotSubTab === 'bgp_routes') {
                            return (
                              <td key={col.key} className="px-4 py-2">
                                {val ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 border border-blue-200/50">
                                    <CheckCircle2 size={10} />
                                    {zh ? '活跃' : 'Active'}
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold bg-gray-50 dark:bg-gray-800 text-gray-500 border border-gray-200/50">
                                    <Minus size={10} />
                                    {zh ? '备用' : 'Backup'}
                                  </span>
                                )}
                              </td>
                            );
                          }
                          if (col.key === 'is_best' && nsotSubTab === 'bgp_routes') {
                            return (
                              <td key={col.key} className="px-4 py-2">
                                {val ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600 dark:text-emerald-400 border border-emerald-200/50">
                                    <Check size={10} strokeWidth={3} />
                                    {zh ? '最佳' : 'Best'}
                                  </span>
                                ) : (
                                  <span className="text-black/30 dark:text-white/30 font-mono">—</span>
                                )}
                              </td>
                            );
                          }
                          if (col.key === 'as_path' && nsotSubTab === 'bgp_routes') {
                            return (
                              <td key={col.key} className="px-4 py-2 font-mono text-black/70 dark:text-white/70 whitespace-nowrap">
                                {val ? (
                                  <span className="bg-black/[0.03] dark:bg-white/[0.05] px-1.5 py-0.5 rounded text-[11px] font-semibold text-black/60 dark:text-white/60">
                                    {val}
                                  </span>
                                ) : (
                                  <span className="text-black/25 dark:text-white/25 italic">Local</span>
                                )}
                              </td>
                            );
                          }
                          if (col.key === 'is_active') {
                            return <td key={col.key} className="px-4 py-2">{val ? <span className="inline-flex items-center gap-1 text-emerald-500 text-[11px]"><CheckCircle2 size={11} />{zh ? '活跃' : 'Active'}</span> : <span className="inline-flex items-center gap-1 text-black/30 dark:text-white/30 text-[11px]"><Minus size={11} />{zh ? '离线' : 'Inactive'}</span>}</td>;
                          }
                          if (col.key === 'protocol') {
                            const colors: Record<string, string> = {
                              ospf: 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400',
                              bgp: 'bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400',
                              eigrp: 'bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400',
                              isis: 'bg-cyan-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400',
                              rip: 'bg-pink-50 dark:bg-pink-900/20 text-pink-600 dark:text-pink-400',
                              static: 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400',
                              periodic_static: 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400',
                              user_static: 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400',
                              connected: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400',
                              local: 'bg-teal-50 dark:bg-teal-900/20 text-teal-600 dark:text-teal-400',
                              direct: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400',
                            };
                            const normVal = normalizeRouteProtocol(val);
                            const cls = colors[normVal] || 'bg-gray-50 dark:bg-gray-900/20 text-gray-600 dark:text-gray-400';
                            return <td key={col.key} className="px-4 py-2"><span className={`inline-block px-2 py-0.5 rounded-md text-[10px] font-semibold ${cls}`}>{normVal || '—'}</span></td>;
                          }
                          if (col.key === 'type' && nsotSubTab === 'inventory') {
                            const colors: Record<string, string> = { loopback: 'bg-violet-50 dark:bg-violet-900/20 text-violet-600 dark:text-violet-400', physical: 'bg-cyan-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400', vlan: 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400', tunnel: 'bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400' };
                            const cls = colors[(val || '').toLowerCase()] || 'bg-gray-50 dark:bg-gray-900/20 text-gray-600 dark:text-gray-400';
                            return <td key={col.key} className="px-4 py-2"><span className={`inline-block px-2 py-0.5 rounded-md text-[10px] font-semibold ${cls}`}>{val || '—'}</span></td>;
                          }
                          if (col.key === 'remote_as' && nsotSubTab === 'neighbors') {
                            if (row.protocol === 'bgp') {
                              if (row.local_as && row.remote_as) {
                                const typeStr = row.local_as === row.remote_as ? 'IBGP' : 'EBGP';
                                return (
                                  <td key={col.key} className="px-4 py-2 whitespace-nowrap font-mono">
                                    <span className="text-black/70 dark:text-white/70">{row.remote_as}</span>
                                    <span className={`inline-block ml-1.5 px-1.5 py-0.5 rounded-md text-[9px] font-bold ${row.local_as === row.remote_as ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400' : 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400'}`}>
                                      {typeStr}
                                    </span>
                                  </td>
                                );
                              }
                              return <td key={col.key} className="px-4 py-2 text-black/70 dark:text-white/70 whitespace-nowrap font-mono">{row.remote_as || '—'}</td>;
                            }
                            return <td key={col.key} className="px-4 py-2 text-black/25 dark:text-white/25 whitespace-nowrap font-mono">—</td>;
                          }
                          if (col.key === 'area_id' && nsotSubTab === 'neighbors') {
                            if (row.protocol === 'ospf') {
                              return <td key={col.key} className="px-4 py-2 text-black/70 dark:text-white/70 whitespace-nowrap font-mono">{val || '0.0.0.0'}</td>;
                            }
                            return <td key={col.key} className="px-4 py-2 text-black/25 dark:text-white/25 whitespace-nowrap font-mono">—</td>;
                          }
                          if (col.key === 'last_seen' || col.key === 'last_update') {
                            return <td key={col.key} className="px-4 py-2 text-black/40 dark:text-white/40 whitespace-nowrap">{val ? formatRelativeTime(val, zh) : '—'}</td>;
                          }
                          return <td key={col.key} className="px-4 py-2 text-black/70 dark:text-white/70 whitespace-nowrap font-mono">{val ?? '—'}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {filtered.length > 0 && (
              <Pagination
                currentPage={safePage}
                totalItems={filtered.length}
                itemsPerPage={nsotPageSize}
                onPageChange={setNsotPage}
                onItemsPerPageChange={(v) => { setNsotPage(1); setNsotPageSize(v); }}
                language={language}
              />
            )}
          </div>
        );
      })()}

      </>)}

      {/* ────────────────────────────────────── */}
      {/* TAB: Path Diagnose                    */}
      {/* ────────────────────────────────────── */}
      {activeTab === 'diagnose' && (<>
      {/* ── Inputs Card ── */}
      <div className="bg-white dark:bg-[#1f2937]/30 rounded-2xl border border-black/5 dark:border-white/5 shadow-sm p-5 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-4">
          <div ref={sourceDropdownRef} className="relative">
            <label className="block text-xs font-semibold text-black/50 dark:text-white/50 mb-1.5">{zh ? '源 IP 地址' : 'Source IP'}</label>
            <div className="relative">
              <input
                type="text"
                value={diagSourceIp}
                onChange={e => { setDiagSourceIp(e.target.value); setShowSourceDropdown(true); }}
                onFocus={() => setShowSourceDropdown(true)}
                placeholder="e.g. 10.1.1.10"
                autoComplete="off"
                className="w-full px-3.5 py-2.5 rounded-xl border border-black/10 dark:border-white/10 text-sm bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white pr-8"
              />
              <Database size={13} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/25 dark:text-white/25 pointer-events-none" />
            </div>
            {showSourceDropdown && sourceMatches.length > 0 && (
              <div className="absolute z-50 left-0 right-0 mt-1.5 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-black/10 dark:border-white/10 rounded-xl shadow-xl max-h-56 overflow-y-auto animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="px-3 py-2 border-b border-black/5 dark:border-white/5">
                  <span className="text-[10px] font-semibold text-black/35 dark:text-white/35 uppercase tracking-wider">CMDB {zh ? '资产匹配' : 'Asset Matches'} · {sourceMatches.length}</span>
                </div>
                {sourceMatches.map(d => (
                  <button
                    key={d.id}
                    onClick={() => { setDiagSourceIp(d.ip_address); setShowSourceDropdown(false); }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-[#06b6d4]/5 dark:hover:bg-[#06b6d4]/10 transition-colors group"
                  >
                    <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${isServerPlatform(d.platform || '') ? 'bg-violet-50 dark:bg-violet-900/30' : 'bg-cyan-50 dark:bg-cyan-900/30'}`}>
                      {isServerPlatform(d.platform || '') ? <Monitor size={13} className="text-violet-500" /> : <Router size={13} className="text-[#0891b2]" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-[#164e63] dark:text-[var(--app-text)] truncate group-hover:text-[#0891b2]">{d.hostname}</div>
                      <div className="text-[10px] text-black/40 dark:text-white/40 font-mono">{d.ip_address} · {d.platform || 'Unknown'}</div>
                    </div>
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${d.status === 'online' ? 'bg-emerald-400' : 'bg-neutral-300'}`} />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div ref={targetDropdownRef} className="relative">
            <label className="block text-xs font-semibold text-black/50 dark:text-white/50 mb-1.5">{zh ? '目标 IP 地址' : 'Target IP'}</label>
            <div className="relative">
              <input
                type="text"
                value={diagTargetIp}
                onChange={e => { setDiagTargetIp(e.target.value); setShowTargetDropdown(true); }}
                onFocus={() => setShowTargetDropdown(true)}
                placeholder="e.g. 172.16.1.100"
                autoComplete="off"
                className="w-full px-3.5 py-2.5 rounded-xl border border-black/10 dark:border-white/10 text-sm bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white pr-8"
              />
              <Database size={13} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/25 dark:text-white/25 pointer-events-none" />
            </div>
            {showTargetDropdown && targetMatches.length > 0 && (
              <div className="absolute z-50 left-0 right-0 mt-1.5 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-black/10 dark:border-white/10 rounded-xl shadow-xl max-h-56 overflow-y-auto animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="px-3 py-2 border-b border-black/5 dark:border-white/5">
                  <span className="text-[10px] font-semibold text-black/35 dark:text-white/35 uppercase tracking-wider">CMDB {zh ? '资产匹配' : 'Asset Matches'} · {targetMatches.length}</span>
                </div>
                {targetMatches.map(d => (
                  <button
                    key={d.id}
                    onClick={() => { setDiagTargetIp(d.ip_address); setShowTargetDropdown(false); }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-[#06b6d4]/5 dark:hover:bg-[#06b6d4]/10 transition-colors group"
                  >
                    <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${isServerPlatform(d.platform || '') ? 'bg-violet-50 dark:bg-violet-900/30' : 'bg-cyan-50 dark:bg-cyan-900/30'}`}>
                      {isServerPlatform(d.platform || '') ? <Monitor size={13} className="text-violet-500" /> : <Router size={13} className="text-[#0891b2]" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-[#164e63] dark:text-[var(--app-text)] truncate group-hover:text-[#0891b2]">{d.hostname}</div>
                      <div className="text-[10px] text-black/40 dark:text-white/40 font-mono">{d.ip_address} · {d.platform || 'Unknown'}</div>
                    </div>
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${d.status === 'online' ? 'bg-emerald-400' : 'bg-neutral-300'}`} />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label className="block text-xs font-semibold text-black/50 dark:text-white/50 mb-1.5">{zh ? '协议' : 'Protocol'}</label>
            <select
              value={diagProtocol}
              onChange={e => setDiagProtocol(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl border border-black/10 dark:border-white/10 text-sm bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all dark:text-white dark:bg-[#1f2937]"
            >
              <option value="TCP">TCP</option>
              <option value="UDP">UDP</option>
              <option value="ICMP">ICMP</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-black/50 dark:text-white/50 mb-1.5">{zh ? '目标端口' : 'Target Port'}</label>
            <input
              type="text"
              value={diagProtocol === 'ICMP' ? '' : diagPort}
              onChange={e => setDiagPort(e.target.value)}
              disabled={diagProtocol === 'ICMP'}
              placeholder={diagProtocol === 'ICMP' ? 'N/A' : '443'}
              className="w-full px-3.5 py-2.5 rounded-xl border border-black/10 dark:border-white/10 text-sm bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white disabled:opacity-50 disabled:bg-neutral-100 dark:disabled:bg-white/[0.03] disabled:cursor-not-allowed"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-black/50 dark:text-white/50 mb-1.5">{zh ? 'VRF 路由表 (选填)' : 'VRF Context (Optional)'}</label>
            <input
              type="text"
              value={diagVrf}
              onChange={e => setDiagVrf(e.target.value)}
              placeholder="e.g. VRF-Busi"
              className="w-full px-3.5 py-2.5 rounded-xl border border-black/10 dark:border-white/10 text-sm bg-white dark:bg-black/[0.08] focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all font-mono dark:text-white"
            />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2">
          <div className="text-[11px] text-black/35 dark:text-white/35 flex items-center gap-1.5">
            <Zap size={12} className="text-[#06b6d4]" />
            <span>{zh ? '所有结论均来自本次实时采集；未取得的证据会标记为未知并限制置信度。' : 'All conclusions use evidence collected for this run; missing evidence is marked unknown and caps confidence.'}</span>
          </div>
          <button
            onClick={() => doDiagnose()}
            disabled={diagLoading || !diagSourceIp.trim() || !diagTargetIp.trim()}
            className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-[#0891b2] to-[#06b6d4] text-white text-sm font-semibold hover:from-[#0e7490] hover:to-[#0891b2] disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2 shadow-sm"
          >
            {diagLoading ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            {zh ? '开始诊断' : 'Start Diagnose'}
          </button>
        </div>
      </div>

      {/* ── Diagnose History Panel ── */}
      {diagHistory.length > 0 && !diagLoading && (
        <div className="bg-white dark:bg-[#1f2937]/30 rounded-2xl border border-black/5 dark:border-white/5 shadow-sm p-5 mt-5">
          <div className="flex items-center gap-2 mb-3">
            <Clock size={14} className="text-black/30 dark:text-white/30" />
            <p className="text-xs font-semibold text-black/40 dark:text-white/40 uppercase tracking-wider">{zh ? '最近路径诊断记录' : 'Recent NPA Diagnostics'}</p>
            <button
              onClick={() => {
                setDiagHistory([]);
                localStorage.removeItem('nexora_npa_history');
              }}
              className="ml-auto text-[10px] text-black/25 dark:text-white/25 hover:text-black/50 dark:hover:text-white/50 transition-colors flex items-center gap-1"
            >
              <RotateCcw size={10} />
              {zh ? '清空记录' : 'Clear'}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {diagHistory.map((h, i) => (
              <button
                key={i}
                onClick={() => {
                  setDiagSourceIp(h.source_ip);
                  setDiagTargetIp(h.target_ip);
                  setDiagProtocol(h.protocol);
                  setDiagPort(h.port === 'N/A' ? '' : h.port);
                  setDiagVrf(h.vrf || '');
                }}
                className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono transition-all hover:shadow-sm ${h.conclusion === 'reachable' ? 'border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-500/15' : 'border-rose-200 dark:border-rose-500/20 bg-rose-50/50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-500/15'}`}
                title={zh ? '点击填入此历史记录参数' : 'Click to fill parameters from this history record'}
              >
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${h.conclusion === 'reachable' ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                <span>{h.source_ip} ➔ {h.target_ip}</span>
                <span className="text-[10px] text-black/30 font-sans">({h.protocol}{h.protocol !== 'ICMP' ? `:${h.port}` : ''})</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <style>{`
        @media print {
          body * {
            visibility: hidden;
          }
          #npa-report-card, #npa-report-card * {
            visibility: visible;
          }
          #npa-report-card {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
          }
        }
      `}</style>

      {/* ── Error Box ── */}
      {diagError && (
        <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-2xl px-5 py-4 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-300">{zh ? '诊断出错' : 'Diagnose Failed'}</p>
            <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{diagError}</p>
          </div>
        </div>
      )}

      {/* ── Diagnose Stepper and Log Console ── */}
      {(diagLoading || diagResult) && (
        <div className="grid grid-cols-1 md:grid-cols-12 gap-5">
          {/* Stepper Card */}
          <div className="md:col-span-5 bg-white dark:bg-[#1f2937]/30 rounded-2xl border border-black/5 dark:border-white/5 shadow-sm p-5 space-y-4">
            <h3 className="text-sm font-bold text-[#164e63] dark:text-[var(--app-text)] flex items-center gap-2">
              <Activity size={15} className="text-[#0891b2]" />
              {zh ? '诊断步骤进度' : 'Diagnosis Stepper'}
            </h3>

            <div className="relative pl-6 space-y-5">
              {/* Stepper line */}
              <div className="absolute left-[9px] top-2 bottom-2 w-0.5 bg-black/5 dark:bg-white/10" />

              {(() => {
                const TEMPLATE_STEPS = [
                  { name: "P0. VRF 发现 (VRF Discovery)", desc: zh ? "感知多路由上下文/VRF状态" : "Discover VRF contexts" },
                  { name: "P1. 资产发现 (Asset Discovery)", desc: zh ? "关联CMDB与基础数据收集" : "Associate asset details and collect data" },
                  { name: "P2. 目标分类 (Target Classification)", desc: zh ? "判定目标为直连还是远程网段" : "Determine subnet classification" },
                  { name: "P3. ARP 分析 (ARP Analysis)", desc: zh ? "查询网关 ARP 获取 MAC 地址" : "Retrieve MAC from gateway ARP table" },
                  { name: "P4. MAC 定位 (MAC Analysis)", desc: zh ? "在二层交换机定位物理接口与STP" : "Track MAC to switch port and check STP" },
                  { name: "P4.5. 实时接口链路验证 (Live Interface Validation)", desc: zh ? "实时核验路径出接口和目标接入接口 admin/oper 状态" : "Live-check path egress and target access interface state" },
                  { name: "P5. 路由递归 (Route Recursion)", desc: zh ? "多跳路由路径递归跟踪" : "Recursively track routing hops" },
                  { name: "P5.5. FIB 验证 (FIB Verification)", desc: zh ? "控制面与转发面(CEF/FIB)一致性校验" : "Verify CEF/FIB forwarding plane" },
                  { name: "P6. 策略分析 (Policy Analysis)", desc: zh ? "核验接口 ACL 与防火墙策略过滤" : "Check ACLs and firewall security policies" },
                  { name: "P6.5. BGP 分析 (BGP Analysis)", desc: zh ? "边界路由 BGP 接收与宣告核验" : "Analyze BGP routing and policies" },
                  { name: "P7. Overlay 分析 (Overlay Analysis)", desc: zh ? "分析底层隧道(VXLAN/EVPN/IPsec)" : "Inspect Overlay tunnel status" },
                  { name: "P7.5. HA 分析 (HA Analysis)", desc: zh ? "核验冗余双机(VRRP/HSRP)与脑裂状态" : "Check HA redundancy and split-brain" },
                  {
                    name: diagProtocol === 'ICMP' ? "P8. ICMP 验证 (ICMP Validation)" : `P8. ${diagProtocol} 验证 (${diagProtocol} Validation)`,
                    desc: diagProtocol === 'ICMP'
                      ? (zh ? "目标主机 ICMP Ping 验证" : "Probe ICMP Ping connection")
                      : (zh ? `目标端口 ${diagProtocol} 探测验证` : `Probe ${diagProtocol} port connection`)
                  },
                  { name: "P8.5. 性能分析 (Performance Analysis)", desc: zh ? "收集端口错包(CRC)、丢包与CPU负荷" : "Analyze packet drops, CRC errors and CPU" },
                  { name: "P9. AI 根因推导 (AI Root Cause Engine)", desc: zh ? "多维证据链关联与置信度推算" : "Correlate evidence & calculate confidence" },
                  { name: "P9.5. 证据一致性检查 (Evidence Consistency)", desc: zh ? "核对实时探测、接口、ARP与路径证据" : "Check probe, interface, ARP and path evidence consistency" },
                  { name: "P10. 智能报告 (Smart Report)", desc: zh ? "生成精确 of CLI配置建议与修复结论" : "Format suggestion report & CLI commands" }
                ];

                const displaySteps = (diagResult && diagResult.steps && diagResult.steps.length > 0)
                  ? diagResult.steps
                  : TEMPLATE_STEPS;

                return displaySteps.map((step: any, idx: number) => {
                  let status = "pending";
                  let msg = "";

                  if (diagResult && diagResult.steps && diagResult.steps[idx]) {
                    status = diagResult.steps[idx].status;
                    msg = diagResult.steps[idx].message;
                  } else if (diagLoading) {
                    if (diagCurrentStep > idx) {
                      status = "success";
                    } else if (diagCurrentStep === idx) {
                      status = "loading";
                    }
                  }

                  const isSelectable = diagResult && diagResult.steps && diagResult.steps[idx];

                  return (
                    <div 
                      key={idx} 
                      onClick={() => {
                        if (isSelectable) {
                          setSelectedStepIdx(selectedStepIdx === idx ? null : idx);
                        }
                      }}
                      className={`relative group pl-2 pr-1.5 py-1.5 rounded-xl transition-all select-none ${
                        isSelectable ? "cursor-pointer" : ""
                      } ${
                        selectedStepIdx === idx 
                          ? "bg-[#06b6d4]/10 dark:bg-[#06b6d4]/15 shadow-sm border border-[#06b6d4]/20" 
                          : isSelectable ? "hover:bg-neutral-50 dark:hover:bg-white/[0.02]" : ""
                      }`}
                    >
                      {/* Circle Node */}
                      <div className={`absolute -left-[23px] top-2.5 w-4 h-4 rounded-full flex items-center justify-center border transition-all z-10 ${
                        status === "success" ? "bg-emerald-500 border-emerald-500 text-white" :
                        status === "failed" ? "bg-rose-500 border-rose-500 text-white" :
                        status === "warning" ? "bg-amber-500 border-amber-500 text-white" :
                        status === "loading" ? "bg-[#ecfeff] dark:bg-cyan-900/30 border-[#0891b2] text-[#0891b2]" :
                        "bg-white dark:bg-neutral-900 border-black/10 dark:border-white/10"
                      }`}>
                        {status === "success" && <Check size={10} strokeWidth={3} />}
                        {status === "failed" && <X size={10} strokeWidth={3} />}
                        {status === "warning" && <AlertCircle size={10} strokeWidth={3} />}
                        {status === "loading" && <Loader2 size={10} strokeWidth={3} className="animate-spin" />}
                      </div>

                      {/* Content */}
                      <div className="flex flex-col">
                        <span className={`text-xs font-bold transition-colors ${
                          status === "loading" ? "text-[#0891b2]" :
                          status === "success" ? "text-emerald-700 dark:text-emerald-400" :
                          status === "failed" ? "text-rose-600 dark:text-rose-400" :
                          "text-black/60 dark:text-white/60"
                        }`}>{step.name}</span>
                        <span className="text-[10px] text-black/35 dark:text-white/35 mt-0.5">{msg || step.desc}</span>
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          </div>

          {/* Console Card */}
          <div className="md:col-span-7 md:sticky md:top-5 bg-slate-50/70 dark:bg-[#111827]/40 rounded-2xl border border-slate-200/80 dark:border-white/5 shadow-sm p-4 flex flex-col h-full min-h-[400px] md:min-h-[500px] overflow-hidden">
            <div className="flex items-center justify-between pb-2.5 border-b border-slate-200/80 dark:border-white/5 mb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-slate-500 dark:text-neutral-400 uppercase tracking-wider font-semibold">
                  {selectedStepIdx === null 
                    ? (zh ? '实时执行日志' : 'Execution Logs')
                    : (zh ? `步骤日志: P${selectedStepIdx}` : `Step Logs: P${selectedStepIdx}`)}
                </span>
                {selectedStepIdx !== null && (
                  <button 
                    onClick={() => setSelectedStepIdx(null)}
                    className="text-[9px] text-[#06b6d4] hover:underline hover:text-[#0891b2] font-semibold cursor-pointer"
                  >
                    {zh ? '(显示全部)' : '(Show All)'}
                  </button>
                )}
              </div>
              <div className="flex gap-1.5">
                <span className="w-2 h-2 rounded-full bg-rose-400/80 dark:bg-rose-500/20 border border-rose-400 dark:border-rose-500/40" />
                <span className="w-2 h-2 rounded-full bg-amber-400/80 dark:bg-amber-500/20 border border-amber-400 dark:border-amber-500/40" />
                <span className="w-2 h-2 rounded-full bg-emerald-400/80 dark:bg-emerald-500/20 border border-emerald-400 dark:border-emerald-500/40" />
              </div>
            </div>
            
            <div className="flex-1 overflow-auto space-y-1.5 pr-2 custom-scrollbar select-text text-slate-600 dark:text-neutral-400 font-mono text-xs">
              {selectedStepIdx === null ? (
                <>
                  {diagLoading && diagCurrentStep >= 0 && (
                    <div className="text-[#0891b2] animate-pulse">
                      &gt; {zh ? '正在执行步骤：' : 'Executing step: '} {getStepNames()[diagCurrentStep]}...
                    </div>
                  )}
                  {diagResult && diagResult.steps ? (
                    diagResult.steps.map((st: any, i: number) => (
                      <div key={i} className="border-b border-slate-200/40 dark:border-white/[0.03] pb-2 last:border-0">
                        <div className="flex items-center justify-between">
                          <span className={`font-semibold cursor-pointer hover:underline ${
                            st.status === 'success' ? 'text-emerald-600 dark:text-emerald-400' :
                            st.status === 'failed' ? 'text-rose-600 dark:text-rose-400' :
                            st.status === 'warning' ? 'text-amber-600 dark:text-amber-400' : 'text-slate-500 dark:text-neutral-400'
                          }`} onClick={() => setSelectedStepIdx(i)}>[{st.name}]</span>
                          {st.log && (
                            <span className="text-[10px] text-[#06b6d4] hover:text-[#0891b2] cursor-pointer font-sans" onClick={() => setSelectedStepIdx(i)}>
                              {zh ? '查看原始日志 ➔' : 'View CLI Log ➔'}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500 dark:text-neutral-400 leading-relaxed pl-3 border-l border-slate-200/80 dark:border-white/5">{st.message}</p>
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-400 dark:text-neutral-600 italic mt-12 text-center">{zh ? '等待诊断开始...' : 'Waiting for diagnostics to begin...'}</div>
                  )}
                </>
              ) : (
                diagResult && diagResult.steps && diagResult.steps[selectedStepIdx] ? (() => {
                  const st = diagResult.steps[selectedStepIdx];
                  return (
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className={`font-semibold ${
                          st.status === 'success' ? 'text-emerald-600 dark:text-emerald-400' :
                          st.status === 'failed' ? 'text-rose-600 dark:text-rose-400' :
                          st.status === 'warning' ? 'text-amber-600 dark:text-amber-400' : 'text-slate-500 dark:text-neutral-400'
                        }`}>[{st.name}]</span>
                      </div>
                      <pre className="mt-1 text-[11px] whitespace-pre-wrap leading-relaxed text-slate-700 dark:text-neutral-300 font-mono pl-3 border-l border-slate-200/80 dark:border-white/5 bg-white/70 dark:bg-black/30 border border-slate-200/50 dark:border-white/5 p-3 rounded-xl overflow-x-auto max-h-[350px] md:max-h-[420px] custom-scrollbar">
                        {st.log || st.message}
                      </pre>
                    </div>
                  );
                })() : (
                  <div className="text-slate-400 dark:text-neutral-600 italic mt-12 text-center">{zh ? '步骤日志为空' : 'Step logs are empty'}</div>
                )
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Path Topology & Sequence Flow Visualization ── */}
      {diagResult && diagResult.hops && (() => {
        const finalHops = diagResult.hops || [];
        const icmpOrServiceProbe = (diagResult.steps || []).find((step: any) =>
          /^P8\.(?!5\.)/.test(String(step?.name || ''))
        );
        const hasTarget = diagResult.report.conclusion === 'reachable'
          && icmpOrServiceProbe?.status === 'success';
        const lastHopIsTarget = finalHops.length > 0 && finalHops[finalHops.length - 1].ip === diagResult.target_ip;
        
        // Construct lanes list
        const lanes = [
          { id: 'source', name: zh ? '源主机' : 'Source Host', ip: diagResult.source_ip, type: 'source', status: 'active' },
          ...finalHops.map((hop: any, idx: number) => {
            const isLast = idx === finalHops.length - 1;
            const isTarget = isLast && lastHopIsTarget;
            return {
              id: `hop-${idx}`,
              name: isTarget ? (zh ? '目标主机' : 'Target Host') : (hop.device_name || `Hop ${idx + 1}`),
              ip: hop.ip,
              type: isTarget ? 'target' : 'hop',
              device_type: hop.device_type,
              status: hop.status,
              detail: hop.detail,
              cpu_usage: hop.cpu_usage,
              memory_usage: hop.memory_usage
            };
          })
        ];

        if (!lastHopIsTarget) {
          lanes.push({
            id: 'target',
            name: zh ? '目标主机' : 'Target Host',
            ip: diagResult.target_ip,
            type: 'target',
            status: hasTarget ? 'active' : 'unreachable'
          });
        }

        // Generate events
        const events = generateSequenceEvents(diagResult, lanes);

        return (
          <div className="bg-white dark:bg-[#1f2937]/30 rounded-2xl border border-black/5 dark:border-white/5 shadow-sm p-6 space-y-5">
            <style>{`
              @keyframes strokeFlow {
                from {
                  stroke-dashoffset: 20;
                }
                to {
                  stroke-dashoffset: 0;
                }
              }
              .ecmp-flow-line {
                stroke-dasharray: 6, 4;
                animation: strokeFlow 1.5s linear infinite;
              }
            `}</style>
            
            {/* SVG Markers Defs */}
            <svg style={{ position: 'absolute', width: 0, height: 0 }}>
              <defs>
                <marker id="arrow-green" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#10b981" />
                </marker>
                <marker id="arrow-blue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#06b6d4" />
                </marker>
                <marker id="arrow-red" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#f43f5e" />
                </marker>
                <marker id="arrow-gray" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#a3a3a3" />
                </marker>
              </defs>
            </svg>

            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center border-b border-slate-100 dark:border-white/5 pb-3 gap-2">
              <h3 className="text-sm font-bold text-[#164e63] dark:text-[var(--app-text)] flex items-center gap-2">
                <Network size={15} className="text-[#0891b2]" />
                {zh ? '可视化链路路径拓扑' : 'Visual Link Path Topology'}
              </h3>
              
              {/* View Mode Switcher */}
              <div className="flex items-center gap-1 bg-slate-100 dark:bg-zinc-800/80 p-1 rounded-xl text-xs self-start sm:self-auto">
                <button
                  onClick={() => setViewMode('topology')}
                  className={`px-3 py-1.5 rounded-lg transition-all font-semibold cursor-pointer ${
                    viewMode === 'topology'
                      ? 'bg-white dark:bg-zinc-700 shadow-sm text-[#0891b2] dark:text-cyan-400'
                      : 'text-slate-500 hover:text-slate-700 dark:text-neutral-400 dark:hover:text-neutral-200'
                  }`}
                >
                  {zh ? '拓扑视图' : 'Topology View'}
                </button>
                <button
                  onClick={() => setViewMode('sequence')}
                  className={`px-3 py-1.5 rounded-lg transition-all font-semibold cursor-pointer ${
                    viewMode === 'sequence'
                      ? 'bg-white dark:bg-zinc-700 shadow-sm text-[#0891b2] dark:text-cyan-400'
                      : 'text-slate-500 hover:text-slate-700 dark:text-neutral-400 dark:hover:text-neutral-200'
                  }`}
                >
                  {zh ? '时序流向' : 'Sequence Flow'}
                </button>
              </div>
            </div>

            {viewMode === 'topology' ? (
              (() => {
                const renderEcmpConnector = (prevHop: any, currentHop: any) => {
                  const prevIsEcmp = !!(prevHop && prevHop.is_ecmp);
                  const currentIsEcmp = !!(currentHop && currentHop.is_ecmp);
                  
                  const isBlocked = (prevHop && prevHop.status === 'blocked') || (currentHop && currentHop.status === 'blocked');
                  const isTimeout = (prevHop && prevHop.status === 'timeout') || (currentHop && currentHop.status === 'timeout');
                  
                  let strokeColor = 'stroke-emerald-400 dark:stroke-emerald-500';
                  let markerId = 'arrow-green';
                  if (isBlocked) {
                    strokeColor = 'stroke-rose-400 dark:stroke-rose-500';
                    markerId = 'arrow-red';
                  } else if (isTimeout) {
                    strokeColor = 'stroke-neutral-300 dark:stroke-neutral-600';
                    markerId = 'arrow-gray';
                  }
                  
                  return (
                    <div className="flex items-center justify-center flex-shrink-0 w-8 h-[192px] overflow-visible relative">
                      <svg className="w-8 h-[192px] overflow-visible absolute inset-0">
                        {prevIsEcmp && currentIsEcmp ? (
                          <>
                            <path d="M 0 44 L 32 44" className={`fill-none stroke-2 ${strokeColor} ecmp-flow-line`} markerEnd={`url(#${markerId})`} />
                            <path d="M 0 148 L 32 148" className={`fill-none stroke-2 ${strokeColor} ecmp-flow-line`} markerEnd={`url(#${markerId})`} />
                          </>
                        ) : prevIsEcmp ? (
                          <>
                            <path d="M 0 44 C 16 44, 16 96, 32 96" className={`fill-none stroke-2 ${strokeColor} ecmp-flow-line`} />
                            <path d="M 0 148 C 16 148, 16 96, 32 96" className={`fill-none stroke-2 ${strokeColor} ecmp-flow-line`} markerEnd={`url(#${markerId})`} />
                          </>
                        ) : currentIsEcmp ? (
                          <>
                            <path d="M 0 96 C 16 96, 16 44, 32 44" className={`fill-none stroke-2 ${strokeColor} ecmp-flow-line`} markerEnd={`url(#${markerId})`} />
                            <path d="M 0 96 C 16 96, 16 148, 32 148" className={`fill-none stroke-2 ${strokeColor} ecmp-flow-line`} markerEnd={`url(#${markerId})`} />
                          </>
                        ) : (
                          <path d="M 0 96 L 32 96" className={`fill-none stroke-2 ${strokeColor} ecmp-flow-line`} markerEnd={`url(#${markerId})`} />
                        )}
                      </svg>
                    </div>
                  );
                };

                return (
                  <div className="flex flex-col sm:flex-row items-center justify-center gap-2 pt-6 pb-4 overflow-x-auto min-h-[220px]">
                    {/* Source Node */}
                    <div className="h-[192px] flex items-center justify-center flex-shrink-0">
                      <div className="flex flex-col items-center bg-white dark:bg-zinc-900 border border-violet-200 dark:border-violet-500/20 rounded-2xl p-4 w-36 shadow-sm">
                        <div className="w-10 h-10 rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center mb-2">
                          <Monitor className="text-violet-500" size={18} />
                        </div>
                        <span className="text-xs font-bold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '源主机' : 'Source Host'}</span>
                        <span className="text-[10px] text-black/35 font-mono mt-0.5">{diagResult.source_ip}</span>
                      </div>
                    </div>

                    {/* Path hops */}
                    {diagResult.hops.map((hop: any, idx: number) => {
                      const prevHop = idx > 0 ? diagResult.hops[idx - 1] : null;
                      const isBlocked = hop.status === 'blocked';
                      const isTimeout = hop.status === 'timeout';
                      const cmdbDevice = findDeviceByIp(hop.ip);
                      const isActive = activeHopIdx === idx;
                      
                      return (
                        <React.Fragment key={idx}>
                          {/* Arrow connector */}
                          {renderEcmpConnector(prevHop, hop)}

                          {/* Device Node(s) */}
                          {hop.is_ecmp ? (
                            <div className="h-[192px] flex flex-col justify-center gap-4 flex-shrink-0">
                              {hop.paths.map((subHop: any, subIdx: number) => {
                                const isSubBlocked = subHop.status === 'blocked';
                                const isSubTimeout = subHop.status === 'timeout';
                                const subCmdbDevice = findDeviceByIp(subHop.ip);
                                const isSubActive = activeHopIdx === idx && activeSubHopIdx === subIdx;
                                
                                return (
                                  <button
                                    key={subIdx}
                                    onClick={() => {
                                      setActiveHopIdx(idx);
                                      setActiveSubHopIdx(subIdx);
                                    }}
                                    className={`relative flex flex-col items-center bg-white dark:bg-zinc-900 border rounded-2xl p-3 w-36 shadow-sm transition-all cursor-pointer hover:shadow-md hover:scale-[1.03] ${
                                      isSubBlocked ? "border-rose-400 dark:border-rose-500/30 ring-2 ring-rose-500/20" :
                                      isSubTimeout ? "border-neutral-200 dark:border-neutral-800 opacity-60" :
                                      isSubActive ? "border-[#06b6d4] dark:border-[#06b6d4]/40 ring-2 ring-[#06b6d4]/25 shadow-lg" :
                                      "border-[#06b6d4]/20 dark:border-[#06b6d4]/10"
                                    }`}
                                  >
                                    <div className={`w-8 h-8 rounded-full flex items-center justify-center mb-1.5 ${
                                      isSubBlocked ? "bg-rose-100 dark:bg-rose-950/40 text-rose-500" :
                                      isSubTimeout ? "bg-neutral-100 dark:bg-neutral-800 text-neutral-400" :
                                      "bg-cyan-50 dark:bg-cyan-950/40 text-[#0891b2]"
                                    }`}>
                                      {isSubBlocked ? <ShieldAlert size={14} /> :
                                       subHop.device_type === 'firewall' ? <ShieldAlert size={14} /> :
                                       <Server size={14} />}
                                    </div>
                                    <span className={`text-[11px] font-bold truncate w-full text-center ${
                                      isSubBlocked ? "text-rose-600 dark:text-rose-400" :
                                      isSubTimeout ? "text-neutral-400" : "text-[#164e63] dark:text-[var(--app-text)]"
                                    }`} title={subHop.device_name}>{subHop.device_name}</span>
                                    <span className="text-[9px] text-black/35 font-mono mt-0.5 truncate w-full">{subHop.ip}</span>
                                    <span className={`text-[8px] px-1.5 py-0.5 rounded-full mt-1 font-mono font-medium ${
                                      isSubBlocked ? "bg-rose-50 dark:bg-rose-950/30 text-rose-600" :
                                      isSubTimeout ? "bg-neutral-50 dark:bg-neutral-950/30 text-neutral-400" :
                                      "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600"
                                    }`}>{subHop.detail || (isSubBlocked ? (zh ? "阻断" : "Blocked") : (zh ? "正常" : "Active"))}</span>
                                    {subCmdbDevice && <Eye size={9} className="absolute top-2 right-2 text-black/20 dark:text-white/20" />}
                                  </button>
                                );
                              })}
                            </div>
                          ) : (
                            <div className="h-[192px] flex items-center justify-center flex-shrink-0">
                              <button
                                onClick={() => setActiveHopIdx(isActive ? null : idx)}
                                className={`relative flex flex-col items-center bg-white dark:bg-zinc-900 border rounded-2xl p-4 w-36 shadow-sm transition-all cursor-pointer hover:shadow-md hover:scale-[1.03] ${
                                  isBlocked ? "border-rose-400 dark:border-rose-500/30 ring-2 ring-rose-500/20 animate-pulse" :
                                  isTimeout ? "border-neutral-200 dark:border-neutral-800 opacity-60" :
                                  isActive ? "border-[#06b6d4] dark:border-[#06b6d4]/40 ring-2 ring-[#06b6d4]/25 shadow-lg" :
                                  "border-[#06b6d4]/20 dark:border-[#06b6d4]/10"
                                }`}
                              >
                                <div className={`w-10 h-10 rounded-full flex items-center justify-center mb-2 ${
                                  isBlocked ? "bg-rose-100 dark:bg-rose-950/40 text-rose-500" :
                                  isTimeout ? "bg-neutral-100 dark:bg-neutral-800 text-neutral-400" :
                                  "bg-cyan-50 dark:bg-cyan-950/40 text-[#0891b2]"
                                }`}>
                                  {isBlocked ? <ShieldAlert size={18} className="animate-bounce" /> :
                                   hop.device_type === 'firewall' ? <ShieldAlert size={18} /> :
                                   <Server size={18} />}
                                </div>
                                <span className={`text-xs font-bold truncate w-full text-center ${
                                  isBlocked ? "text-rose-600 dark:text-rose-400 font-bold" :
                                  isTimeout ? "text-neutral-400" : "text-[#164e63] dark:text-[var(--app-text)]"
                                 }`} title={hop.device_name}>{hop.device_name}</span>
                                 <span className="text-[10px] text-black/35 font-mono mt-0.5">{hop.ip}</span>
                                 <span className="text-[8px] text-black/40 dark:text-white/40 font-mono mt-1 truncate w-full" title={`ingress=${hop.ingress_interface || 'unknown'} · egress=${hop.egress_interface || 'unknown'}`}>
                                   in {hop.ingress_interface || '?'} · out {hop.egress_interface || '?'}
                                 </span>
                                 <span className={`text-[9px] px-1.5 py-0.5 rounded-full mt-1.5 font-mono font-medium ${
                                  isBlocked ? "bg-rose-50 dark:bg-rose-950/30 text-rose-600" :
                                  isTimeout ? "bg-neutral-50 dark:bg-neutral-950/30 text-neutral-400" :
                                  "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600"
                                }`}>{hop.detail || (isBlocked ? (zh ? "阻断" : "Blocked") : (zh ? "正常" : "Active"))}</span>
                                {cmdbDevice && <Eye size={10} className="absolute top-2 right-2 text-black/20 dark:text-white/20" />}
                              </button>
                            </div>
                          )}
                        </React.Fragment>
                      );
                    })}

                    {/* Target Node */}
                    {diagResult.report.conclusion === 'reachable' && (
                      <>
                        {renderEcmpConnector(diagResult.hops[diagResult.hops.length - 1], null)}
                        <div className="h-[192px] flex items-center justify-center flex-shrink-0">
                          <div className="flex flex-col items-center bg-white dark:bg-zinc-900 border border-emerald-200 dark:border-emerald-500/20 rounded-2xl p-4 w-36 shadow-sm">
                            <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center mb-2">
                              <Globe className="text-emerald-500" size={18} />
                            </div>
                            <span className="text-xs font-bold text-[#164e63] dark:text-[var(--app-text)]">{zh ? '目标主机' : 'Target Host'}</span>
                            <span className="text-[10px] text-black/35 font-mono mt-0.5">{diagResult.target_ip}</span>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                );
              })()
            ) : (
              /* New Sequence Flow View rendering */
              <div className="space-y-4 pt-4">
                {/* Flow Summary Bar */}
                <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3.5 bg-slate-50 dark:bg-zinc-900/60 rounded-2xl border border-slate-100 dark:border-zinc-800 text-xs font-mono shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400 dark:text-neutral-500 font-sans font-semibold">{zh ? '传输链路:' : 'Link Path:'}</span>
                    <span className="text-[#0891b2] dark:text-cyan-400 font-bold">{diagResult.source_ip}</span>
                    <ArrowRight size={12} className="text-slate-400" />
                    <span className="text-emerald-500 dark:text-emerald-400 font-bold">{diagResult.target_ip}</span>
                  </div>
                  <div className="h-4 w-px bg-slate-200 dark:bg-zinc-800 hidden sm:block" />
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400 dark:text-neutral-500 font-sans font-semibold">{zh ? '总跳数:' : 'Total Hops:'}</span>
                    <span className="text-slate-700 dark:text-neutral-300 font-bold">{diagResult.hops.length} {zh ? '跳' : 'hops'}</span>
                  </div>
                  <div className="h-4 w-px bg-slate-200 dark:bg-zinc-800 hidden sm:block" />
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400 dark:text-neutral-500 font-sans font-semibold">{zh ? '端到端延迟:' : 'End-to-End RTT:'}</span>
                    <span className="text-violet-500 dark:text-violet-400 font-bold">
                      {(() => {
                        const finalHop = diagResult.hops.length > 0 ? diagResult.hops[diagResult.hops.length - 1] : null;
                        if (finalHop && finalHop.rtt_ms && finalHop.rtt_ms.length > 0) {
                          return `${Math.round(finalHop.rtt_ms[0])}ms`;
                        }
                        return 'N/A';
                      })()}
                    </span>
                  </div>
                </div>

                <div className="overflow-x-auto w-full custom-scrollbar pt-2 relative">
                  <div
                    style={{
                      minWidth: lanes.length * 150,
                      gridTemplateColumns: `repeat(${lanes.length}, minmax(140px, 1fr))`
                    }}
                    className="grid gap-0 relative"
                  >
                  {/* Vertical Lifelines (overlayed absolute lines) */}
                  <div className="absolute inset-y-0 left-0 right-0 pointer-events-none">
                    {lanes.map((lane, idx) => (
                      <div
                        key={idx}
                        className="absolute top-0 bottom-0 border-l-2 border-dashed border-slate-200 dark:border-zinc-800"
                        style={{ left: `${(idx + 0.5) * (100 / lanes.length)}%` }}
                      />
                    ))}
                  </div>

                  {/* Grid Header Cards */}
                  {lanes.map((lane, idx) => {
                    const isSrc = lane.type === 'source';
                    const isTgt = lane.type === 'target';
                    const isBlocked = lane.status === 'blocked';
                    const isUnreachable = lane.status === 'unreachable';
                    
                    let headerBg = 'bg-cyan-50 dark:bg-cyan-950/40 border-cyan-200 dark:border-cyan-500/20';
                    let iconColor = 'text-cyan-500';
                    if (isSrc) {
                      headerBg = 'bg-violet-50 dark:bg-violet-950/40 border-violet-200 dark:border-violet-500/20';
                      iconColor = 'text-violet-500';
                    } else if (isTgt) {
                      headerBg = isUnreachable
                        ? 'bg-neutral-50 dark:bg-neutral-900 border-neutral-200 dark:border-neutral-800/50 opacity-60'
                        : 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-500/20';
                      iconColor = isUnreachable ? 'text-neutral-400' : 'text-emerald-500';
                    } else if (isBlocked) {
                      headerBg = 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-500/20';
                      iconColor = 'text-rose-500';
                    }

                    return (
                      <div key={lane.id} className="flex flex-col items-center pb-8 z-10 px-2">
                        <div className={`flex flex-col items-center bg-white dark:bg-zinc-900 border rounded-2xl p-3 w-full shadow-sm ${headerBg}`}>
                          <div className="w-8 h-8 rounded-full bg-white dark:bg-black/30 flex items-center justify-center mb-1.5 shadow-sm">
                            {isSrc ? <Monitor className={iconColor} size={14} /> :
                             isTgt ? <Globe className={iconColor} size={14} /> :
                             isBlocked ? <ShieldAlert className={iconColor} size={14} /> :
                             <Server className={iconColor} size={14} />}
                          </div>
                          <span className="text-[11px] font-bold text-[#164e63] dark:text-[var(--app-text)] truncate max-w-full text-center">
                            {lane.name}
                          </span>
                          <span className="text-[9px] text-black/35 font-mono mt-0.5">{lane.ip}</span>
                          {lane.type === 'hop' && lane.cpu_usage !== undefined && (
                            <div className="flex gap-1.5 mt-1 text-[8px] font-semibold font-mono">
                              <span className={lane.cpu_usage > 80 ? "text-rose-500 animate-pulse font-bold" : "text-slate-400 dark:text-neutral-500"}>
                                CPU:{lane.cpu_usage}%
                              </span>
                              <span className="text-slate-300 dark:text-zinc-800">|</span>
                              <span className={lane.memory_usage > 80 ? "text-rose-500 font-bold" : "text-slate-400 dark:text-neutral-500"}>
                                MEM:{lane.memory_usage}%
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}

                  {/* Events Rows */}
                  <div className="col-span-full flex flex-col pt-2 pb-6">
                    {events.map((event) => {
                      const isForward = event.direction === 'forward';
                      const isSuccess = event.status === 'active' || event.status === 'success' || !event.status || event.status === 'refused';
                      const isBlocked = event.status === 'blocked';
                      const isRefused = event.status === 'refused';
                      const isTimeout = event.status === 'timeout';
                      
                      let strokeColor = 'stroke-emerald-500 dark:stroke-emerald-400';
                      let textColor = 'text-emerald-600 dark:text-emerald-400';
                      let borderClass = 'border-emerald-200 dark:border-emerald-800';
                      let markerId = 'arrow-green';
                      
                      if (isBlocked) {
                        strokeColor = 'stroke-rose-500 dark:stroke-rose-400';
                        textColor = 'text-rose-600 dark:text-rose-400';
                        borderClass = 'border-rose-200 dark:border-rose-800';
                        markerId = 'arrow-red';
                      } else if (isRefused) {
                        strokeColor = 'stroke-rose-500 dark:stroke-rose-400';
                        textColor = 'text-rose-600 dark:text-rose-400';
                        borderClass = 'border-rose-200 dark:border-rose-800';
                        markerId = 'arrow-red';
                      } else if (isTimeout) {
                        strokeColor = 'stroke-neutral-300 dark:stroke-neutral-600';
                        textColor = 'text-neutral-500 dark:text-neutral-400';
                        borderClass = 'border-neutral-200 dark:border-neutral-800';
                        markerId = 'arrow-gray';
                      } else if (event.type === 'response') {
                        strokeColor = 'stroke-cyan-500 dark:stroke-cyan-400';
                        textColor = 'text-cyan-600 dark:text-cyan-400';
                        borderClass = 'border-cyan-200 dark:border-cyan-800';
                        markerId = 'arrow-blue';
                      }

                      const leftPos = (Math.min(event.startCol, event.endCol) + 0.5) * (100 / lanes.length);
                      const widthPos = Math.abs(event.startCol - event.endCol) * (100 / lanes.length);

                      return (
                        <div
                          key={event.id}
                          className="relative h-16 group select-none transition-colors hover:bg-slate-500/5 dark:hover:bg-white/[0.02]"
                        >
                          {/* Arrow SVG container */}
                          <div
                            className="absolute h-8 flex items-center"
                            style={{
                              left: `${leftPos}%`,
                              width: `${widthPos}%`,
                              top: '16px'
                            }}
                          >
                            <svg className="w-full h-8 overflow-visible">
                              <line
                                x1={isForward ? "0%" : "100%"}
                                y1="50%"
                                x2={isForward ? "100%" : "0%"}
                                y2="50%"
                                className={`stroke-[1.5] ${strokeColor}`}
                                style={isSuccess ? {
                                  strokeDasharray: '6, 4',
                                  animation: 'strokeFlow 1.5s linear infinite'
                                } : (isTimeout ? { strokeDasharray: '4, 4', opacity: 0.5 } : undefined)}
                                markerEnd={!isTimeout ? `url(#${markerId})` : undefined}
                              />
                            </svg>

                            {/* Label Overlay */}
                            <span className={`absolute left-1/2 -translate-x-1/2 bottom-5 px-1.5 py-0.5 bg-white dark:bg-zinc-900 border text-[9px] font-bold rounded-md shadow-sm transition-all group-hover:scale-105 z-10 ${textColor} ${borderClass}`}>
                              {event.label}
                            </span>

                            {/* Blocked Barrier Marker */}
                            {isBlocked && (
                              <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 w-4.5 h-4.5 rounded-full bg-rose-500 border border-white dark:border-zinc-900 flex items-center justify-center text-white text-[9px] font-black shadow-md z-20 animate-pulse">
                                ✕
                              </div>
                            )}
                            {isTimeout && (
                              <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 w-4.5 h-4.5 rounded-full bg-neutral-400 border border-white dark:border-zinc-900 flex items-center justify-center text-white text-[10px] font-black shadow-md z-20">
                                ?
                              </div>
                            )}
                          </div>

                          {/* Simulation Packet Tooltip */}
                          <div className="absolute z-50 bottom-full mb-1 left-1/2 -translate-x-1/2 pointer-events-none w-72 bg-slate-950/95 border border-white/10 rounded-xl p-3 shadow-2xl opacity-0 group-hover:opacity-100 transition-all duration-200 scale-95 origin-bottom group-hover:scale-100 flex flex-col gap-1.5 text-[10px] text-slate-300 font-mono">
                            <div className="text-white font-bold border-b border-white/10 pb-1 flex justify-between items-center text-[11px]">
                              <span>{zh ? '仿真数据包明细' : 'Packet Simulation Details'}</span>
                              <span className="text-[9px] px-1 bg-cyan-500/20 text-cyan-400 rounded uppercase font-sans font-bold">{event.protocol}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-400">{zh ? '链路层 (L2):' : 'Data Link (L2):'}</span>
                              <span className="text-white">Ethernet II</span>
                            </div>
                            <div className="pl-3 border-l border-white/10 flex flex-col gap-0.5 text-[9px]">
                              <div className="flex justify-between">
                                <span>Src MAC:</span>
                                <span>{event.srcMac}</span>
                              </div>
                              <div className="flex justify-between">
                                <span>Dst MAC:</span>
                                <span>{event.dstMac}</span>
                              </div>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-400">{zh ? '网络层 (L3):' : 'Network (L3):'}</span>
                              <span className="text-white">IPv4</span>
                            </div>
                            <div className="pl-3 border-l border-white/10 flex flex-col gap-0.5 text-[9px]">
                              <div className="flex justify-between">
                                <span>Src IP:</span>
                                <span>{event.srcIp}</span>
                              </div>
                              <div className="flex justify-between">
                                <span>Dst IP:</span>
                                <span>{event.dstIp}</span>
                              </div>
                              <div className="flex justify-between">
                                <span>TTL:</span>
                                <span className="text-cyan-400">{event.ttl}</span>
                              </div>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-400">{zh ? '传输/控制层 (L4):' : 'Transport/Control (L4):'}</span>
                              <span className="text-white">{event.l4Name}</span>
                            </div>
                             <div className="pl-3 border-l border-white/10 flex flex-col gap-0.5 text-[9px]">
                              <div className={`flex justify-between ${textColor}`}>
                                <span>Info:</span>
                                <span>{event.info}</span>
                              </div>
                            </div>
                            {event.deviceName && event.cpu_usage !== undefined && (
                              <>
                                <div className="border-t border-white/10 my-1 pb-1" />
                                <div className="flex justify-between text-slate-400">
                                  <span>{zh ? '网关设备:' : 'Gateway:'}</span>
                                  <span className="text-white font-bold">{event.deviceName}</span>
                                </div>
                                <div className="pl-3 border-l border-white/10 flex flex-col gap-0.5 text-[9px]">
                                  <div className="flex justify-between">
                                    <span>CPU Usage:</span>
                                    <span className={event.cpu_usage > 80 ? "text-rose-500 font-bold" : "text-cyan-400"}>
                                      {event.cpu_usage}%
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span>Memory Usage:</span>
                                    <span className={event.memory_usage > 80 ? "text-rose-500 font-bold" : "text-cyan-400"}>
                                      {event.memory_usage}%
                                    </span>
                                  </div>
                                </div>
                              </>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
        );
      })()}

      {diagResult?.return_path && (
        <div className="bg-white dark:bg-[#1f2937]/30 rounded-2xl border border-black/5 dark:border-white/5 shadow-sm p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-[#164e63] dark:text-[var(--app-text)]">
                {zh ? '回程路径实时验证' : 'Return Path Validation'}
              </h3>
              <p className="text-[11px] text-black/45 dark:text-white/45 mt-1">
                {diagResult.return_path.reason}
              </p>
            </div>
            <span className={`text-[10px] px-2.5 py-1 rounded-full border font-bold ${
              diagResult.return_path.status === 'collected'
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                : 'bg-amber-50 text-amber-700 border-amber-200'
            }`}>
              {diagResult.return_path.status === 'collected'
                ? (zh ? '已实时采集' : 'Live collected')
                : (zh ? '未知 / 未完成' : 'Unknown / incomplete')}
            </span>
          </div>
          {diagResult.return_path.hops?.length > 0 ? (
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {diagResult.return_path.hops.map((hop: any, index: number) => (
                <div key={`${hop.device_id || hop.ip}-${index}`} className="rounded-xl border border-black/5 dark:border-white/5 px-3 py-2 text-xs">
                  <div className="font-semibold text-neutral-700 dark:text-neutral-200">
                    {index + 1}. {hop.device_name || hop.ip}
                  </div>
                  <div className="font-mono text-[10px] text-neutral-500 mt-1">
                    {hop.ip} · in {hop.ingress_interface || '?'} · out {hop.egress_interface || '?'}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl bg-amber-50/70 dark:bg-amber-950/20 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
              {zh ? '当前没有可验证的回程跳点；这不是“回程正常”，而是证据未知。' : 'No return hops could be verified; this is unknown, not healthy.'}
            </div>
          )}
        </div>
      )}

      {/* ── Diagnostic Report ── */}
      {diagResult && diagResult.report && (
        <div id="npa-report-card" className="bg-white dark:bg-[#1f2937]/20 border border-neutral-200 dark:border-white/5 rounded-2xl overflow-hidden shadow-lg transition-all duration-300 hover:shadow-xl">
          {/* Card Header with Status and AI Confidence */}
          <div className="px-6 py-5 border-b border-neutral-100 dark:border-white/5 bg-neutral-50/50 dark:bg-white/[0.01] flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center shadow-sm ${
                diagResult.report.conclusion === 'interrupted'
                  ? "bg-rose-500 text-white animate-pulse"
                  : "bg-emerald-500 text-white"
              }`}>
                <FileText size={18} />
              </div>
              <div>
                <h3 className="text-base font-bold text-neutral-800 dark:text-neutral-200">
                  {zh ? 'Smart NPA 智能故障分析报告' : 'Smart NPA Path Diagnostics Report'}
                </h3>
                <p className="text-xs text-neutral-400 mt-0.5">
                  {zh ? '报告生成时间' : 'Report generated at'}: {diagResult.timestamp?.replace('T', ' ').slice(0, 19)}
                  {diagResult.diagnosis_run_id && ` · Run ${diagResult.diagnosis_run_id}`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              {/* Export Buttons */}
              <div className="flex gap-2">
                <ActionButton
                  icon={Download}
                  variant="accent"
                  onClick={() => exportToMarkdown(diagResult)}
                  title={zh ? '导出 Markdown 格式报告' : 'Export report as Markdown'}
                >
                  {zh ? '导出 Markdown' : 'Export MD'}
                </ActionButton>
                <ActionButton
                  icon={FileText}
                  variant="default"
                  onClick={() => window.print()}
                  title={zh ? '使用系统打印机保存为 PDF' : 'Save as PDF using system print dialogue'}
                >
                  {zh ? '打印 / 导出 PDF' : 'Print / PDF'}
                </ActionButton>
              </div>

              {/* AI Confidence Badge */}
              {diagResult.report.confidence && (
                <div className="flex items-center gap-2 bg-violet-50 dark:bg-violet-950/20 border border-violet-100 dark:border-violet-500/10 px-3.5 py-1.5 rounded-full">
                  <Zap size={14} className="text-violet-500 animate-bounce" />
                  <span className="text-xs text-neutral-500 dark:text-neutral-400 font-medium">
                    {zh ? 'AI 置信度' : 'AI Confidence'}:
                  </span>
                  <span className="text-xs font-bold text-violet-600 dark:text-violet-400">
                    {diagResult.report.confidence}
                  </span>
                </div>
              )}

              {/* Status Badge */}
              <span className={`text-xs px-3 py-1.5 rounded-full font-bold uppercase tracking-wider border ${
                diagResult.report.diagnostic_status === 'incomplete_evidence'
                  ? "bg-amber-100 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/30"
                  : diagResult.report.diagnostic_status === 'evidence_conflict' || diagResult.report.conclusion === 'interrupted'
                  ? "bg-rose-100 dark:bg-rose-950/30 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-800/30"
                  : "bg-emerald-100 dark:bg-emerald-950/30 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800/30"
              }`}>
                {diagResult.report.diagnostic_status === 'evidence_conflict'
                  ? (zh ? '证据冲突' : 'Evidence Conflict')
                  : diagResult.report.diagnostic_status === 'incomplete_evidence'
                    ? (zh ? '证据不完整' : 'Incomplete Evidence')
                  : diagResult.report.conclusion === 'interrupted'
                    ? (zh ? '检测到阻断' : 'Blocked')
                    : (zh ? '路径可达' : 'Reachable')}
              </span>
            </div>
          </div>

          {/* Card Body */}
          <div className="p-6 space-y-6">
            {(diagResult.snapshot || diagResult.report.diagnostic_status === 'evidence_conflict') && (
              <div className={`rounded-xl border px-4 py-3 text-xs ${diagResult.report.diagnostic_status === 'evidence_conflict' || diagResult.report.diagnostic_status === 'incomplete_evidence' ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-cyan-50 border-cyan-200 text-cyan-800'}`}>
                <div className="font-bold mb-1">
                  {diagResult.report.diagnostic_status === 'evidence_conflict'
                    ? (zh ? '本次诊断存在证据冲突，未生成确定性根因。' : 'Evidence conflict detected; no deterministic root cause was generated.')
                    : diagResult.report.diagnostic_status === 'incomplete_evidence'
                      ? (zh ? '本次诊断存在证据缺口，候选结论已限制置信度。' : 'This run has evidence gaps; confidence is capped.')
                    : (zh ? '本报告主结论使用本次诊断运行快照。' : 'The primary conclusion uses this diagnosis run snapshot.')}
                </div>
                {diagResult.snapshot && (
                  <div className="font-mono text-[10px] opacity-80">
                    {zh ? '实时来源' : 'Live sources'}: {Object.entries(diagResult.snapshot.primary_sources || {}).map(([key, value]) => `${key}=${value}`).join(' · ')}
                  </div>
                )}
                {diagResult.report.evidence_gaps?.length > 0 && (
                  <div className="mt-2 space-y-0.5">
                    {diagResult.report.evidence_gaps.map((gap: string) => <div key={gap}>· {gap}</div>)}
                  </div>
                )}
              </div>
            )}
            {/* Grid Layout for Checklist and Cause/Impact */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Left Column: AI Checklist & Verification Steps */}
              <div className="lg:col-span-5 bg-neutral-50/50 dark:bg-white/[0.01] rounded-2xl p-5 border border-neutral-100 dark:border-white/5 space-y-4">
                <div className="flex items-center gap-2 pb-2 border-b border-neutral-100 dark:border-white/5">
                  <CheckCircle2 size={16} className="text-emerald-500" />
                  <h4 className="text-xs font-bold text-neutral-800 dark:text-neutral-200 uppercase tracking-wider">
                    {zh ? 'AI 诊断验证清单' : 'AI Diagnostic Checklist'}
                  </h4>
                </div>

                <div className="space-y-3">
                  {/* Dynamic Checklist derived from steps */}
                  {diagResult.steps && diagResult.steps.map((step: any, idx: number) => {
                    let statusColor = "text-neutral-400";
                    let Icon = Minus;
                    if (step.status === 'success') {
                      statusColor = "text-emerald-500";
                      Icon = CheckCircle2;
                    } else if (step.status === 'failed') {
                      statusColor = "text-rose-500";
                      Icon = XCircle;
                    } else if (step.status === 'warning') {
                      statusColor = "text-amber-500";
                      Icon = AlertCircle;
                    }

                    return (
                      <div key={idx} className="flex items-start gap-2.5 text-xs">
                        <Icon size={14} className={`mt-0.5 flex-shrink-0 ${statusColor}`} />
                        <div>
                          <div className="font-semibold text-neutral-700 dark:text-neutral-300">
                            {step.name}
                          </div>
                          {step.message && (
                            <div className="text-[10px] text-neutral-500 dark:text-neutral-400 mt-0.5 leading-relaxed font-mono">
                              {step.message}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Evidence Panel */}
                {diagResult.report.evidence && diagResult.report.evidence.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-neutral-200/50 dark:border-white/5">
                    <span className="text-[10px] font-bold text-neutral-400 uppercase tracking-wider block mb-2">
                      {zh ? '关键根因证据' : 'Key Evidences'}
                    </span>
                    <div className="space-y-2">
                      {diagResult.report.evidence.map((ev: string, idx: number) => (
                        <div key={idx} className="flex items-start gap-2 bg-rose-50/50 dark:bg-rose-950/10 border border-rose-100 dark:border-rose-900/20 rounded-lg p-2.5">
                          <ShieldAlert size={14} className="text-rose-500 mt-0.5 flex-shrink-0" />
                          <span className="text-xs text-rose-700 dark:text-rose-300 font-medium">
                            {ev}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Right Column: Root Cause, Impact and Suggestions */}
              <div className="lg:col-span-7 space-y-4">
                {/* Conclusion Banner */}
                <div className={`rounded-xl p-4 border flex items-start gap-3 ${
                  diagResult.report.conclusion === 'interrupted'
                    ? "bg-rose-50/30 dark:bg-rose-950/10 border-rose-200/60 dark:border-rose-900/20"
                    : "bg-emerald-50/30 dark:bg-emerald-950/10 border-emerald-200/60 dark:border-emerald-900/20"
                }`}>
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    diagResult.report.conclusion === 'interrupted'
                      ? "bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400"
                      : "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400"
                  }`}>
                    {diagResult.report.conclusion === 'interrupted' ? <ShieldAlert size={16} /> : <CheckCircle2 size={16} />}
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
                      {zh ? '诊断结论' : 'Diagnostic Conclusion'}
                    </span>
                    <p className="text-sm font-bold text-neutral-800 dark:text-neutral-200 mt-1 leading-relaxed">
                      {diagResult.report.conclusion === 'interrupted' ? (
                        zh ? `路径中断于设备：${diagResult.report.interrupted_at}` : `Path blocked at device: ${diagResult.report.interrupted_at}`
                      ) : (
                        zh ? '全路径网络连通性正常' : 'End-to-end connectivity is normal'
                      )}
                    </p>
                  </div>
                </div>

                {/* Root Cause Details */}
                <div className="bg-white dark:bg-zinc-900 border border-neutral-200 dark:border-white/5 rounded-xl p-4 shadow-sm space-y-2">
                  <span className="text-[10px] font-bold text-neutral-400 uppercase tracking-wide block">
                    {zh ? '根因分析' : 'Root Cause Analysis'}
                  </span>
                  <p className="text-xs text-neutral-700 dark:text-neutral-300 font-medium font-mono leading-relaxed bg-neutral-50 dark:bg-black/20 p-3 rounded-lg border border-neutral-100 dark:border-white/[0.03]">
                    {diagResult.report.reason}
                  </p>
                </div>

                {/* Business Impact */}
                <div className="bg-white dark:bg-zinc-900 border border-neutral-200 dark:border-white/5 rounded-xl p-4 shadow-sm space-y-2">
                  <span className="text-[10px] font-bold text-neutral-400 uppercase tracking-wide block">
                    {zh ? '业务影响范围' : 'Business Impact'}
                  </span>
                  <p className="text-xs text-neutral-700 dark:text-neutral-300 leading-relaxed font-mono bg-neutral-50 dark:bg-black/20 p-3 rounded-lg border border-neutral-100 dark:border-white/[0.03]">
                    {diagResult.report.impact}
                  </p>
                </div>

                {/* Suggestions */}
                <div className="bg-gradient-to-r from-emerald-50 to-teal-50/30 dark:from-emerald-950/20 dark:to-teal-950/10 border border-emerald-200/40 dark:border-emerald-500/20 rounded-xl p-4 shadow-sm space-y-2">
                  <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wide block">
                    {zh ? '优化与修复建议' : 'Actionable Suggestion'}
                  </span>
                  <p className="text-xs text-emerald-800 dark:text-emerald-300 font-medium leading-relaxed">
                    {diagResult.report.suggestion}
                  </p>
                </div>
              </div>
            </div>

            {/* CLI Repair Commands Section */}
            {diagResult.report.repair_commands && (
              <div className="bg-neutral-900 dark:bg-black/40 border border-neutral-800 rounded-xl p-5 shadow-inner space-y-3 relative group">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-red-500" />
                    <div className="w-2.5 h-2.5 rounded-full bg-yellow-500" />
                    <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
                    <span className="text-[10px] text-neutral-500 dark:text-neutral-400 font-mono ml-2">
                      {zh ? '建议配置修复指令 (设备: ' + diagResult.report.interrupted_at + ')' : 'Recommended CLI Fixes (' + diagResult.report.interrupted_at + ')'}
                    </span>
                  </div>
                  <ActionButton
                    icon={copiedCmd ? Check : Copy}
                    variant={copiedCmd ? 'success' : 'accent'}
                    onClick={() => {
                      navigator.clipboard.writeText(diagResult.report.repair_commands);
                      setCopiedCmd(true);
                      setTimeout(() => setCopiedCmd(false), 2000);
                    }}
                  >
                    {copiedCmd ? (zh ? '已复制' : 'Copied!') : (zh ? '复制代码' : 'Copy Code')}
                  </ActionButton>
                </div>
                <pre className="text-xs text-neutral-300 font-mono overflow-x-auto whitespace-pre leading-relaxed max-h-60 pt-2 custom-scrollbar">
                  {diagResult.report.repair_commands}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
      </>)}
      </div>

      {/* ── CMDB Hop Device Detail Modal ── */}
      {diagResult && diagResult.hops && activeHopIdx !== null && (() => {
        const activeHop = diagResult.hops[activeHopIdx];
        if (!activeHop) return null;
        const currentHop = activeHop.is_ecmp ? (activeHop.paths[activeSubHopIdx] || activeHop.paths[0] || activeHop) : activeHop;
        const cmdbDevice = findDeviceByIp(currentHop.ip);
        const isSrv = cmdbDevice ? isServerPlatform(cmdbDevice.platform || '') : false;
        return (
          <div 
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 dark:bg-black/70 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={() => setActiveHopIdx(null)}
          >
            <div 
              className="w-full max-w-sm mx-4 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-black/10 dark:border-white/10 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div className="px-5 py-4 border-b border-black/5 dark:border-white/5 bg-gradient-to-r from-[#0891b2]/5 to-transparent flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${cmdbDevice ? (isSrv ? 'bg-violet-50 dark:bg-violet-900/30' : 'bg-cyan-50 dark:bg-cyan-900/30') : 'bg-neutral-100 dark:bg-neutral-800'}`}>
                    {cmdbDevice ? (isSrv ? <Monitor size={16} className="text-violet-500" /> : <Router size={16} className="text-[#0891b2]" />) : <Server size={16} className="text-neutral-400" />}
                  </div>
                  <div>
                    <div className="text-sm font-bold text-[#164e63] dark:text-[var(--app-text)]">{currentHop.device_name}</div>
                    <div className="text-xs text-black/45 dark:text-white/45 font-mono">{currentHop.ip}</div>
                  </div>
                </div>
                <button 
                  onClick={() => setActiveHopIdx(null)} 
                  className="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 text-black/40 dark:text-white/40 transition-colors"
                >
                  <X size={15} />
                </button>
              </div>

              {/* ECMP Sub-hops Selector Tab */}
              {activeHop.is_ecmp && (
                <div className="flex border-b border-black/5 dark:border-white/5 bg-black/[0.01] dark:bg-white/[0.01] px-5 py-2 gap-2">
                  {activeHop.paths.map((p: any, idx: number) => (
                    <button
                      key={idx}
                      onClick={() => setActiveSubHopIdx(idx)}
                      className={`text-xs font-semibold px-2.5 py-1 rounded-lg transition-all ${
                        activeSubHopIdx === idx 
                          ? 'bg-[#0891b2] text-white shadow-sm' 
                          : 'text-black/50 dark:text-white/50 hover:bg-black/5 dark:hover:bg-white/5'
                      }`}
                    >
                      {p.device_name || `Path ${idx + 1}`}
                    </button>
                  ))}
                </div>
              )}

              {/* Modal Body */}
              <div className="px-5 py-4 space-y-4">
                {cmdbDevice ? (
                  <>
                    {/* Device Info Grid */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="bg-neutral-50 dark:bg-white/[0.02] border border-black/[0.03] dark:border-white/[0.02] rounded-xl px-3 py-2.5">
                        <div className="text-[10px] text-black/35 dark:text-white/35 uppercase font-semibold tracking-wider">{zh ? '设备型号' : 'Model'}</div>
                        <div className="text-xs font-mono font-semibold text-[#164e63] dark:text-[var(--app-text)] mt-1 truncate" title={cmdbDevice.model}>{cmdbDevice.model || '—'}</div>
                      </div>
                      <div className="bg-neutral-50 dark:bg-white/[0.02] border border-black/[0.03] dark:border-white/[0.02] rounded-xl px-3 py-2.5">
                        <div className="text-[10px] text-black/35 dark:text-white/35 uppercase font-semibold tracking-wider">{zh ? '系统平台' : 'Platform'}</div>
                        <div className="text-xs font-mono font-semibold text-[#164e63] dark:text-[var(--app-text)] mt-1 truncate" title={cmdbDevice.platform}>{cmdbDevice.platform || '—'}</div>
                      </div>
                    </div>

                    {/* CPU & Memory Utilization */}
                    <div className="space-y-3">
                      <div>
                        <div className="flex justify-between text-xs font-medium">
                          <span className="text-black/50 dark:text-white/50 flex items-center gap-1.5"><Cpu size={12} /> CPU 使用率</span>
                          <span className="font-mono font-bold text-[#164e63] dark:text-[var(--app-text)]">{cmdbDevice.cpu_usage ?? '—'}%</span>
                        </div>
                        <div className="h-2 rounded-full bg-neutral-100 dark:bg-white/5 mt-1.5 overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-[#0891b2] to-[#06b6d4] transition-all" style={{ width: `${cmdbDevice.cpu_usage ?? 0}%` }} />
                        </div>
                      </div>
                      <div>
                        <div className="flex justify-between text-xs font-medium">
                          <span className="text-black/50 dark:text-white/50 flex items-center gap-1.5"><MemoryStick size={12} /> 内存使用率</span>
                          <span className="font-mono font-bold text-[#164e63] dark:text-[var(--app-text)]">{cmdbDevice.memory_usage ?? '—'}%</span>
                        </div>
                        <div className="h-2 rounded-full bg-neutral-100 dark:bg-white/5 mt-1.5 overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-violet-400 to-violet-500 transition-all" style={{ width: `${cmdbDevice.memory_usage ?? 0}%` }} />
                        </div>
                      </div>
                    </div>

                    {/* Details status row */}
                    <div className="flex items-center gap-2 text-xs border-t border-black/5 dark:border-white/5 pt-3.5">
                      <span className={`w-2.5 h-2.5 rounded-full ${cmdbDevice.status === 'online' ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-rose-500 shadow-sm shadow-rose-500/50'}`} />
                      <span className="font-semibold text-black/60 dark:text-white/60">{cmdbDevice.status === 'online' ? (zh ? '设备在线 (Online)' : 'Online') : (zh ? '设备离线 (Offline)' : 'Offline')}</span>
                      {cmdbDevice.vendor && (
                        <span className="text-black/40 dark:text-white/40 ml-auto font-mono text-[10px] uppercase font-semibold">{cmdbDevice.vendor}</span>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="text-center py-6">
                    <div className="text-xs text-black/40 dark:text-white/40">{zh ? '该 IP 设备未在 CMDB 资产中注册' : 'Device not found in CMDB'}</div>
                  </div>
                )}
              </div>

              {/* Modal Footer / Actions */}
              <div className="px-5 py-3.5 bg-neutral-50/50 dark:bg-white/[0.01] border-t border-black/5 dark:border-white/5 flex gap-3">
                <a
                  href={isSrv ? `/monitor/servers?q=${encodeURIComponent(activeHop.ip)}` : `/monitor/networks?q=${encodeURIComponent(activeHop.ip)}`}
                  className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl bg-[#06b6d4]/5 hover:bg-[#06b6d4]/10 text-[#0891b2] text-xs font-semibold transition-colors"
                >
                  <Activity size={13} /> {zh ? '监控中心' : 'Monitor'}
                  <ExternalLink size={10} className="ml-0.5 opacity-60" />
                </a>
                <a
                  href={`/access/workspace?q=${encodeURIComponent(activeHop.ip)}`}
                  className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl bg-violet-50 dark:bg-violet-900/20 hover:bg-violet-100 dark:hover:bg-violet-900/30 text-violet-600 dark:text-violet-400 text-xs font-semibold transition-colors"
                >
                  <Cable size={13} /> {zh ? '登录排障' : 'SSH'}
                  <ExternalLink size={10} className="ml-0.5 opacity-60" />
                </a>
              </div>
            </div>
          </div>
        );
      })()}
      {/* ── NSOT Collection Policy Modal ── */}
      {nsotPolicyModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="bg-white dark:bg-[#0f172a] rounded-2xl border border-black/10 dark:border-white/10 shadow-2xl w-full max-w-4xl max-h-[88vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-black/5 dark:border-white/10 bg-slate-50/50 dark:bg-slate-900/50">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-cyan-700 flex items-center justify-center text-white shadow-md shadow-cyan-500/20">
                  <Sliders size={18} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900 dark:text-white">
                    {zh ? '网络事实库 (NSOT) 设备采集能力策略' : 'Device NSOT Collection Policies'}
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                    {zh ? '控制哪些设备参与 NSOT 事实库的转发表项、动态协议与拓扑数据采集' : 'Control which collectors run per device during unified NSOT reality collection'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setNsotPolicyModalOpen(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body (Split Left / Right) */}
            <div className="flex-1 flex overflow-hidden divide-x divide-black/5 dark:divide-white/10 min-h-[420px]">
              {/* Left Device List */}
              <div className="w-1/3 flex flex-col bg-slate-50/30 dark:bg-slate-950/20 min-w-[240px]">
                <div className="p-3 border-b border-black/5 dark:border-white/10">
                  <div className="relative">
                    <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type="text"
                      value={nsotPlanSearch}
                      onChange={(e) => setNsotPlanSearch(e.target.value)}
                      placeholder={zh ? '搜索设备...' : 'Search devices...'}
                      className="w-full pl-8 pr-2.5 py-1.5 rounded-lg text-xs bg-white dark:bg-slate-900 border border-black/10 dark:border-white/10 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                    />
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                  {nsotPlansLoading ? (
                    <div className="flex items-center justify-center py-10 text-xs text-slate-400">
                      <Loader2 size={16} className="animate-spin mr-2 text-cyan-500" />
                      {zh ? '加载中...' : 'Loading...'}
                    </div>
                  ) : nsotPlans
                      .filter((row) => {
                        const q = nsotPlanSearch.trim().toLowerCase();
                        if (!q) return true;
                        return (
                          (row.device?.hostname || '').toLowerCase().includes(q) ||
                          (row.device?.ip_address || '').toLowerCase().includes(q) ||
                          (row.device?.platform || '').toLowerCase().includes(q) ||
                          (row.device?.role || '').toLowerCase().includes(q)
                        );
                      })
                      .map((row) => {
                        const isSelected = row.device?.id === nsotSelectedPlanDeviceId;
                        const hasOverrides = row.plan?.overrides && Object.keys(row.plan.overrides).length > 0;
                        return (
                          <button
                            key={row.device?.id}
                            onClick={() => {
                              setNsotSelectedPlanDeviceId(row.device?.id);
                              setNsotPlanMessage('');
                            }}
                            className={`w-full text-left p-2.5 rounded-xl text-xs transition-all flex items-center justify-between ${
                              isSelected
                                ? 'bg-cyan-500 text-white shadow-md shadow-cyan-500/20'
                                : 'hover:bg-black/5 dark:hover:bg-white/5 text-slate-700 dark:text-slate-200'
                            }`}
                          >
                            <div className="truncate pr-2">
                              <div className="font-semibold truncate">{row.device?.hostname || row.device?.ip_address}</div>
                              <div className={`text-[10px] font-mono truncate ${isSelected ? 'text-white/80' : 'text-slate-400'}`}>
                                {row.device?.ip_address} · {row.device?.platform || 'generic'}
                              </div>
                            </div>
                            {hasOverrides && (
                              <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
                                isSelected ? 'bg-white/20 text-white' : 'bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300'
                              }`}>
                                {zh ? '自定义' : 'Custom'}
                              </span>
                            )}
                          </button>
                        );
                      })}
                </div>
              </div>

              {/* Right Policy Detail */}
              <div className="flex-1 flex flex-col overflow-y-auto p-6 bg-white dark:bg-[#0f172a]">
                {(() => {
                  const selected = nsotPlans.find((row) => row.device?.id === nsotSelectedPlanDeviceId);
                  if (!selected) {
                    return (
                      <div className="flex-1 flex items-center justify-center text-xs text-slate-400">
                        {zh ? '请从左侧选择设备以查看其采集策略' : 'Select a device from the left to view its collection policy'}
                      </div>
                    );
                  }

                  const effective = selected.plan?.effective || {};
                  const overrides = selected.plan?.overrides || {};
                  const profile = selected.plan?.profile || selected.device?.role || 'default';

                  const collectorGroups = [
                    {
                      groupTitle: zh ? '基础与接口事实' : 'Basics & Interface Facts',
                      items: [
                        { key: 'reachability', label: zh ? '连通性测试 (Ping)' : 'Reachability', desc: zh ? '测试管理 IP 可达性' : 'ICMP reachability check' },
                        { key: 'interface_status', label: zh ? '接口状态与物理层' : 'Interface Status', desc: zh ? '采集接口 Up/Down 与速率' : 'Port oper/admin status and speed' },
                        { key: 'interface_ip', label: zh ? '接口 IP 与 SVI' : 'Interface IP / SVI', desc: zh ? '采集接口 IP 地址与子网' : 'Port IPs, masks, and SVI bindings' },
                      ],
                    },
                    {
                      groupTitle: zh ? '二层拓扑与转发表项' : 'L2 Topology & Forwarding Facts',
                      items: [
                        { key: 'arp', label: zh ? 'ARP 映射表' : 'ARP Table', desc: zh ? '采集 IP 与 MAC 对应表项' : 'IP-to-MAC resolution table' },
                        { key: 'mac_table', label: zh ? 'MAC 转发表' : 'MAC Table', desc: zh ? '采集端口与 MAC 映射' : 'Switchport MAC forwarding table' },
                        { key: 'lldp', label: zh ? 'LLDP / CDP 拓扑邻居' : 'LLDP / CDP Neighbors', desc: zh ? '发现设备直连邻居与端口' : 'Direct neighbor port discovery' },
                        { key: 'vlan', label: zh ? 'VLAN 记录与划分' : 'VLAN Records', desc: zh ? '采集 VLAN 配置与 Trunk 划分' : 'VLANs and port memberships' },
                      ],
                    },
                    {
                      groupTitle: zh ? '三层路由与协议状态' : 'L3 Routing & Protocol Facts',
                      items: [
                        { key: 'routes', label: zh ? 'IP 路由表 (RIB)' : 'IP Route Table', desc: zh ? '采集全局路由表项' : 'Global routing table snapshot' },
                        { key: 'bgp', label: zh ? 'BGP 邻居与 RIB' : 'BGP Peers & Routes', desc: zh ? '采集 BGP 对等体与路由' : 'BGP sessions and prefix table' },
                        { key: 'ospf', label: zh ? 'OSPF 邻居状态' : 'OSPF Neighbors', desc: zh ? '采集 OSPF 邻接关系' : 'OSPF adjacency states' },
                      ],
                    },
                    {
                      groupTitle: zh ? '推导计算与 IPAM 事实' : 'Derivation & IPAM Projection',
                      items: [
                        { key: 'endpoint_location', label: zh ? '终端定位计算' : 'Endpoint Location', desc: zh ? '参与 IP 接入端口定位推导' : 'Include in endpoint location derivation' },
                        { key: 'prefix_projection', label: zh ? 'Prefix 前缀投影' : 'Prefix Projection', desc: zh ? '投影至 IPAM 网段事实库' : 'Project to IPAM prefix facts' },
                      ],
                    },
                  ];

                  return (
                    <div className="space-y-6">
                      {/* Device meta header */}
                      <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-xl bg-slate-50 dark:bg-slate-900/50 border border-black/5 dark:border-white/5">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-slate-900 dark:text-white">
                              {selected.device?.hostname || selected.device?.ip_address}
                            </span>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-100 dark:bg-cyan-950 text-cyan-700 dark:text-cyan-300 font-semibold uppercase">
                              {profile}
                            </span>
                          </div>
                          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 font-mono">
                            IP: {selected.device?.ip_address} · {zh ? '平台' : 'Platform'}: {selected.device?.platform || 'generic'} · {zh ? '状态' : 'Status'}: {selected.device?.status || 'active'}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={resetNsotCollectionPlan}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                          >
                            {zh ? '恢复角色默认策略' : 'Reset to Default'}
                          </button>
                        </div>
                      </div>

                      {nsotPlanMessage && (
                        <div className="text-xs font-medium text-cyan-600 dark:text-cyan-400 px-1 animate-in fade-in">
                          {nsotPlanMessage}
                        </div>
                      )}

                      {/* Grouped collectors list */}
                      <div className="space-y-5">
                        {collectorGroups.map((grp) => (
                          <div key={grp.groupTitle} className="space-y-2">
                            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                              {grp.groupTitle}
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                              {grp.items.map((it) => {
                                const isEnabled = Boolean(effective[it.key]);
                                const hasExplicitOverride = Object.prototype.hasOwnProperty.call(overrides, it.key);
                                return (
                                  <div
                                    key={it.key}
                                    className={`p-3 rounded-xl border transition-all flex items-start justify-between gap-3 ${
                                      isEnabled
                                        ? 'bg-emerald-50/40 dark:bg-emerald-950/10 border-emerald-200/80 dark:border-emerald-800/40'
                                        : 'bg-slate-50/50 dark:bg-slate-900/30 border-slate-200/60 dark:border-slate-800/60'
                                    }`}
                                  >
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2">
                                        <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
                                          {it.label}
                                        </span>
                                        {hasExplicitOverride && (
                                          <span className="text-[9px] px-1 py-0.2 rounded font-medium bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-400">
                                            {zh ? '覆盖' : 'Override'}
                                          </span>
                                        )}
                                      </div>
                                      <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5 leading-snug">
                                        {it.desc}
                                      </div>
                                    </div>
                                    <button
                                      onClick={() => updateNsotCollectionPlan(it.key, !isEnabled)}
                                      className={`px-2.5 py-1 rounded-lg text-xs font-semibold shrink-0 transition-colors ${
                                        isEnabled
                                          ? 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm'
                                          : 'bg-slate-200 dark:bg-slate-800 text-slate-500 hover:bg-slate-300 dark:hover:bg-slate-700'
                                      }`}
                                    >
                                      {isEnabled ? (zh ? '已开启' : 'ON') : (zh ? '已关闭' : 'OFF')}
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end px-6 py-3.5 border-t border-black/5 dark:border-white/10 bg-slate-50/50 dark:bg-slate-900/50">
              <button
                onClick={() => setNsotPolicyModalOpen(false)}
                className="px-5 py-2 rounded-xl text-xs font-bold bg-[#06b6d4] hover:bg-[#0891b2] text-white shadow-md shadow-cyan-500/20 transition-all active:scale-95"
              >
                {zh ? '完成' : 'Done'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

export default IPLocatorPage;
